"""Renders previews of a .4ds model with its BMP textures (reads the file the game reads).

    blender -b --factory-startup --python blender_preview.py -- MODEL.4ds MAPS_DIR OUT_PREFIX
            [--views iso;side;front;top;rear;fpv;cam3rd;at:EYE:TARGET:LENS] [--pose TRAV,ELEV] [--lod N]
            [--size W,H] [--samples N] [--hide NAME,...] [--bones FILE.json]

Frames are placed as the engine does (stored quaternion = the conjugate of D3DX's; see
4ds_format.md); game (x, y, z) maps to Blender (x, z, y). --pose turns HORT00 / VERT00 (degrees;
traverse positive to the right, elevation positive up).
"""
import math
import os
import struct
import sys

import bpy

argv = sys.argv[sys.argv.index('--') + 1:]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hd2_4ds as h  # noqa: E402

model_path, maps_dir, out_prefix = argv[0], argv[1], argv[2]


def opt(name, default=None):
    return argv[argv.index(name) + 1] if name in argv else default


views = opt('--views', 'iso;side;front;top;rear;fpv').split(';')
pose = [float(v) for v in opt('--pose', '0,0').split(',')]
lod = int(opt('--lod', '0'))
size = [int(v) for v in opt('--size', '1200,800').split(',')]
samples = int(opt('--samples', '48'))
hide = set(filter(None, opt('--hide', '').split(',')))

m = h.load(model_path)
names = [f['name'] for f in m['frames']]


def quat_matrix(q):
    x, y, z, w = q
    x, y, z = -x, -y, -z
    return [[1 - 2 * (y * y + z * z), 2 * (x * y + z * w), 2 * (x * z - y * w)],
            [2 * (x * y - z * w), 1 - 2 * (x * x + z * z), 2 * (y * z + x * w)],
            [2 * (x * z + y * w), 2 * (y * z - x * w), 1 - 2 * (x * x + y * y)]]


def axis_quat(axis, deg):
    a = math.radians(deg) / 2
    q = [0.0, 0.0, 0.0, math.cos(a)]
    q[axis] = math.sin(a)
    return tuple(q)


# the pose: elevation lifts +z to +y (as the shot animation's recoil key); traverse turns +z to +x
if 'HORT00' in names:
    m['frames'][names.index('HORT00')]['rot'] = axis_quat(1, -pose[0])
if 'VERT00' in names:
    m['frames'][names.index('VERT00')]['rot'] = axis_quat(0, pose[1])

# --anim FILE.5DS --frame K: the animation's pose at frame K (linear positions, slerped rotations)
if '--anim' in argv:
    import hd2_5ds
    anim = hd2_5ds.load(opt('--anim'))
    at = float(opt('--frame', '0'))

    def sample(keys, fn):
        times = [k for k, _ in keys]
        if at <= times[0]:
            return keys[0][1]
        for (t0, v0), (t1, v1) in zip(keys, keys[1:]):
            if t0 <= at <= t1:
                return fn(v0, v1, (at - t0) / (t1 - t0) if t1 > t0 else 1.0)
        return keys[-1][1]

    def slerp(a, b, t):
        d = sum(x * y for x, y in zip(a, b))
        if d < 0:
            b, d = tuple(-x for x in b), -d
        if d > 0.9995:
            q = [x + (y - x) * t for x, y in zip(a, b)]
        else:
            th = math.acos(d)
            s0, s1 = math.sin((1 - t) * th) / math.sin(th), math.sin(t * th) / math.sin(th)
            q = [x * s0 + y * s1 for x, y in zip(a, b)]
        n = math.sqrt(sum(x * x for x in q))
        return tuple(x / n for x in q)

    for o in anim['objects']:
        if o['name'] not in names:
            continue
        f = m['frames'][names.index(o['name'])]
        for kind, (times, off) in hd2_5ds.tracks(anim, o).items():
            stride, fmt = (16, '<4f') if kind == 'rot' else (12, '<3f')
            keys = [(times[i], struct.unpack_from(fmt, anim['raw'], off + stride * i)) for i in range(len(times))]
            if kind == 'rot':
                f['rot'] = sample(keys, slerp)
            elif kind == 'pos':
                f['pos'] = sample(keys, lambda a, b, t: tuple(x + (y - x) * t for x, y in zip(a, b)))


def mat3mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


world = []
for f in m['frames']:
    r = quat_matrix(f['rot'])
    r = [[r[i][j] * f['scale'][i] for j in range(3)] for i in range(3)]
    t = list(f['pos'])
    if f['parent']:
        pr, pt = world[f['parent'] - 1]
        t = [sum(t[k] * pr[k][j] for k in range(3)) + pt[j] for j in range(3)]
        r = mat3mul(r, pr)
    world.append((r, t))


def xform(i, p):
    r, t = world[i]
    return tuple(sum(p[k] * r[k][j] for k in range(3)) + t[j] for j in range(3))


def g2b(p):
    return (p[0], p[2], p[1])


bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene

# materials
mats = []
for k, mt in enumerate(m['materials']):
    mat = bpy.data.materials.new('mat%d' % k)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes['Principled BSDF']
    bsdf.inputs['Roughness'].default_value = 0.62
    tex = mt.get('diffuse_map')
    if tex:
        path = os.path.join(maps_dir, tex)
        img = bpy.data.images.load(path)
        node = nt.nodes.new('ShaderNodeTexImage')
        node.image = img
        nt.links.new(node.outputs['Color'], bsdf.inputs['Base Color'])
    mats.append(mat)

coll = scene.collection
for i, f in enumerate(m['frames']):
    if f['type'] != h.FRAME_VISUAL or f['name'] in hide:
        continue
    # (a frame may share the mesh of an earlier frame)
    src = m['frames'][f['instance'] - 1] if f.get('instance') else f
    if 'lods' not in src:
        continue
    lv = src['lods'][min(lod, len(src['lods']) - 1)]
    vb = lv['vertices']
    n = len(vb) // 32
    pos, uvs = [], []
    for k in range(n):
        x, y, z, nx, ny, nz, u, v = struct.unpack_from('<8f', vb, 32 * k)
        pos.append(g2b(xform(i, (x, y, z))))
        uvs.append((u, 1.0 - v))
    faces, fmat = [], []
    for g in lv['groups']:
        for t in range(len(g['faces']) // 6):
            a, b, c = struct.unpack_from('<3H', g['faces'], 6 * t)
            faces.append((c, b, a))
            fmat.append(g['material'] - 1)
    me = bpy.data.meshes.new(f['name'])
    me.from_pydata(pos, [], faces)
    for mt in mats:
        me.materials.append(mt)
    uvl = me.uv_layers.new(name='uv')
    for poly, mi in zip(me.polygons, fmat):
        poly.material_index = mi
        poly.use_smooth = True
    for loop in me.loops:
        uvl.data[loop.index].uv = uvs[loop.vertex_index]
    me.update()
    ob = bpy.data.objects.new(f['name'], me)
    coll.objects.link(ob)

# --bones FILE: the gunner as capsules (tools/pose_fit.py bones), in orange
if '--bones' in argv:
    import json
    import mathutils
    bm = bpy.data.materials.new('bones')
    bm.use_nodes = True
    bm.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (0.75, 0.42, 0.18, 1.0)
    for pa, pb, rad in json.load(open(opt('--bones'))):
        pa, pb = mathutils.Vector(g2b(pa)), mathutils.Vector(g2b(pb))
        d = pb - pa
        bpy.ops.mesh.primitive_cylinder_add(vertices=12, radius=rad, depth=d.length, location=(pa + pb) / 2)
        cyl = bpy.context.active_object
        cyl.rotation_mode = 'QUATERNION'
        cyl.rotation_quaternion = d.to_track_quat('Z', 'Y')
        cyl.data.materials.append(bm)
        for end in (pa, pb):
            bpy.ops.mesh.primitive_uv_sphere_add(segments=12, ring_count=8, radius=rad, location=end)
            bpy.context.active_object.data.materials.append(bm)

# ground (shadow catcher), lights, world
bpy.ops.mesh.primitive_plane_add(size=12.0, location=(0.0, 0.0, 0.0))
ground = bpy.context.active_object
gm = bpy.data.materials.new('ground')
gm.use_nodes = True
gm.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (0.42, 0.40, 0.35, 1.0)
gm.node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value = 1.0
ground.data.materials.append(gm)
sun = bpy.data.objects.new('sun', bpy.data.lights.new('sun', 'SUN'))
sun.data.energy = 3.2
sun.data.angle = math.radians(3)
sun.rotation_euler = (math.radians(50), math.radians(10), math.radians(-35))
coll.objects.link(sun)
w = bpy.data.worlds.new('w')
w.use_nodes = True
w.node_tree.nodes['Background'].inputs['Color'].default_value = (0.62, 0.68, 0.75, 1.0)
w.node_tree.nodes['Background'].inputs['Strength'].default_value = 0.85
scene.world = w

scene.render.engine = 'CYCLES'
scene.cycles.device = 'CPU'
scene.cycles.samples = samples
scene.cycles.use_denoising = True
scene.render.resolution_x, scene.render.resolution_y = size
scene.view_settings.view_transform = 'Standard'

cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam'))
coll.objects.link(cam)
scene.camera = cam


def look_at(eye, target, lens=50.0, ortho=None):
    import mathutils
    cam.location = eye
    d = mathutils.Vector(target) - mathutils.Vector(eye)
    cam.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    if ortho:
        cam.data.type = 'ORTHO'
        cam.data.ortho_scale = ortho
    else:
        cam.data.type = 'PERSP'
        cam.data.lens = lens
    cam.data.clip_start = 0.01


def frame_world(name):
    i = [n.upper() for n in names].index(name.upper())
    return world[i]


centre = g2b((0.0, 0.62, 0.30))
for v in views:
    if v.startswith('at:'):
        # at:EX,EY,EZ:TX,TY,TZ[:LENS]: from the eye to the target (game coordinates)
        parts = v.split(':')
        eye_at = [tuple(float(c) for c in parts[k].split(',')) for k in (1, 2)]
        look_at(g2b(eye_at[0]), g2b(eye_at[1]), float(parts[3]) if len(parts) > 3 else 42)
    elif v == 'iso':
        look_at(g2b((-2.4, 1.75, 2.6)), centre, 42)
    elif v == 'iso2':
        look_at(g2b((2.6, 1.5, -1.8)), centre, 42)
    elif v == 'side':
        look_at(g2b((-6.0, 0.62, 0.30)), centre, ortho=2.6)
    elif v == 'front':
        look_at(g2b((0.0, 0.62, 6.0)), centre, ortho=2.0)
    elif v == 'top':
        look_at(g2b((0.0, 6.0, 0.30)), centre, ortho=2.6)
        cam.rotation_euler = (0.0, 0.0, 0.0)
    elif v == 'rear':
        look_at(g2b((0.35, 1.25, -1.55)), g2b((0.0, 0.70, 0.30)), 35)
    elif v == 'closeup':
        look_at(g2b((-0.75, 1.05, -0.55)), g2b((0.0, 0.80, -0.05)), 40)
    elif v == 'support':
        look_at(g2b((0.62, 0.95, 0.55)), g2b((0.0, 0.83, 0.62)), 45)
    elif v == 'right':
        look_at(g2b((0.95, 1.05, -0.35)), g2b((0.12, 0.72, -0.08)), 38)
    elif v == 'eject':
        look_at(g2b((1.10, 1.00, 0.55)), g2b((0.20, 0.70, 0.36)), 40)
    elif v == 'mount':
        look_at(g2b((0.55, 0.70, 0.95)), g2b((0.0, 0.66, 0.42)), 45)
    elif v == 'fsight':
        # the front sight from behind and above, as in footage of a real M2 being fired
        r, t = frame_world('BARREL00_00')
        look_at(g2b((t[0] + 0.0, t[1] + 0.32, t[2] - 0.16)), g2b((t[0], t[1] + 0.20, t[2] + 0.05)), 70)
    elif v in ('fpv', 'cam3rd', 'fpvzoom'):
        r, t = frame_world('CAMERA3RD' if v == 'cam3rd' else 'cameraFPV')
        eye = g2b(t)
        fwd = (r[2][0], r[2][1], r[2][2])
        # the game's first person view: 74 degrees vertically (measured on an in-game 4:3
        # screenshot), near clip 0.1 m (scene2.bin chunk 0x3011); fpvzoom: the sights, 10 degrees
        vfov = math.radians(10.0 if v == 'fpvzoom' else 74.0)
        hfov = 2 * math.atan(math.tan(vfov / 2) * size[0] / size[1])
        look_at(eye, g2b(tuple(t[k] + fwd[k] for k in range(3))), 30 if v == 'cam3rd' else 18.0 / math.tan(hfov / 2))
        cam.data.clip_start = 0.1
    scene.render.filepath = '%s_%s.png' % (out_prefix, 'at%d' % views.index(v) if v.startswith('at:') else v)
    bpy.ops.render.render(write_still=True)
    print('rendered', scene.render.filepath)
