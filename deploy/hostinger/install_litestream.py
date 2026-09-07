"""Install the pinned official binary with its release SHA-256 (build time)."""
import hashlib
import argparse
import io
import platform
import tarfile
import urllib.request
from pathlib import Path

VERSION = "0.5.17"
RELEASES = {
    "x86_64": ("x86_64", "cfb371176d164437ae869f8351cfde49bd1804ae71c61923f75c9cba9c9c006d"),
    "aarch64": ("arm64", "f8ca4a050095c1efbda2c4365172e61bf9d955ea0d9ac42f448b52e51819baa5"),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("/usr/local/bin/litestream"))
    args = parser.parse_args()
    architecture, checksum = RELEASES[platform.machine()]
    # Asset names and checksums are pinned together, not inferred at deploy time.
    url = (f"https://github.com/benbjohnson/litestream/releases/download/v{VERSION}/"
           f"litestream-{VERSION}-linux-{architecture}.tar.gz")
    with urllib.request.urlopen(url, timeout=60) as response:
        payload = response.read(100 * 1024 * 1024)
    if hashlib.sha256(payload).hexdigest() != checksum:
        raise RuntimeError("Litestream release checksum mismatch")
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        members = [member for member in archive.getmembers()
                   if Path(member.name).name == "litestream" and member.isfile()]
        if len(members) != 1:
            raise RuntimeError("unexpected Litestream release layout")
        destination = args.output
        destination.parent.mkdir(parents=True, exist_ok=True)
        with archive.extractfile(members[0]) as incoming:
            destination.write_bytes(incoming.read())
        destination.chmod(0o755)


if __name__ == "__main__":
    main()
