"""Operational storage controls, independent of economic/replay semantics."""
from __future__ import annotations

import os
import shutil
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Mapping


GiB = 1024 ** 3


class StorageBudgetExceeded(RuntimeError):
    def __init__(self, kind: str, used: int, limit: int):
        self.kind, self.used, self.limit = kind, used, limit
        super().__init__(f"storage {kind} limit reached")

    def as_dict(self) -> dict:
        return {"kind": self.kind, "bytes": self.used, "limit_bytes": self.limit}


@dataclass(frozen=True)
class StoragePolicy:
    checkpoint_keep_last: int = 4
    checkpoint_max_bytes: int = 20 * GiB
    min_free_bytes: int = 5 * GiB
    max_run_bytes: int = 10 * GiB
    max_tenant_bytes: int = 50 * GiB
    compress_payloads: bool = True
    durable_writes: bool = True

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            expected = bool if field.name in {"compress_payloads", "durable_writes"} else int
            if type(value) is not expected:
                raise ValueError(f"storage_policy.{field.name} must be {expected.__name__}")
            if expected is int and value < 0:
                raise ValueError(f"storage_policy.{field.name} must be nonnegative")
        if not 2 <= self.checkpoint_keep_last <= 10_000:
            raise ValueError("storage_policy.checkpoint_keep_last must be between 2 and 10000")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "StoragePolicy | None":
        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise ValueError("storage_policy must be a mapping")
        if set(value) - {field.name for field in fields(cls)}:
            raise ValueError("unknown storage_policy setting")
        return cls(**dict(value))

    def as_dict(self) -> dict:
        return asdict(self)

    def apply(self, store: Any) -> None:
        if not store.read_only:
            store.compress_payloads = self.compress_payloads
            if self.durable_writes:
                store.execute("PRAGMA synchronous = FULL")

    def check_run(self, database: str | Path, *, additional_bytes: int = 0) -> None:
        path = Path(database).resolve()
        size = database_bytes(path)
        if self.max_run_bytes and size + additional_bytes > self.max_run_bytes:
            raise StorageBudgetExceeded("run", size + additional_bytes, self.max_run_bytes)
        self.check_free(path.parent, additional_bytes=additional_bytes)

    def check_free(self, directory: str | Path, *, additional_bytes: int = 0) -> None:
        path = Path(directory).resolve()
        while not path.exists():
            path = path.parent
        free = shutil.disk_usage(path).free
        required = self.min_free_bytes + additional_bytes
        if free < required:
            raise StorageBudgetExceeded("free_space", free, required)

    def check_tenant(self, directory: str | Path, *, additional_bytes: int = 0) -> None:
        if not self.max_tenant_bytes:
            return
        total = directory_bytes(directory)
        if total + additional_bytes > self.max_tenant_bytes:
            raise StorageBudgetExceeded("tenant", total + additional_bytes, self.max_tenant_bytes)


def database_bytes(path: str | Path) -> int:
    return sum(candidate.stat().st_size for candidate in (
        Path(path), Path(f"{path}-wal"), Path(f"{path}-shm")) if candidate.is_file())


def directory_bytes(root: str | Path) -> int:
    """Measure regular files without following symlink/reparse directories."""
    root = Path(root)
    if not root.exists():
        return 0
    total = 0
    for directory, names, files in os.walk(root, followlinks=False):
        names[:] = [name for name in names if not _is_link(Path(directory) / name)]
        for name in files:
            candidate = Path(directory) / name
            if not _is_link(candidate) and candidate.is_file():
                total += candidate.stat().st_size
    return total


def _is_link(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)
