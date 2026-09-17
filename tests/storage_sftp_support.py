"""Disposable loopback SFTP server for recovery tests; never a hosted service."""
from __future__ import annotations

from contextlib import contextmanager
import errno
import os
from pathlib import Path
import socket
import threading


@contextmanager
def sftp_replica(root, key_directory, *, username="drill", read_only=False):
    import paramiko

    root = Path(root).resolve()
    host_key, client_key = paramiko.RSAKey.generate(2048), paramiko.RSAKey.generate(2048)
    key_path = Path(key_directory) / "drill-key"
    client_key.write_private_key_file(str(key_path))
    key_path.chmod(0o600)

    class Authentication(paramiko.ServerInterface):
        def get_allowed_auths(self, username):
            return "publickey"

        def check_auth_publickey(self, username, key):
            return paramiko.AUTH_SUCCESSFUL if username == allowed_user and key == client_key else paramiko.AUTH_FAILED

        def check_channel_request(self, kind, channel_id):
            return paramiko.OPEN_SUCCEEDED if kind == "session" else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    class Files(paramiko.SFTPServerInterface):
        def local(self, path):
            candidate = (root / path.lstrip("/")).resolve()
            if not candidate.is_relative_to(root):
                raise OSError(errno.EACCES, "outside test replica")
            return candidate

        def _operation(self, operation):
            try:
                return operation()
            except OSError as exc:
                return paramiko.SFTPServer.convert_errno(exc.errno)

        def stat(self, path):
            return self._operation(lambda: paramiko.SFTPAttributes.from_stat(self.local(path).stat()))

        lstat = stat

        def chattr(self, path, attributes):
            if read_only:
                return paramiko.SFTP_PERMISSION_DENIED
            return self._operation(lambda: (paramiko.SFTPServer.set_file_attr(str(self.local(path)), attributes),
                                            paramiko.SFTP_OK)[1])

        def list_folder(self, path):
            def listing():
                entries = []
                for item in self.local(path).iterdir():
                    attributes = paramiko.SFTPAttributes.from_stat(item.stat())
                    attributes.filename = item.name
                    entries.append(attributes)
                return entries
            return self._operation(listing)

        def open(self, path, flags, attributes):
            if read_only and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                return paramiko.SFTP_PERMISSION_DENIED
            def opened():
                descriptor = os.open(self.local(path), flags, 0o600)
                mode = "r+b" if flags & os.O_RDWR else "wb" if flags & os.O_WRONLY else "rb"
                stream = os.fdopen(descriptor, mode)
                class Handle(paramiko.SFTPHandle):
                    def stat(self):
                        return paramiko.SFTPAttributes.from_stat(os.fstat(stream.fileno()))

                    def chattr(self, attributes):
                        if read_only:
                            return paramiko.SFTP_PERMISSION_DENIED
                        paramiko.SFTPServer.set_file_attr(str(self.filename), attributes)
                        return paramiko.SFTP_OK
                handle = Handle(flags)
                handle.filename = self.local(path)
                handle.readfile = stream
                handle.writefile = stream
                return handle
            return self._operation(opened)

        def mkdir(self, path, attributes):
            if read_only:
                return paramiko.SFTP_PERMISSION_DENIED
            return self._operation(lambda: (self.local(path).mkdir(), paramiko.SFTP_OK)[1])

        def rmdir(self, path):
            if read_only:
                return paramiko.SFTP_PERMISSION_DENIED
            return self._operation(lambda: (self.local(path).rmdir(), paramiko.SFTP_OK)[1])

        def remove(self, path):
            if read_only:
                return paramiko.SFTP_PERMISSION_DENIED
            return self._operation(lambda: (self.local(path).unlink(), paramiko.SFTP_OK)[1])

        def rename(self, old, new):
            if read_only:
                return paramiko.SFTP_PERMISSION_DENIED
            return self._operation(lambda: (os.rename(self.local(old), self.local(new)), paramiko.SFTP_OK)[1])

        posix_rename = rename

    allowed_user = username
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.settimeout(0.2)
    stopped = threading.Event()
    transports = []

    def accept():
        while not stopped.is_set():
            try:
                client, _ = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            transport = paramiko.Transport(client)
            transports.append(transport)
            transport.add_server_key(host_key)
            transport.set_subsystem_handler("sftp", paramiko.SFTPServer, Files)
            try:
                transport.start_server(server=Authentication())
            except (EOFError, paramiko.SSHException):
                transport.close()

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    try:
        yield {"type": "sftp", "host": f"127.0.0.1:{listener.getsockname()[1]}",
               "user": username, "key-path": str(key_path),
               "host-key": f"{host_key.get_name()} {host_key.get_base64()}", "path": "/backup"}
    finally:
        stopped.set()
        listener.close()
        for transport in transports:
            transport.close()
        thread.join(timeout=3)
