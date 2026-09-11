"""Build the original Agent Economy modular kit and export glTF/GLB assets.

Run from the repository root:
    blender --background --python city/blender/export_assets.py
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import shutil
import sys

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(__file__).resolve()
ASSET_DIR = ROOT / "city" / "assets"
PUBLIC_DIR = ROOT / "dashboard" / "public" / "city"
KEYS = ("residence", "office", "workshop", "bank", "civic_hall", "neutral", "agent")
DIMENSIONS = {
    "residence": (3.2, 3.4, 2.8),
    "office": (4.2, 7.7, 4.2),
    "workshop": (5.4, 3.5, 3.8),
    "bank": (5.2, 4.0, 4.4),
    "civic_hall": (6.4, 5.2, 4.8),
    "neutral": (3.8, 3.6, 3.8),
    "agent": (0.8, 1.8, 0.8),
}


def reset() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def material(name: str, color: tuple[float, float, float], metallic: float = 0.0):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1.0)
    mat.use_nodes = True
    shader = mat.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (*color, 1.0)
    shader.inputs["Roughness"].default_value = 0.72
    shader.inputs["Metallic"].default_value = metallic
    return mat


def palette() -> dict[str, object]:
    return {
        "concrete": material("AE Concrete", (0.66, 0.73, 0.70)),
        "brick": material("AE Terracotta", (0.57, 0.25, 0.16)),
        "glass": material("AE Blue Glass", (0.08, 0.27, 0.38), 0.15),
        "roof": material("AE Slate", (0.11, 0.16, 0.19)),
        "sand": material("AE Sandstone", (0.61, 0.52, 0.35)),
        "cobalt": material("AE Civic Cobalt", (0.04, 0.15, 0.52)),
        "neutral": material("AE Neutral", (0.38, 0.43, 0.42)),
        "accent": material("AE Agent Cyan", (0.04, 0.62, 0.70), 0.1),
        "dark": material("AE Dark", (0.035, 0.06, 0.08)),
    }


def box(root, name, location, size, mat, bevel=0.0):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(mat)
    obj.parent = root
    if bevel:
        modifier = obj.modifiers.new("Manufactured edge", "BEVEL")
        modifier.width = bevel
        modifier.segments = 1
    return obj


def cylinder(root, name, location, radius, depth, mat, vertices=12):
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(mat)
    obj.parent = root
    return obj


def roof(root, mats, width, depth, base, high):
    if high:
        bpy.ops.mesh.primitive_cone_add(vertices=4, radius1=1.0,
                                        radius2=0.0, depth=1.0, location=(0, 0, base + 0.5))
        obj = bpy.context.object
        obj.name = "Roof"
        obj.scale = (width / 2.0, depth / 2.0, 1.0)
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        obj.data.materials.append(mats["roof"])
        obj.parent = root
    else:
        box(root, "Roof", (0, 0, base + 0.12), (width, depth, 0.24), mats["roof"])


def windows(root, mats, width, depth, levels, high):
    columns = 3 if high else 1
    for level in range(levels):
        z = 0.8 + level * 1.25
        for column in range(columns):
            x = (column - (columns - 1) / 2) * width * 0.25
            box(root, f"Window_F_{level}_{column}", (x, -depth / 2 - 0.011, z),
                (width * (0.17 if high else 0.55), 0.035, 0.48), mats["glass"])
        if high:
            for side in (-1, 1):
                box(root, f"Window_S_{level}_{side}", (side * (width / 2 + 0.011), 0, z),
                    (0.035, depth * 0.46, 0.48), mats["glass"])


def build_asset(key: str, detail: str):
    reset()
    mats = palette()
    high = detail == "high"
    width, height, depth = DIMENSIONS[key]
    root = bpy.data.objects.new(f"AE_{key}_{detail}", None)
    bpy.context.scene.collection.objects.link(root)
    root["asset_key"] = key
    root["detail_variant"] = detail
    root["provenance"] = "original_procedural_agent_economy"
    root["coordinate_system"] = "glTF_Y_UP"

    if key == "residence":
        body_h = 2.4
        box(root, "Residence_Body", (0, 0, body_h / 2), (width, depth, body_h), mats["brick"], 0.05)
        roof(root, mats, width, depth, body_h, high)
        box(root, "Door", (0, -depth / 2 - 0.02, 0.65), (0.58, 0.06, 1.3), mats["dark"])
        windows(root, mats, width, depth, 1, high)
    elif key == "office":
        body_h = 7.2
        box(root, "Office_Body", (0, 0, body_h / 2), (width, depth, body_h), mats["concrete"], 0.06)
        windows(root, mats, width, depth, 5 if high else 3, high)
        box(root, "Office_Penthouse", (0, 0, body_h + 0.25), (1.8, 1.7, 0.5), mats["roof"])
    elif key == "workshop":
        body_h = 2.55
        box(root, "Workshop_Body", (0, 0, body_h / 2), (width, depth, body_h), mats["sand"], 0.04)
        roof(root, mats, width, depth, body_h, False)
        box(root, "Loading_Door", (0, -depth / 2 - 0.02, 1.0), (2.0, 0.06, 1.8), mats["dark"])
        cylinder(root, "Vent", (width * 0.3, 0, 2.95), 0.28, 1.0, mats["roof"], 16 if high else 8)
        if high:
            windows(root, mats, width, depth, 1, True)
    elif key == "bank":
        body_h = 3.45
        box(root, "Bank_Body", (0, 0.25, body_h / 2), (width, depth - 0.5, body_h), mats["concrete"], 0.04)
        box(root, "Bank_Pediment", (0, -depth / 2 + 0.32, 3.55), (width, 0.62, 0.35), mats["cobalt"])
        for index in range(4 if high else 2):
            x = (index - (1.5 if high else 0.5)) * (width * (0.22 if high else 0.34))
            cylinder(root, f"Column_{index}", (x, -depth / 2 + 0.15, 1.65), 0.14, 3.0,
                     mats["concrete"], 12 if high else 8)
    elif key == "civic_hall":
        box(root, "Civic_Base", (0, 0, 1.35), (width, depth, 2.7), mats["concrete"], 0.05)
        box(root, "Civic_Tower", (0, 0.35, 3.7), (1.65, 1.7, 2.5), mats["cobalt"], 0.04)
        box(root, "Civic_Entry", (0, -depth / 2 - 0.02, 0.8), (1.45, 0.06, 1.6), mats["dark"])
        if high:
            for side in (-1, 1):
                box(root, f"Civic_Wing_Glass_{side}", (side * 1.75, -depth / 2 - 0.02, 1.35),
                    (1.55, 0.05, 0.75), mats["glass"])
    elif key == "neutral":
        box(root, "Neutral_Body", (0, 0, height / 2), (width, depth, height), mats["neutral"], 0.05)
        box(root, "Neutral_Entry", (0, -depth / 2 - 0.02, 0.7), (0.8, 0.06, 1.4), mats["dark"])
        windows(root, mats, width, depth, 2, high)
    elif key == "agent":
        cylinder(root, "Agent_Body", (0, 0, 0.75), 0.27, 1.05, mats["accent"], 16 if high else 8)
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2 if high else 1, radius=0.34, location=(0, 0, 1.48))
        head = bpy.context.object
        head.name = "Agent_Head"
        head.data.materials.append(mats["concrete"])
        head.parent = root
        box(root, "Agent_Base", (0, 0, 0.06), (width, depth, 0.12), mats["dark"])
    else:
        raise ValueError(key)

    bpy.context.view_layer.update()
    return root


def mesh_metrics() -> tuple[int, list[str]]:
    triangles = 0
    materials: set[str] = set()
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        mesh = evaluated.to_mesh()
        mesh.calc_loop_triangles()
        triangles += len(mesh.loop_triangles)
        evaluated.to_mesh_clear()
        materials.update(mat.name for mat in obj.data.materials if mat is not None)
    return triangles, sorted(materials)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def export_variant(key: str, detail: str) -> dict[str, object]:
    build_asset(key, detail)
    triangles, materials = mesh_metrics()
    filename = f"{key}-{detail}.glb"
    destination = ASSET_DIR / filename
    bpy.ops.export_scene.gltf(
        filepath=str(destination), export_format="GLB", export_extras=True,
        export_cameras=False, export_lights=False, export_apply=True,
    )
    shutil.copy2(destination, PUBLIC_DIR / filename)
    return {
        "detail": detail,
        "url": f"/city/{filename}",
        "sha256": file_sha256(destination),
        "bytes": destination.stat().st_size,
        "triangles": triangles,
        "materials": materials,
        "material_count": len(materials),
    }


def render_contact_sheet() -> None:
    reset()
    for index, key in enumerate(KEYS):
        before = set(bpy.context.scene.objects)
        bpy.ops.import_scene.gltf(filepath=str(ASSET_DIR / f"{key}-high.glb"))
        for obj in set(bpy.context.scene.objects) - before:
            if obj.parent is None:
                obj.location.x += (index - 3) * 8.0
    mats = palette()
    ground = box(None, "Contact_Ground", (0, 0, -0.08), (58, 11, 0.15), mats["concrete"])
    ground.parent = None
    bpy.ops.object.light_add(type="AREA", location=(-8, -10, 18))
    bpy.context.object.data.energy = 1800
    bpy.context.object.data.shape = "DISK"
    bpy.context.object.data.size = 16
    bpy.ops.object.light_add(type="SUN", location=(0, 0, 12))
    bpy.context.object.rotation_euler = (0.5, -0.5, -0.4)
    bpy.context.object.data.energy = 2.0
    bpy.ops.object.camera_add(location=(0, -45, 30))
    camera = bpy.context.object
    camera.rotation_euler = (Vector((0, 0, 2.0)) - camera.location).to_track_quat("-Z", "Y").to_euler()
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = 58
    scene = bpy.context.scene
    scene.camera = camera
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 1800
    scene.render.resolution_y = 620
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(ASSET_DIR / "contact-sheet.png")
    scene.world = bpy.data.worlds.new("Contact World")
    scene.world.color = (0.035, 0.045, 0.055)
    scene.view_settings.view_transform = "AgX"
    bpy.ops.render.render(write_still=True)


def main() -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    entries = []
    for key in KEYS:
        variants = {detail: export_variant(key, detail) for detail in ("low", "high")}
        for variant in variants.values():
            variant.pop("detail")
        width, height, depth = DIMENSIONS[key]
        entries.append({"key": key, "dimensions": [width, height, depth], "variants": variants})
    catalog = {
        "schema_version": 1,
        "coordinate_system": {"authoring": "Z_UP", "export": "Y_UP", "unit": "meter", "ground_plane": "y=0"},
        "generator": {
            "blender_version": bpy.app.version_string,
            "source": "city/blender/export_assets.py",
            "source_sha256": file_sha256(SOURCE),
        },
        "delivery_budget_bytes": 10_000_000,
        "assets": entries,
    }
    encoded = json.dumps(catalog, indent=2, sort_keys=True) + "\n"
    (ASSET_DIR / "catalog.json").write_text(encoded)
    (PUBLIC_DIR / "catalog.json").write_text(encoded)
    render_contact_sheet()
    print(f"ASSET_EXPORT_COMPLETE assets={len(entries)} bytes={sum(v['bytes'] for a in entries for v in a['variants'].values())}")


if __name__ == "__main__":
    main()
