"""Verify generated scene and exported GLB by reopening both in Blender."""
import json
import math
from pathlib import Path
import bpy

output = Path(__file__).resolve().parents[1] / 'output'
manifest = json.loads((output / 'manifest.json').read_text())
expected = {item['concept_id'] for item in manifest['buildings']}
assert len(expected) == len(manifest['buildings']) == 36
assert manifest['live_data'] is False
assert all(item['entity_id'] is None for item in manifest['buildings'])


def check_scene():
    buildings = [obj for obj in bpy.context.scene.objects if 'concept_id' in obj]
    assert {obj['concept_id'] for obj in buildings} == expected
    assert len(buildings) == len(expected)
    assert all(obj['layout_provenance'] == 'synthetic_concept' for obj in buildings)
    for obj in bpy.context.scene.objects:
        assert all(math.isfinite(v) for row in obj.matrix_world for v in row)
        if obj.type == 'MESH':
            assert len(obj.data.vertices) > 0
            assert len(obj.data.materials) > 0
    return len(bpy.context.scene.objects)


bpy.ops.wm.open_mainfile(filepath=str(output / 'agent-economy-city.blend'))
blend_count = check_scene()
assert bpy.context.scene.camera is not None
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(output / 'agent-economy-city.glb'))
glb_count = check_scene()
print(json.dumps({'verified_buildings': len(expected), 'blend_objects': blend_count,
                  'glb_objects': glb_count, 'blender': bpy.app.version_string}))
print('CITY_VERIFY_COMPLETE')
