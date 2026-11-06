#!/usr/bin/env python3
"""Builds the prone and standing static M1919A4s from the mod's own w_1919Crouch.4ds (the gun with
its front sight), as the game's w_mg42Lie and w_mg42Stand are to w_mg42Crouch.

    python tools/build_stances.py [--game H:/HD2_Unmodified] [--unpacked H:/HD2_Unpacked]

Writes (into the project folder):
    Models/w_1919Lie.4ds, w_1919Lie_f00_00.5DS       prone: the tripod at its lowest
    Models/w_1919Stand.4ds, w_1919Stand_f00_00.5DS   standing: the tripod on long legs
    Tables/anim.sav                                  Sabre Squadron's, with the prone gunner pose
                                                     for projectile type 1 (see below)
    test_lie/, test_stand/                           the Tutorial's Browning with each model
                                                     (the prone one lifted onto the firing counter)

The gun itself (BARREL00_00 and everything under it, the front sight and cameraFPV included) is
not touched, and its shot animation is w_1919Crouch's, byte for byte: the sight picture is the same
as the crouching gun's. A variant changes what holds the gun:

  * SEAT00: the gunner's place and stance ("SEAT68" lies, "SEAT28" stands);
  * HORT00: the pin the gun turns about, from the seat, so that the grips suit the gunner's pose
    (tools/pose_fit.py: both hands within reach at all six of the pose's aim extremes);
  * the limits in BARREL00_00's properties;
  * CAMERA3RD: at the MG 42's distance from the pin, so the third-person view orbits as its does;
  * lafeta: the crouching gun's head (the plate under the gun) on new legs;
  * stupacka01 is left out: nothing in the exe reads it. It is a triangle on the ground that keeps
    the floating parapet guns' bounds down to the origin; these tripods reach the ground.

The gunner's pose comes from a table in anim.sav, index projectile type + 3 x stance (0x00755e0e).
The M1919 (item 34) is type 1: its row has (w97_stand and (w97_crouch but no prone pose, slot 7 is
empty. Tables/anim.sav fills slot 7 with (mg42lie, the only prone gunner the game has. Changing the
item's type instead (as the M2's build does) would need items.sav, which Sasha's New Weapons Mod
ships, and would also change the crouching gun's pose.

Placement. A shipped static gun floats: w_mg42Stand's bipod ends at y = 1.22 and w_1919Crouch's
tripod at 0.41, because the missions stand them on a wall (the walls under the shipped
w_mg42Stands are 1.1-1.3 m high, their rear faces 0-0.5 m ahead of the model's origin, measured
in Sicily1, AFRICA1, Burgundy3 and CZECH6). The variants keep the MG 42's pivot height and place,
and their legs reach the ground, so each model drops into an MG 42's spot and also stands alone;
in a wall the long legs are simply hidden.
"""
import argparse
import copy
import math
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import dta_read                # noqa: E402
import hd2_4ds as h            # noqa: E402
import near_clip_check         # noqa: E402

BASE = 'w_1919Crouch'
SHOT_ANIM = BASE + '_f00_00.5DS'
SEAT_TABLE_SIZE = 12 * 20
PRONE_POSE = '(mg42lie'
PRONE_SLOT = 1 + 3 * 2          # projectile type 1, stance 2 (prone)


class Variant:
    def __init__(self, key, model, seat_flags, pose, seat, hort, limits, cam3rd, legs):
        self.key, self.model, self.pose = key, model, pose
        self.seat_params = 'SEAT%s,name7101' % seat_flags
        self.seat = seat                # SEAT00 in the model
        self.hort = hort                # the pin, from the seat
        self.limits = limits            # up, down, left, right (degrees)
        self.cam3rd = cam3rd            # (from the pin, stored rotation): the MG 42's
        self.legs = legs
        self.pivot = tuple(seat[k] + hort[k] for k in range(3))


class Legs:
    """In lafeta space (the crouching gun's: origin under the pin, the plate above y = 0.027)."""

    def __init__(self, front_foot, rear_foot_z, sleeve=(0.017, 0.013), spreader_t=None):
        self.front_foot = front_foot    # x, z of the front feet
        self.rear_foot_z = rear_foot_z
        self.sleeve = sleeve            # the leg's radius: upper part, telescoped lower part
        self.spreader_t = spreader_t    # where bars join the legs (0 top .. 1 foot); None: no bars


VARIANTS = {
    # The MG 42's seat; its muzzle ends 4 cm further forward than the MG 42's. Elevation: the pivot
    # is 0.55 m behind the muzzle (the MG 42's bipod 0.17 m), so 15 degrees down, as the MG 42
    # has, would put the muzzle 10 cm off the ground; 12 keeps it 13 cm off.
    'lie': Variant('lie', 'w_1919Lie', '68', PRONE_POSE, (0.0, -0.002, -1.205), (0.0, 0.220, 1.400), (8, 12, 45, 45),
                   ((0.0, 1.072, -3.786), (-0.017, 0.0, 0.0, 1.0)),
                   Legs((0.300, 0.270), -0.420)),
    # The pin exactly where the MG 42's is. The pose is the Type 97's, whose hands and head match a
    # gun 0.70 m ahead of the seat, so the gunner stands 0.32 m nearer the pin than the MG 42's.
    'stand': Variant('stand', 'w_1919Stand', '28', '(w97_stand', (0.081, 0.0, -0.640), (0.0, 1.400, 1.192), (15, 5, 30, 30),
                     ((0.0, 0.432, -3.726), (0.0, 0.0, 0.0, 1.0)),
                     Legs((0.400, 0.420), -0.500, sleeve=(0.019, 0.015), spreader_t=0.52)),
}

# ---- mesh helpers -------------------------------------------------------------------------------

# The texture band of the crouching tripod's legs (W_1919FPV.BMP)
BAND_U, BAND_V = (0.931, 0.978), (0.185, 0.404)
FOOT_TOP_Y, FOOT_FLARE_Y, FOOT_EDGE_Y, FOOT_TIP_Y = 0.034, 0.020, 0.015, -0.005     # above the ground
FOOT_R, FOOT_TIP_R = 0.040, 0.006


def sub(a, b): return tuple(a[k] - b[k] for k in range(3))
def add(a, b): return tuple(a[k] + b[k] for k in range(3))
def scale(a, s): return tuple(c * s for c in a)
def dot(a, b): return sum(a[k] * b[k] for k in range(3))
def lerp(a, b, t): return tuple(a[k] + (b[k] - a[k]) * t for k in range(3))


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def norm(a):
    n = math.sqrt(dot(a, a))
    return tuple(c / n for c in a)


class Level:
    def __init__(self):
        self.verts, self.faces = [], []

    def vert(self, p, n, uv):
        self.verts.append((tuple(p), tuple(n), uv))
        return len(self.verts) - 1

    def tri(self, a, b, c):
        """Winding by the shipped meshes: cross(b - a, c - a) along the vertex normals."""
        pa, pb, pc = (self.verts[i][0] for i in (a, b, c))
        if dot(cross(sub(pb, pa), sub(pc, pa)), self.verts[a][1]) < 0:
            b, c = c, b
        self.faces.append((a, b, c))

    def lathe(self, base, axis, profile, seg):
        """A solid of revolution about `axis` from `base`: profile = [(distance along it, radius)]."""
        axis = norm(axis)
        side = norm(cross(axis, (0.0, 0.0, 1.0) if abs(axis[2]) < 0.9 else (1.0, 0.0, 0.0)))
        up = cross(axis, side)
        ring = [(math.cos(2 * math.pi * i / seg), math.sin(2 * math.pi * i / seg)) for i in range(seg)]
        total = profile[-1][0] - profile[0][0]
        for (d0, r0), (d1, r1) in zip(profile, profile[1:]):
            slope = (r0 - r1) / (math.hypot(d1 - d0, r1 - r0) or 1.0)
            flat = math.sqrt(max(0.0, 1.0 - slope * slope))
            v0 = BAND_V[0] + (BAND_V[1] - BAND_V[0]) * (d0 - profile[0][0]) / total
            v1 = BAND_V[0] + (BAND_V[1] - BAND_V[0]) * (d1 - profile[0][0]) / total
            for i in range(seg):
                ca, sa = ring[i]
                cb, sb = ring[(i + 1) % seg]
                ra, rb = add(scale(side, ca), scale(up, sa)), add(scale(side, cb), scale(up, sb))
                na, nb = add(scale(ra, flat), scale(axis, slope)), add(scale(rb, flat), scale(axis, slope))
                ua = BAND_U[0] + (BAND_U[1] - BAND_U[0]) * i / seg
                ub = BAND_U[0] + (BAND_U[1] - BAND_U[0]) * (i + 1) / seg
                a = self.vert(add(add(base, scale(axis, d0)), scale(ra, r0)), na, (ua, v0))
                b = self.vert(add(add(base, scale(axis, d0)), scale(rb, r0)), nb, (ub, v0))
                c = self.vert(add(add(base, scale(axis, d1)), scale(rb, r1)), nb, (ub, v1))
                d = self.vert(add(add(base, scale(axis, d1)), scale(ra, r1)), na, (ua, v1))
                if r0 > 0:
                    self.tri(a, b, c)
                if r1 > 0:
                    self.tri(a, c, d)

    def leg(self, top, foot, sleeve, seg):
        """A tube, thinner past its middle as the real legs telescope."""
        axis = sub(foot, top)
        n = math.sqrt(dot(axis, axis))
        if sleeve[0] == sleeve[1] or seg < 8:
            self.lathe(top, axis, [(0.0, sleeve[0]), (n, sleeve[1])], seg)
        else:
            step = n * 0.55
            self.lathe(top, axis, [(0.0, sleeve[0]), (step, sleeve[0]), (step, sleeve[1]), (n, sleeve[1])], seg)

    def foot(self, x, ground, z, seg):
        """The cup foot of the photos: a dish on a cone standing on its point."""
        base = (x, ground + FOOT_TOP_Y, z)
        self.lathe(base, (0.0, -1.0, 0.0),
                   [(0.0, 0.014), (FOOT_TOP_Y - FOOT_FLARE_Y, FOOT_R), (FOOT_TOP_Y - FOOT_EDGE_Y, FOOT_R),
                    (FOOT_TOP_Y - FOOT_TIP_Y, FOOT_TIP_R)], seg)

    def data(self, distance, material):
        vb = b''.join(struct.pack('<8f', *p, *n, *uv) for p, n, uv in self.verts)
        fb = b''.join(struct.pack('<3H', *f) for f in self.faces)
        assert len(self.verts) < 65536
        return {'distance': distance, 'unk': 0, 'vertices': vb, 'groups': [{'faces': fb, 'material': material}]}


def head_of(level, out):
    """Copies the faces of a shipped lafeta level that are entirely above y = 0: the head (the
    legs and the spreader all reach below it)."""
    vb = level['vertices']
    remap = {}
    for g in level['groups']:
        fb = g['faces']
        for k in range(len(fb) // 6):
            tri = struct.unpack_from('<3H', fb, 6 * k)
            vs = [struct.unpack_from('<8f', vb, 32 * i) for i in tri]
            if min(v[1] for v in vs) < 0.0:
                continue
            ids = []
            for i, v in zip(tri, vs):
                if i not in remap:
                    remap[i] = out.vert(v[:3], v[3:6], v[6:8])
                ids.append(remap[i])
            out.faces.append(tuple(ids))


# The tops of the legs in the shipped tripod: under the plate
FRONT_TOP = (0.030, 0.034, 0.050)
REAR_TOP = (0.001, 0.028, -0.002)


def leg_ends(legs, ground):
    """(name, top, foot point on the dish) of the three legs, in lafeta space."""
    fx, fz = legs.front_foot
    y = ground + FOOT_TOP_Y - 0.004
    return [('rear', REAR_TOP, (REAR_TOP[0], y, legs.rear_foot_z)),
            ('left', (-FRONT_TOP[0], FRONT_TOP[1], FRONT_TOP[2]), (-fx, y, fz)),
            ('right', FRONT_TOP, (fx, y, fz))]


def tripod_levels(base_lods, legs, ground, material):
    """Level 0 as far as the shipped tripod's level 1 reaches, then two plainer ones."""
    levels = []
    for distance, head_level, seg, detail in ((base_lods[1]['distance'], 0, 8, True),
                                              (base_lods[3]['distance'], 2, 4, False),
                                              (0.0, 4, 3, False)):
        lv = Level()
        head_of(base_lods[head_level], lv)
        ends = leg_ends(legs, ground)
        for _name, top, foot in ends:
            lv.leg(top, foot, legs.sleeve if detail else (legs.sleeve[1], legs.sleeve[1]), seg)
            if detail:
                lv.foot(foot[0], ground, foot[2], seg)
        if legs.spreader_t is not None:
            joints = [lerp(top, foot, legs.spreader_t) for _n, top, foot in ends]
            for a, b in ((joints[0], joints[1]), (joints[0], joints[2]), (joints[1], joints[2])):
                lv.lathe(a, sub(b, a), [(0.0, 0.0065), (math.dist(a, b), 0.0065)], 6 if detail else 3)
        levels.append(lv.data(distance, material))
    return levels


# ---- the models -----------------------------------------------------------------------------------

def index(m, name):
    for i, f in enumerate(m['frames']):
        if f['name'] == name:
            return i
    raise KeyError(name)


def remove_frame(m, i):
    frames = m['frames']
    assert not any(f['parent'] == i + 1 or f.get('instance') == i + 1 for f in frames), frames[i]['name']
    del frames[i]
    for f in frames:
        if f['parent'] > i + 1:
            f['parent'] -= 1
        if f.get('instance', 0) > i + 1:
            f['instance'] -= 1


def build_model(base, v):
    m = copy.deepcopy(base)
    f = {x['name']: x for x in m['frames']}
    seat0, hort0 = f['SEAT00']['pos'], f['HORT00']['pos']
    pivot0 = tuple(seat0[k] + hort0[k] for k in range(3))
    laf = f['lafeta']
    offset = tuple(laf['pos'][k] - pivot0[k] for k in range(3))    # lafeta from the pin

    f['SEAT00']['pos'] = v.seat
    f['SEAT00']['params'] = v.seat_params
    f['HORT00']['pos'] = v.hort
    bar = f['BARREL00_00']
    assert bar['params'] == 'matid12,itemid34,up30,down35,left45,right45,hs180,vs180', bar['params']
    bar['params'] = 'matid12,itemid34,up%d,down%d,left%d,right%d,hs180,vs180' % v.limits
    # (BARREL00_00 stays where it is on VERT00: the shot animation's keys hold it there)
    cam_pos, cam_rot = v.cam3rd
    f['CAMERA3RD']['pos'] = tuple(cam_pos[k] - bar['pos'][k] for k in range(3))
    f['CAMERA3RD']['rot'] = cam_rot

    laf['pos'] = tuple(v.pivot[k] + offset[k] for k in range(3))
    material = laf['lods'][0]['groups'][0]['material']
    assert m['materials'][material - 1]['diffuse_map'].upper() == 'W_1919FPV.BMP'
    laf['lods'] = tripod_levels(laf['lods'], v.legs, -laf['pos'][1], material)
    remove_frame(m, index(m, 'stupacka01'))

    names = [x['name'] for x in m['frames']]
    assert len(names) == len(set(names))
    data = h.dumps(m)
    assert h.dumps(h.loads(data)) == data, 'round trip'
    return m, data


def check_sight(m):
    """The blade's top is on the camera's axis, as on the crouching gun."""
    f = {x['name']: x for x in m['frames']}
    s = f['FrontSight00']
    vb = s['lods'][0]['vertices']
    top = max(struct.unpack_from('<f', vb, 32 * k + 4)[0] for k in range(len(vb) // 32)) + s['pos'][1]
    assert s['parent'] - 1 == index(m, 'BARREL00_00') and f['cameraFPV']['parent'] - 1 == index(m, 'BARREL00_00')
    assert abs(top - f['cameraFPV']['pos'][1]) < 1e-4, (top, f['cameraFPV']['pos'][1])


# ---- anim.sav -----------------------------------------------------------------------------------

def patch_anim_sav(game):
    arc = dta_read.Archive(os.path.join(game, 'SabreSquadron.dta'))
    data = bytearray(arc.read('Tables\\anim.sav'))
    start = len(data) - SEAT_TABLE_SIZE
    names = [bytes(data[start + 20 * k:start + 20 * k + 20]).split(b'\0')[0].decode() for k in range(12)]
    assert names[1] == '(w97_stand' and names[4] == '(w97_crouch' and names[6] == PRONE_POSE, names
    assert names[PRONE_SLOT] == '', names
    data[start + 20 * PRONE_SLOT:start + 20 * PRONE_SLOT + 20] = PRONE_POSE.encode().ljust(20, b'\0')
    os.makedirs(os.path.join(ROOT, 'Tables'), exist_ok=True)
    open(os.path.join(ROOT, 'Tables', 'anim.sav'), 'wb').write(data)
    return names


# ---- test kits: the Tutorial's static M1919 becomes each variant --------------------------------

def replace_chunk_string(data, chunk_id, old, new):
    """actors.bin: the chunk `chunk_id` holding the NUL-terminated `old` gets `new`; the sizes of
    the chunks around it (u16 id, u32 size incl. the 6-byte header) are fixed up."""
    target = struct.pack('<HI', chunk_id, 6 + len(old) + 1) + old.encode() + b'\0'
    at = data.find(target)
    assert at >= 0 and data.find(target, at + 1) < 0, 'expected exactly one %r' % old
    delta = len(new) - len(old)
    out = bytearray(data[:at]) + struct.pack('<HI', chunk_id, 6 + len(new) + 1) + new.encode() + b'\0' + \
        data[at + len(target):]

    def walk(off, end):
        while off + 6 <= end:
            cid, size = struct.unpack_from('<HI', data, off)
            if size < 6 or off + size > end:
                return
            if off < at < off + size:
                struct.pack_into('<I', out, off + 2, size + delta)
                walk(off + 6, off + size)
            off += size
    walk(0, len(data))
    return bytes(out)


def move_object(data, name, delta):
    """actors.bin: the object `name` (chunk 0x4010, its name in 0x0010) moves by delta; its position
    chunks are 0x0020 and, without a parent, 0x002C."""
    out = bytearray(data)
    moved = []

    def walk(off, end, depth):
        while off + 6 <= end:
            cid, size = struct.unpack_from('<HI', data, off)
            if size < 6 or off + size > end:
                return
            if cid == 0x4010:
                kids = {}
                p = off + 6
                while p + 6 <= off + size:
                    c2, s2 = struct.unpack_from('<HI', data, p)
                    if s2 < 6:
                        break
                    kids.setdefault(c2, p + 6)
                    p += s2
                if 0x10 in kids and data[kids[0x10]:].split(bytes(1), 1)[0] == name.encode():
                    for c2 in (0x20, 0x2C):
                        if c2 in kids:
                            v = struct.unpack_from('<3f', data, kids[c2])
                            struct.pack_into('<3f', out, kids[c2], *(v[k] + delta[k] for k in range(3)))
                            moved.append(c2)
            elif depth < 3:
                walk(off + 6, off + size, depth + 1)
            off += size
    walk(0, len(data), 0)
    assert moved, name
    return bytes(out)


# The Tutorial's firing counter is 0.43 m high, 0.1 - 0.9 m ahead of the gun's origin: a prone gun
# left in place would be sunk in it, so for the test it lies on the counter (the gunner hovers
# over the floor behind it). The standing gun's legs simply pass through the counter.
TEST_MOVE = {'lie': (0.0, 0.43, 0.30), 'stand': (0.0, 0.0, 0.0)}


def build_test_kits(game):
    actors = dta_read.Archive(os.path.join(game, 'missions.dta')).read('MISSIONS\\TUTORIAL\\actors.bin')
    for other in ('SabreSquadron.dta', 'Patch.dta', 'PatchX01.dta'):
        names = dta_read.Archive(os.path.join(game, other)).names
        assert 'MISSIONS\\TUTORIAL\\actors.bin' not in names, other
    for v in VARIANTS.values():
        dst = os.path.join(ROOT, 'test_' + v.key, 'Missions', 'TUTORIAL')
        os.makedirs(dst, exist_ok=True)
        patched = replace_chunk_string(actors, 0x2012, BASE, v.model)
        if any(TEST_MOVE[v.key]):
            patched = move_object(patched, 'Browning', TEST_MOVE[v.key])
        open(os.path.join(dst, 'actors.bin'), 'wb').write(patched)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--game', default='H:/HD2_Unmodified')
    ap.add_argument('--unpacked', default='H:/HD2_Unpacked')
    a = ap.parse_args()
    models = os.path.join(ROOT, 'Models')
    base = h.load(os.path.join(models, BASE + '.4ds'))
    anim = open(os.path.join(a.unpacked, 'MODELS', SHOT_ANIM), 'rb').read()
    for v in VARIANTS.values():
        m, data = build_model(base, v)
        check_sight(m)
        path = os.path.join(models, v.model + '.4ds')
        open(path, 'wb').write(data)
        open(os.path.join(models, v.model + '_f00_00.5DS'), 'wb').write(anim)
        print('%s: %d bytes, pin at (%.3f %.3f %.3f), limits up/down/left/right %s' % (v.model, len(data), *v.pivot, v.limits))
        worst = 0
        for trav in (0, -v.limits[2], v.limits[3]):
            for elev in (0, v.limits[0], -v.limits[1]):
                worst = max(worst, len(near_clip_check.check(path, pose=(trav, elev))))
        print('  faces cut by the near clip in first person, worst pose: %d' % worst)
    names = patch_anim_sav(a.game)
    print('Tables/anim.sav: slot %d = %s (was empty; table %s)' % (PRONE_SLOT, PRONE_POSE, names))
    build_test_kits(a.game)
    print('test_lie, test_stand: the Tutorial with its Browning swapped')


if __name__ == '__main__':
    main()
