"""Original city concept. Run with Blender, never the economic simulation."""
import argparse
import json
import math
from pathlib import Path
import random
import sys

import bpy
from mathutils import Vector

parser = argparse.ArgumentParser()
parser.add_argument('--output', default='city/output')
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])
out = Path(args.output).resolve()
out.mkdir(parents=True, exist_ok=True)
rng = random.Random(42)
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)


def material(name, color, metallic=0):
    m = bpy.data.materials.new(name)
    m.diffuse_color = (*color, 1)
    m.use_nodes = True
    shader = m.node_tree.nodes.get('Principled BSDF')
    shader.inputs['Base Color'].default_value = (*color, 1)
    shader.inputs['Roughness'].default_value = .65
    shader.inputs['Metallic'].default_value = metallic
    return m


paper = material('Porcelain concrete', (.75, .82, .8))
navy = material('Survey navy', (.035, .085, .15))
road = material('Asphalt', (.10, .15, .18))
white = material('Road markings', (.85, .89, .82))
glass = material('Blue glazing', (.10, .35, .46), .35)
roof = material('Roof slate', (.16, .23, .27))
green = material('Park grass', (.31, .47, .28))
leaf = material('Tree canopy', (.15, .32, .23))
wood = material('Timber', (.28, .18, .10))
water = material('River cyan', (.13, .43, .49), .25)
brick = material('Residential terracotta', (.62, .32, .22))
sand = material('Industrial sandstone', (.65, .58, .43))
cobalt = material('Civic cobalt', (.055, .19, .57))


def box(name, loc, size, mat, bevel=0):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    ob = bpy.context.object
    ob.name = name
    ob.dimensions = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    ob.data.materials.append(mat)
    if bevel:
        mod = ob.modifiers.new('Soft manufactured edges', 'BEVEL')
        mod.width = bevel
        mod.segments = 2
        ob.modifiers.new('Weighted corner normals', 'WEIGHTED_NORMAL')
    return ob


def tree(x, y):
    box('Tree trunk', (x, y, .6), (.16, .16, 1), wood)
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=.7, location=(x, y, 1.45))
    ob = bpy.context.object
    ob.name = 'Park canopy'
    ob.scale.z = 1.3
    ob.data.materials.append(leaf)


box('City plinth', (0, 0, -.6), (39, 33, 1.2), navy, .25)
box('Survey ground', (0, 0, .015), (38.8, 32.8, .08), paper)
box('River', (15.4, 0, .09), (6, 32.6, .08), water)
for x in [-12, -4, 4, 12]:
    box('North south avenue', (x, 0, .09), (1.7, 32.5, .06), road)
    for y in range(-15, 16, 2):
        box('Lane dash', (x, y, .13), (.06, .65, .01), white)
for y in [-12, -4, 4, 12]:
    box('East west avenue', (-2.7, y, .10), (31.6, 1.7, .08), road)
    for x in range(-18, 13, 2):
        box('Lane dash', (x, y, .15), (.65, .06, .01), white)
for y in [-4, 12]:
    box('River bridge', (15.3, y, .28), (6.8, 1.8, .3), paper)
    box('Bridge deck', (15.3, y, .45), (6.8, 1.45, .04), road)
    for edge in [-.88, .88]:
        box('Bridge parapet', (15.3, y + edge, .68), (6.8, .12, .4), white)

manifest = []


def building(kind, x, y, width, depth, height, mat):
    key = f'concept:{kind}:{len(manifest):03d}'
    ob = box(key, (x, y, height / 2 + .18), (width, depth, height), mat, .06)
    ob['asset_kind'] = kind
    ob['layout_provenance'] = 'synthetic_concept'
    ob['concept_id'] = key
    manifest.append({'concept_id': key, 'asset_kind': kind, 'position_blender': [x, y, .18],
                     'size': [width, depth, height], 'entity_id': None})
    box('Roof cap', (x, y, height + .23), (width + .12, depth + .12, .17), roof)
    for z in range(1, max(2, int(height))):
        for dx in [-.28 * width, .28 * width]:
            box('Front glazing', (x + dx, y - depth / 2 - .012, z + .2),
                (.25 * width, .035, .43), glass)
        for dy in [-.27 * depth, .27 * depth]:
            box('Side glazing', (x + width / 2 + .012, y + dy, z + .2),
                (.035, .25 * depth, .43), glass)
    return ob


# Neighborhoods: low-rise housing west, businesses central, industry northeast.
for x in [-16, -8]:
    for y in [-8, 0, 8]:
        box('Residential block lawn', (x, y, .12), (5.8, 5.8, .08), green)
        for dx in [-1.5, 1.5]:
            for dy in [-1.5, 1.5]:
                building('residence', x + dx, y + dy, 1.8, 1.9, rng.choice([1.8, 2.5, 3.2]), brick)
        tree(x, y)
for x, y, h in [(0, 0, 8), (1.5, 8, 10), (-1.5, 7, 6), (8, 0, 7), (7, 8, 5)]:
    building('office', x, y, 2.7, 2.7, h, paper)
    box('Mechanical penthouse', (x, y, h + .55), (1.5, 1.3, .6), roof)
building('bank', 8, -8, 4, 3.8, 3.2, paper)
for dx in [-1.4, -.5, .5, 1.4]:
    box('Bank colonnade', (8 + dx, -10.05, 1.7), (.2, .3, 3), paper)
building('civic_hall', 0, -8, 4.8, 3.2, 2.8, paper)
building('civic_tower', 0, -7.8, 1.3, 1.3, 5.2, cobalt)
for x in [-16, -8, 0, 8]:
    building('workshop', x, 14.3, 4.5, 2.3, 2.1, sand)
    box('Ventilation stack', (x + 1.2, 14.3, 3), (.5, .5, 2), roof)
for x in [-16, -8, 0, 8]:
    box('Pocket park', (x, -14.2, .12), (5.7, 2.1, .08), green)
    for dx in [-2, 0, 2]:
        tree(x + dx, -14.1)
for y in range(-14, 16, 3):
    tree(11, y)
for x, y in [(-12, -7), (-4, 2), (4, 6), (6, -4), (-10, 12), (-15, 4)]:
    box('Concept vehicle', (x, y, .4), (.6, 1.05, .45), cobalt, .08)

scene = bpy.context.scene
scene['provenance'] = 'Synthetic city concept; no live Agent Economy data'
scene['layout_version'] = 1
scene.world.color = (.35, .35, .35)
bpy.ops.object.light_add(type='AREA', location=(-10, -12, 26))
bpy.context.object.data.energy = 6500
bpy.context.object.data.shape = 'DISK'
bpy.context.object.data.size = 18
bpy.ops.object.light_add(type='SUN', location=(0, 0, 18))
bpy.context.object.rotation_euler = (.4, -.5, -.3)
bpy.context.object.data.energy = 2
bpy.ops.object.camera_add(location=(45, -58, 47))
cam = bpy.context.object
cam.rotation_euler = (Vector((0, 0, 1.6)) - cam.location).to_track_quat('-Z', 'Y').to_euler()
cam.data.type = 'ORTHO'
cam.data.ortho_scale = 55
scene.camera = cam
scene.render.engine = 'CYCLES'
scene.cycles.samples = 24
scene.cycles.use_denoising = True
scene.render.resolution_x = 1600
scene.render.resolution_y = 1200
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = 'PNG'
scene.render.filepath = str(out / 'city-preview.png')
scene.view_settings.view_transform = 'AgX'
bpy.ops.wm.save_as_mainfile(filepath=str(out / 'agent-economy-city.blend'))
bpy.ops.export_scene.gltf(filepath=str(out / 'agent-economy-city.glb'), export_format='GLB',
                          export_extras=True, export_cameras=False, export_lights=False)
(out / 'manifest.json').write_text(json.dumps({'layout_version': 1, 'seed': 42,
    'provenance': 'synthetic_concept', 'live_data': False, 'buildings': manifest}, indent=2) + '\n')
bpy.ops.render.render(write_still=True)
print(f'CITY_BUILD_COMPLETE buildings={len(manifest)} output={out}')
