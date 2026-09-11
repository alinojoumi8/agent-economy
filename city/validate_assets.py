"""Validate the modular city catalog and round-trip every GLB through Blender."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_KEYS = {"residence", "office", "workshop", "bank", "civic_hall", "neutral", "agent"}
DETAILS = {"low", "high"}
MAX_ASSET_BYTES = 2_000_000


class AssetValidationError(ValueError):
    """Catalog or asset violates the public asset contract."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fail(condition: bool, message: str) -> None:
    if not condition:
        raise AssetValidationError(message)


def validate_catalog(catalog_path: Path, *, check_files: bool = True) -> dict[str, Any]:
    try:
        catalog = json.loads(catalog_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise AssetValidationError(f"cannot read catalog: {exc}") from exc
    _fail(catalog.get("schema_version") == 1, "unsupported schema_version")
    coordinate = catalog.get("coordinate_system", {})
    _fail(coordinate.get("authoring") == "Z_UP" and coordinate.get("export") == "Y_UP", "invalid axes")
    _fail(coordinate.get("ground_plane") == "y=0", "invalid ground plane")
    generator = catalog.get("generator", {})
    _fail(isinstance(generator.get("blender_version"), str) and generator["blender_version"], "missing Blender version")
    _fail(isinstance(generator.get("source_sha256"), str) and len(generator["source_sha256"]) == 64, "invalid source hash")
    if check_files:
        _fail(generator.get("source") == "city/blender/export_assets.py", "invalid generator source")
        _fail(_sha256(ROOT / generator["source"]) == generator["source_sha256"], "exporter source hash mismatch")
    assets = catalog.get("assets")
    _fail(isinstance(assets, list), "assets must be a list")
    keys = [asset.get("key") for asset in assets if isinstance(asset, dict)]
    _fail(len(keys) == len(assets), "asset entry must be an object")
    _fail(len(keys) == len(set(keys)), "duplicate asset key")
    _fail(set(keys) == REQUIRED_KEYS, "catalog keys do not match required kit")

    total_bytes = 0
    for asset in assets:
        key = asset["key"]
        dimensions = asset.get("dimensions")
        _fail(isinstance(dimensions, list) and len(dimensions) == 3, f"{key}: invalid dimensions")
        _fail(all(isinstance(value, (int, float)) and math.isfinite(value) and value > 0 for value in dimensions),
              f"{key}: dimensions must be positive and finite")
        variants = asset.get("variants")
        _fail(isinstance(variants, dict) and set(variants) == DETAILS, f"{key}: variants must be low/high")
        for detail, variant in variants.items():
            _fail(isinstance(variant, dict), f"{key}/{detail}: variant must be an object")
            filename = f"{key}-{detail}.glb"
            _fail(variant.get("url") == f"/city/{filename}", f"{key}/{detail}: invalid URL")
            size = variant.get("bytes")
            _fail(isinstance(size, int) and 0 < size <= MAX_ASSET_BYTES, f"{key}/{detail}: oversized or invalid byte count")
            _fail(isinstance(variant.get("triangles"), int) and variant["triangles"] > 0,
                  f"{key}/{detail}: invalid triangle count")
            materials = variant.get("materials")
            _fail(isinstance(materials, list) and materials and len(materials) == len(set(materials)),
                  f"{key}/{detail}: invalid material references")
            _fail(variant.get("material_count") == len(materials), f"{key}/{detail}: material count mismatch")
            _fail(isinstance(variant.get("sha256"), str) and len(variant["sha256"]) == 64,
                  f"{key}/{detail}: invalid sha256")
            total_bytes += size
            if check_files:
                asset_path = catalog_path.parent / filename
                _fail(asset_path.is_file(), f"{key}/{detail}: missing {asset_path}")
                _fail(asset_path.stat().st_size == size, f"{key}/{detail}: file size mismatch")
                _fail(_sha256(asset_path) == variant["sha256"], f"{key}/{detail}: sha256 mismatch")
    budget = catalog.get("delivery_budget_bytes")
    _fail(isinstance(budget, int) and 0 < budget <= 10_000_000, "invalid delivery budget")
    _fail(total_bytes <= budget, f"kit exceeds delivery budget: {total_bytes} > {budget}")
    return {"assets": len(assets), "variants": len(assets) * 2, "bytes": total_bytes}


def _run_blender_reimport(catalog_path: Path, blender: str) -> None:
    executable = shutil.which(blender) if not Path(blender).is_absolute() else blender
    _fail(bool(executable), f"Blender executable not found: {blender}")
    command = [str(executable), "--background", "--python", str(Path(__file__).resolve()), "--", "--reimport", str(catalog_path)]
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    if completed.returncode:
        raise AssetValidationError(f"Blender reimport failed\n{completed.stdout}\n{completed.stderr}")
    _fail("ASSET_REIMPORT_COMPLETE" in completed.stdout, "Blender reimport did not complete")
    print(completed.stdout.strip())


def _blender_check(catalog_path: Path) -> None:
    import bpy
    from mathutils import Vector

    catalog = json.loads(catalog_path.read_text())
    _fail(bpy.app.version_string == catalog["generator"]["blender_version"], "Blender version differs from pinned catalog")
    checked = 0
    for asset in catalog["assets"]:
        width, height, depth = asset["dimensions"]
        for detail, variant in asset["variants"].items():
            bpy.ops.wm.read_factory_settings(use_empty=True)
            path = catalog_path.parent / Path(variant["url"]).name
            bpy.ops.import_scene.gltf(filepath=str(path))
            objects = list(bpy.context.scene.objects)
            roots = [obj for obj in objects if obj.get("asset_key") == asset["key"]]
            _fail(len(roots) == 1, f"{asset['key']}/{detail}: missing unique metadata root")
            root = roots[0]
            _fail(root.get("detail_variant") == detail, "detail metadata mismatch")
            _fail(root.parent is None, "asset metadata root must be top-level")
            _fail(root.location.length < 1e-6, "asset pivot must be at world origin")
            meshes = [obj for obj in objects if obj.type == "MESH"]
            _fail(bool(meshes), "asset has no meshes")
            triangles = 0
            material_names: set[str] = set()
            world_points = []
            for obj in objects:
                _fail(all(math.isfinite(value) for row in obj.matrix_world for value in row), "non-finite transform")
                if obj.type != "MESH":
                    continue
                parent = obj.parent
                while parent is not None and parent != root:
                    parent = parent.parent
                _fail(parent == root, "mesh is outside asset metadata hierarchy")
                _fail(len(obj.data.vertices) > 0, "empty mesh")
                _fail(all(slot is not None for slot in obj.data.materials) and len(obj.data.materials) > 0,
                      f"{obj.name}: missing material")
                obj.data.calc_loop_triangles()
                triangles += len(obj.data.loop_triangles)
                material_names.update(slot.name for slot in obj.data.materials)
                world_points.extend(obj.matrix_world @ Vector(corner) for corner in obj.bound_box)
            _fail(triangles == variant["triangles"], f"triangle mismatch: {triangles} != {variant['triangles']}")
            _fail(material_names == set(variant["materials"]), "material references differ after import")
            minima = [min(point[axis] for point in world_points) for axis in range(3)]
            maxima = [max(point[axis] for point in world_points) for axis in range(3)]
            _fail(abs(minima[2]) <= 1e-4, f"grounded pivot violated: min z={minima[2]}")
            tolerance = 0.06  # exported bevels and facade plates may extend at most six centimeters
            _fail(minima[0] >= -width / 2 - tolerance and maxima[0] <= width / 2 + tolerance,
                  f"{asset['key']}/{detail}: width bound exceeded ({minima[0]}, {maxima[0]})")
            _fail(minima[1] >= -depth / 2 - tolerance and maxima[1] <= depth / 2 + tolerance,
                  f"{asset['key']}/{detail}: depth bound exceeded ({minima[1]}, {maxima[1]})")
            _fail(maxima[2] <= height + tolerance, f"{asset['key']}/{detail}: height bound exceeded ({maxima[2]})")
            checked += 1
    print(f"ASSET_REIMPORT_COMPLETE variants={checked} blender={bpy.app.version_string}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("catalog", nargs="?", default=str(ROOT / "city" / "assets" / "catalog.json"))
    parser.add_argument("--blender", default="blender")
    parser.add_argument("--skip-reimport", action="store_true")
    parser.add_argument("--reimport")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else None)
    if args.reimport:
        _blender_check(Path(args.reimport).resolve())
        return
    catalog_path = Path(args.catalog).resolve()
    summary = validate_catalog(catalog_path)
    if not args.skip_reimport:
        _run_blender_reimport(catalog_path, args.blender)
    print(f"ASSET_VALIDATION_COMPLETE assets={summary['assets']} variants={summary['variants']} bytes={summary['bytes']}")


if __name__ == "__main__":
    main()
