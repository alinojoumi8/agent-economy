"""Explicit storage-version routing; legacy SQLite remains the default."""
from contextlib import contextmanager
from pathlib import Path
import tempfile


def checkpoint_format(config: dict) -> str:
    value = config.get("checkpoint_format", "sqlite-v1")
    if value not in ("sqlite-v1", "incremental-v2"):
        raise ValueError("checkpoint_format must be sqlite-v1 or incremental-v2")
    return value


def checkpoint_path(directory: Path, run_id: str, tick: int, config: dict) -> Path:
    suffix = ".icp.json" if checkpoint_format(config) == "incremental-v2" else ".db"
    path = directory / f"{run_id}_t{tick}{suffix}"
    if path.parent != directory:
        raise ValueError("checkpoint identity escapes its directory")
    return path


def is_incremental(path: str | Path) -> bool:
    return Path(path).name.endswith(".icp.json")


@contextmanager
def checkpoint_database(path: str | Path, *, max_bytes: int = 64 * 1024**3,
                        scratch_dir: str | Path | None = None):
    """Resolve a v2 artifact into a verified private SQLite copy for readers.

    Materialization is intentionally explicit: restore has its own measured
    cost and is never hidden in checkpoint-save timings. Legacy paths pass
    through untouched, so existing historical checks retain their semantics.
    """
    source = Path(path)
    if not is_incremental(source):
        yield source
        return
    from engine.incremental_checkpoint import restore_incremental
    parent = Path(scratch_dir) if scratch_dir is not None else source.absolute().parent
    with tempfile.TemporaryDirectory(prefix=".manyworld-checkpoint-", dir=parent) as directory:
        target = Path(directory) / "checkpoint.db"
        restore_incremental(source, target, max_bytes=max_bytes)
        yield target
