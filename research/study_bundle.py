"""Portable private study evidence with bounded extraction and fresh verification."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
import zipfile

from research.artifacts import digest_json, file_sha256, json_bytes, publish_json
from research.study_results import StudyArtifactError, StudyIdentityChanged, load_study_result, verification_identity

CONTRACT = "study-evidence-bundle-v1"
CLASSIFICATION = "private_research_evidence"
MAX_FILES = 8192
MAX_BYTES = 2 * 1024 ** 3
MAX_INDEX_BYTES = 8 * 1024 ** 2


def _name(value: str) -> str:
    # A single portable namespace also rejects Windows ADS, devices and aliases.
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise StudyArtifactError("invalid bundle member path")
    parts = value.split("/")
    if (any(part in {"", ".", ".."} or part[-1:] in {".", " "}
            or any(ord(c) < 32 or c in '<>"|?*' for c in part)
            or re.fullmatch(r"(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", part)
            for part in parts) or len(value) > 240):
        raise StudyArtifactError("unsafe or nonportable bundle member path")
    return value


def _linked(path: Path) -> bool:
    info = path.lstat()
    return path.is_symlink() or bool(getattr(info, "st_file_attributes", 0)
                                   & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _inventory(result: dict, *, max_bytes: int) -> dict[str, dict]:
    entries, total = {}, 0
    roots = (("data", Path(result["verification"]["data_dir"])),
             ("reports/studies", Path(result["verification"]["report_dir"])))
    for prefix, root in roots:
        relative = PurePosixPath(root.parent.name) / root.name
        pending = [root]
        while pending:
            directory = pending.pop()
            if _linked(directory):
                raise StudyArtifactError("study bundles cannot contain linked directories")
            for path in sorted(directory.iterdir()):
                if _linked(path):
                    raise StudyArtifactError("study bundles cannot contain linked files")
                if path.is_dir():
                    pending.append(path)
                    continue
                if not path.is_file():
                    raise StudyArtifactError("study bundles require ordinary files")
                name = _name(str(PurePosixPath(prefix) / relative / path.relative_to(root).as_posix()))
                size = path.stat().st_size
                total += size
                if len(entries) >= MAX_FILES or total > max_bytes:
                    raise StudyArtifactError("study exceeds the bundle size or file limit")
                entries[name] = {"path": path, "size": size, "sha256": file_sha256(path)}
    return entries


def _proof(result: dict) -> dict:
    verification = {key: value for key, value in result["verification"].items()
                    if key not in {"data_dir", "report_dir"}}
    return {"verification": verification, "summary_sha256": digest_json(result["summary"]),
            "attempts_sha256": digest_json(result["results"])}


def export_study_bundle(result_path: str | Path, destination: str | Path, *,
                        data_root: str | Path = "data/studies", out_dir: str | Path = "reports/out",
                        expected_sha256: str | None = None, expected_verification: str | None = None,
                        max_bytes: int = MAX_BYTES) -> dict:
    """Copy original bytes, including exclusions, into an exclusively published ZIP."""
    if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_BYTES:
        raise StudyArtifactError("invalid bundle size limit")
    result = load_study_result(result_path, data_root=data_root, out_dir=out_dir,
                               expected_sha256=expected_sha256)
    if expected_verification is not None and verification_identity(result) != expected_verification:
        raise StudyIdentityChanged("Study evidence changed; verify it again before exporting.")
    requested_target = Path(destination)
    if requested_target.exists() or requested_target.is_symlink():
        raise FileExistsError("bundle destination already exists")
    target = requested_target.resolve()
    for root in (result["verification"]["data_dir"], result["verification"]["report_dir"]):
        if target.is_relative_to(Path(root)):
            raise StudyArtifactError("bundle destination must be outside its source study")
    entries = _inventory(result, max_bytes=max_bytes)
    result_name = next(name for name, item in entries.items() if item["path"].resolve() == Path(result_path).resolve())
    index = {"contract": CONTRACT, "classification": CLASSIFICATION,
             "batch_id": result["batch"]["batch_id"], "manifest_sha256": result["batch"]["manifest_sha256"],
             "result_path": result_name, "result_sha256": result["verification"]["result_sha256"],
             "files": {name: {k: v for k, v in item.items() if k != "path"}
                       for name, item in sorted(entries.items())}, "proof": _proof(result),
             "scope": "Recorded evidence and declared inputs; source checkout and runtime are not bundled."}
    index_bytes = json_bytes(index)
    if len(index_bytes) > MAX_INDEX_BYTES:
        raise StudyArtifactError("bundle index exceeds its size limit")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w+b") as output:
            with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                for name, item in sorted(entries.items()):
                    digest, size = hashlib.sha256(), 0
                    with item["path"].open("rb") as source, archive.open(name, "w", force_zip64=True) as member:
                        while chunk := source.read(1024 * 1024):
                            size += len(chunk)
                            if size > item["size"]:
                                raise StudyArtifactError("study changed during bundle export")
                            digest.update(chunk)
                            member.write(chunk)
                    if size != item["size"] or digest.hexdigest() != item["sha256"]:
                        raise StudyArtifactError("study changed during bundle export")
                archive.writestr("bundle.json", index_bytes)
            output.flush()
            os.fsync(output.fileno())
        # Recheck the live sources and their logical proof after all bytes were read.
        after = load_study_result(result_path, data_root=data_root, out_dir=out_dir,
                                  expected_sha256=index["result_sha256"])
        if _proof(after) != index["proof"] or _inventory(after, max_bytes=max_bytes) != entries:
            raise StudyArtifactError("study changed during bundle export")
        with zipfile.ZipFile(temporary) as archive:
            _checked_index(archive, max_bytes=max_bytes)
        os.link(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return {"path": str(target), "sha256": file_sha256(target), "files": len(entries),
            "bytes": target.stat().st_size, "classification": CLASSIFICATION,
            "verification_status": result["verification"]["status"]}


def _checked_index(archive: zipfile.ZipFile, *, max_bytes: int) -> tuple[dict, dict]:
    items = archive.infolist()
    if len(items) > MAX_FILES + 1:
        raise StudyArtifactError("bundle exceeds its file limit")
    names, aliases, total = {}, set(), 0
    for item in items:
        name = _name(item.filename)
        mode = item.external_attr >> 16
        if (name.casefold() in aliases or item.is_dir() or item.flag_bits & 1
                or stat.S_IFMT(mode) not in {0, stat.S_IFREG}
                or item.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}):
            raise StudyArtifactError("bundle contains duplicate, linked or unsupported members")
        aliases.add(name.casefold())
        names[name] = item
        total += item.file_size
        if total > max_bytes + MAX_INDEX_BYTES:
            raise StudyArtifactError("bundle exceeds its extraction size limit")
    if "bundle.json" not in names or names["bundle.json"].file_size > MAX_INDEX_BYTES:
        raise StudyArtifactError("bundle index is missing or too large")
    index = json.loads(archive.read("bundle.json"))
    if (not isinstance(index, dict) or index.get("contract") != CONTRACT
            or index.get("classification") != CLASSIFICATION or not isinstance(index.get("files"), dict)
            or set(index["files"]) != set(names) - {"bundle.json"}):
        raise StudyArtifactError("invalid bundle index or unlisted members")
    result_path = _name(index["result_path"])
    parts = PurePosixPath(result_path).parts
    if len(parts) != 5 or parts[:2] != ("reports", "studies") or parts[-1] != "results.json":
        raise StudyArtifactError("invalid bundled study result path")
    prefixes = (f"data/{parts[2]}/{parts[3]}/", f"reports/studies/{parts[2]}/{parts[3]}/")
    total = 0
    for name, entry in index["files"].items():
        if (not name.startswith(prefixes) or not isinstance(entry, dict)
                or set(entry) != {"size", "sha256"} or type(entry["size"]) is not int
                or entry["size"] != names[name].file_size or entry["size"] < 0
                or not isinstance(entry["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", entry["sha256"])):
            raise StudyArtifactError("invalid bundle inventory entry")
        if any(parent.as_posix().casefold() in aliases for parent in PurePosixPath(name).parents):
            raise StudyArtifactError("bundle file and directory paths collide")
        total += entry["size"]
    if total > max_bytes:
        raise StudyArtifactError("bundle exceeds its extraction size limit")
    return index, names


def import_study_bundle(bundle_path: str | Path, destination: str | Path, *,
                        expected_sha256: str | None = None, max_bytes: int = MAX_BYTES) -> dict:
    """Extract into a new directory and verify without executing bundled code.

    Failed imports retain their new directory for diagnosis, never replace an
    existing destination, and never receive a successful import receipt.
    """
    if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_BYTES:
        raise StudyArtifactError("invalid bundle size limit")
    requested_target, source = Path(destination), Path(bundle_path)
    if requested_target.exists() or requested_target.is_symlink():
        raise FileExistsError("import destination already exists")
    target = requested_target.resolve()
    created = False
    try:
        archive_hash = file_sha256(source)
        if expected_sha256 is not None and expected_sha256 != archive_hash:
            raise StudyArtifactError("bundle differs from its externally bound hash")
        with zipfile.ZipFile(source) as archive:
            index, names = _checked_index(archive, max_bytes=max_bytes)
            target.mkdir(parents=True, exist_ok=False)
            created = True
            for name in sorted(index["files"]):
                path = target.joinpath(*PurePosixPath(name).parts)
                path.parent.mkdir(parents=True, exist_ok=True)
                if not path.resolve().is_relative_to(target):
                    raise StudyArtifactError("bundle member escapes import destination")
                digest, size = hashlib.sha256(), 0
                with archive.open(names[name]) as member, path.open("xb") as output:
                    while chunk := member.read(1024 * 1024):
                        size += len(chunk)
                        if size > index["files"][name]["size"]:
                            raise StudyArtifactError("bundle member exceeds its declared size")
                        digest.update(chunk)
                        output.write(chunk)
                if size != index["files"][name]["size"] or digest.hexdigest() != index["files"][name]["sha256"]:
                    raise StudyArtifactError("bundle member checksum mismatch")
        if file_sha256(source) != archive_hash:
            raise StudyArtifactError("bundle changed during import")
        result_path = target.joinpath(*PurePosixPath(index["result_path"]).parts)
        result = load_study_result(result_path, data_root=target / "data", out_dir=target / "reports",
                                   expected_sha256=index["result_sha256"])
        if (result["batch"]["batch_id"] != index["batch_id"]
                or result["batch"]["manifest_sha256"] != index["manifest_sha256"]
                or _proof(result) != index["proof"]):
            raise StudyArtifactError("bundled proof differs from freshly verified study evidence")
        receipt = {"contract": "study-import-v1", "status": "verified",
                   "bundle_sha256": archive_hash, "classification": CLASSIFICATION,
                   "result_path": str(result_path), "study_verification": result["verification"]}
        publish_json(target / "import.json", receipt)
        return receipt
    except (OSError, ValueError, KeyError, TypeError, AttributeError, zipfile.BadZipFile, RuntimeError) as exc:
        if created:
            publish_json(target / "import-failed.json", {"status": "failed", "error_type": type(exc).__name__})
        if isinstance(exc, StudyArtifactError):
            raise
        raise StudyArtifactError("missing, malformed or unsupported evidence bundle") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export")
    export.add_argument("result", type=Path)
    export.add_argument("destination", type=Path)
    export.add_argument("--data-root", type=Path, default=Path("data/studies"))
    export.add_argument("--out-dir", type=Path, default=Path("reports/out"))
    restore = sub.add_parser("import")
    restore.add_argument("bundle", type=Path)
    restore.add_argument("destination", type=Path)
    for command in (export, restore):
        command.add_argument("--expected-sha256")
    args = parser.parse_args()
    try:
        if args.command == "export":
            result = export_study_bundle(args.result, args.destination, data_root=args.data_root,
                out_dir=args.out_dir, expected_sha256=args.expected_sha256)
        else:
            result = import_study_bundle(args.bundle, args.destination, expected_sha256=args.expected_sha256)
        print(json.dumps(result))
        return 0
    except (StudyArtifactError, FileExistsError) as exc:
        print(json.dumps({"status": "invalid", "reason": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
