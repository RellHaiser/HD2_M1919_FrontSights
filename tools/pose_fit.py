"""The gunner poses against a gun's grips: can the hands reach at every aim extreme?

    python tools/pose_fit.py dump "H:/HD2_Unpacked/MODELS/(mg42_stand.4ds"
    python tools/pose_fit.py fit  (reports every variant in build_stances.VARIANTS)
    python tools/pose_fit.py bones lie OUT.json [TRAV ELEV]   (the soldier as capsules, for previews)

A static weapon's gunner (C_HumanWeaponPose::UpdateStaticWeapon, 0x007af780) blends six poses, the
first six keys of the pose's tracks: 0 right-down, 1 right-up, 2 centre-down, 3 centre-up,
4 left-down, 5 left-up. Then the hands go onto the grips (RWS / LWS) with a chain from the spine.
So the arms must span shoulder to grip at the sample's aim: this computes, per sample, the
distance from each shoulder to its grip against the length of the arm.

The skeleton comes from the pose's .4ds (the exporter's scene: skinned visuals, joints).
"""
import math
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hd2_5ds               # noqa: E402

MODELS = r'H:\HD2_Unpacked\MODELS'


# ---- a reader for all of a .4ds's frames (hd2_4ds stops at skinned visuals) ------------------

class R:
    def __init__(self, d):
        self.d, self.p = d, 0

    def u(self, fmt):
        v = struct.unpack_from('<' + fmt, self.d, self.p)
        self.p += struct.calcsize('<' + fmt)
        return v if len(v) > 1 else v[0]

    def s(self):
        n = self.u('B')
        t = self.d[self.p:self.p + n].decode('latin1')
        self.p += n
        return t


def skip_material(r):
    flags = r.u('I')
    r.p += 16 * 4 + 8
    if flags & 0x00080000:
        r.p += 4
        r.s()
    tex = r.s()
    if tex and flags & 0x40000000 and not flags & 0xA1000000:
        r.s()
    if flags & 0x04000000:
        r.p += 2 + 16


def read_mesh(r):
    """Returns the vertex count of each level (None: instanced or no mesh)."""
    if r.u('H'):
        return None
    counts = []
    for _ in range(r.u('B')):
        r.p += 4
        extra = r.u('I')
        n = r.u('H')
        stride = 0
        if extra & 1:
            stride += 4
        if extra & 2:
            stride += 8
        elif extra & 4:
            stride += 16
        elif extra & 8:
            stride += 24
        if n == 0xFFFF:
            raise NotImplementedError('texture level')
        r.p += 32 * n + stride * n
        counts.append(n)
        for _g in range(r.u('B')):
            f = r.u('H')
            r.p += 6 * f + 2
    return counts


def skip_skin(r, levels):
    j = r.u('B')
    if not j:
        return
    r.p += 32 + j + j * (64 + 32)
    for _ in levels:
        w = r.u('I')
        r.p += 2 * w


def skip_morph(r):
    t = r.u('B')
    if not t:
        return
    c, l = r.u('B'), r.u('B')
    for _ in range(l * c):
        v = r.u('H')
        if v:
            r.p += v * t * 24
            if r.u('B'):
                r.p += 2 * v
    r.p += 48


def read_frames(path):
    r = R(open(path, 'rb').read())
    r.p = 14
    for _ in range(r.u('H')):
        skip_material(r)
    frames = []
    for _ in range(r.u('H')):
        typ = r.u('B')
        vt = None
        if typ == 1:
            vt = r.u('B')
            r.u('H')
        parent = r.u('H')
        pos = r.u('3f')
        rot = r.u('4f')
        scale = r.u('3f')
        r.p += 5
        name = r.s()
        r.s()
        bone = None
        if typ == 6:
            r.p += 32
        elif typ == 10:
            bone = r.u('i')
        elif typ == 1:
            if vt in (0, 1):
                read_mesh(r)
            elif vt == 2:
                lv = read_mesh(r)
                if lv is not None:
                    skip_skin(r, lv)
            elif vt == 3:
                lv = read_mesh(r)
                if lv is not None:
                    skip_skin(r, lv)
                    skip_morph(r)
            elif vt == 4:
                read_mesh(r)
                r.p += 5
            elif vt == 5:
                lv = read_mesh(r)
                if lv is not None:
                    skip_morph(r)
            else:
                raise NotImplementedError('visual type %s (%s)' % (vt, name))
        else:
            raise NotImplementedError('frame type %s (%s)' % (typ, name))
        frames.append({'name': name, 'type': typ, 'parent': parent, 'pos': pos, 'rot': rot, 'scale': scale, 'bone': bone})
    return frames


# ---- quaternions (stored as the files: the conjugate of D3DX's) --------------------------------

def quat_matrix(q):
    x, y, z, w = q
    x, y, z = -x, -y, -z
    return [[1 - 2 * (y * y + z * z), 2 * (x * y + z * w), 2 * (x * z - y * w)],
            [2 * (x * y - z * w), 1 - 2 * (x * x + z * z), 2 * (y * z + x * w)],
            [2 * (x * z + y * w), 2 * (y * z - x * w), 1 - 2 * (x * x + y * y)]]


def mat3mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def world(frames, overrides=None):
    """{name: (R, t)}; overrides {name: {'rot', 'pos'}} replace a frame's local values."""
    out, by_index = {}, []
    for f in frames:
        o = (overrides or {}).get(f['name'], {})
        r = quat_matrix(o.get('rot', f['rot']))
        t = list(o.get('pos', f['pos']))
        if f['parent']:
            pr, pt = by_index[f['parent'] - 1]
            t = [sum(t[k] * pr[k][j] for k in range(3)) + pt[j] for j in range(3)]
            r = mat3mul(r, pr)
        by_index.append((r, t))
        out[f['name']] = (r, t)
    return out


def pose_tracks(path):
    a = hd2_5ds.load(path)
    out = {}
    for o in a['objects']:
        tr = hd2_5ds.tracks(a, o)
        e = {}
        for kind, (times, at) in tr.items():
            stride, fmt = (16, '<4f') if kind == 'rot' else (12, '<3f')
            e[kind] = [struct.unpack_from(fmt, a['raw'], at + stride * i) for i in range(len(times))]
        out[o['name']] = e
    return out


def sample_overrides(tracks, k):
    return {n: {kind: keys[k] for kind, keys in e.items() if k < len(keys)} for n, e in tracks.items()}


def lerp_pose(tracks, k0, k1, t):
    """Pose halfway (t) between samples (the level aim between down and up keys)."""
    out = {}
    for n, e in tracks.items():
        o = {}
        for kind, keys in e.items():
            if k1 < len(keys):
                a, b = keys[k0], keys[k1]
                v = [x + (y - x) * t for x, y in zip(a, b)]
                if kind == 'rot':
                    d = math.sqrt(sum(c * c for c in v))
                    v = [c / d for c in v]
                o[kind] = tuple(v)
        out[n] = o
    return out


# ---- a gun's grips at an aim ----------------------------------------------------------------------

HAND_OFFSET = {'R': (0.075, -0.041, -0.003), 'L': (-0.075, -0.041, -0.003)}     # C_HumanWeaponPose
ARM = {'R': ('h', 'i', 'j'), 'L': ('l', 'm', 'n')}
SAMPLES = ['right-down', 'right-up', 'centre-down', 'centre-up', 'left-down', 'left-up']


def aim(v, trav, elev, pos=True, hort=(0, 0, 0), vert=(0, 0, 0)):
    """A gun-space point (or, pos=False, direction) in seat space: elevation about x, then
    traverse about y (positive: the muzzle up, the muzzle to +x), as the seat weapon turns."""
    c, s = math.cos(math.radians(elev)), math.sin(math.radians(elev))
    x, y, z = v
    y, z = y * c + z * s, -y * s + z * c
    if pos:
        x, y, z = x + vert[0], y + vert[1], z + vert[2]
    c, s = math.cos(math.radians(trav)), math.sin(math.radians(trav))
    x, z = x * c + z * s, -x * s + z * c
    if pos:
        x, y, z = x + hort[0], y + hort[1], z + hort[2]
    return (x, y, z)


def sample_aim(k, limits):
    """(traverse, elevation) of pose sample k. limits: up, down, left, right (degrees)."""
    up, down, left, right = limits
    trav = (right, right, 0.0, 0.0, -left, -left)[k]
    elev = (-down, up)[k % 2]
    return trav, elev


def reach_table(skeleton, tracks, gun):
    """Per sample: the distance of each arm's shoulder to the wrist's target, and the arm's length.
    gun: dict hort, vert (pivot: seat space / hort space), rws, lws: (gun-space pos, stored rot),
    limits."""
    rest = world(skeleton)
    lengths = {}
    for side, (sh, el, wr) in ARM.items():
        a = math.dist(rest[sh][1], rest[el][1])
        b = math.dist(rest[el][1], rest[wr][1])
        lengths[side] = a + b
    rows = []
    for k in range(6):
        w = world(skeleton, sample_overrides(tracks, k))
        trav, elev = sample_aim(k, gun['limits'])
        row = {'sample': SAMPLES[k], 'trav': trav, 'elev': elev}
        for side, key in (('R', 'rws'), ('L', 'lws')):
            pos, rot = gun[key]
            g = aim(pos, trav, elev, True, gun['hort'], gun['vert'])
            axes = quat_matrix(rot)
            off = [sum(HAND_OFFSET[side][i] * axes[i][j] for i in range(3)) for j in range(3)]
            off = aim(off, trav, elev, False)
            target = tuple(g[j] - off[j] for j in range(3))     # the wrist (MirrorAbout)
            d = math.dist(w[ARM[side][0]][1], target)
            row[side] = d
            row[side + 'grip'] = g
            row[side + 'shoulder'] = tuple(w[ARM[side][0]][1])
        rows.append(row)
    return rows, lengths


def reference_gun(path):
    """The grips and limits of one of the game's static guns, in the layout reach_table wants."""
    import re
    import hd2_4ds as h
    m = h.load(path)
    f = {x['name'].upper(): x for x in m['frames']}
    add = lambda a, b: tuple(a[i] + b[i] for i in range(3))
    bar = f['BARREL00_00']
    lim = {k: int(re.search(k + r'(\d+)', bar['params']).group(1)) for k in ('up', 'down', 'left', 'right')}
    seat_x = 0.0
    hort = f['HORT00']['pos']
    vert = f['VERT00']['pos']
    del seat_x
    return {'hort': hort, 'vert': vert, 'rws': (add(bar['pos'], f['RWS']['pos']), f['RWS']['rot']),
            'lws': (add(bar['pos'], f['LWS']['pos']), f['LWS']['rot']),
            'limits': (lim['up'], lim['down'], lim['left'], lim['right'])}


def report(title, pose_name, gun):
    skel = read_frames(os.path.join(MODELS, pose_name + '.4ds'))
    tr = pose_tracks(os.path.join(MODELS, pose_name + '.5DS'))
    rows, lengths = reach_table(skel, tr, gun)
    print('%s  pose %s  limits up/down/left/right %s  arm R %.3f L %.3f' % (title, pose_name, gun['limits'], lengths['R'], lengths['L']))
    worst = 0.0
    for r in rows:
        print('  %-12s trav %+5.0f elev %+5.0f   shoulder->wrist R %.3f L %.3f' % (r['sample'], r['trav'], r['elev'], r['R'], r['L']))
        worst = max(worst, r['R'] - lengths['R'], r['L'] - lengths['L'])
    print('  worst overreach %+.3f m' % worst)
    return worst


# ---- the soldier's limbs against the tripod's legs ---------------------------------------------

LIMBS = (('o', 'p', 0.078), ('p', 'q', 0.056), ('q', 'r', 0.045), ('s', 't', 0.078), ('t', 'u', 0.056),
         ('u', 'v', 0.045), ('a', 'b', 0.125), ('b', 'c', 0.120), ('c', 'd', 0.130), ('d', 'e', 0.115))


def seg_dist(p1, q1, p2, q2):
    """Distance between segments p1q1 and p2q2."""
    d1 = [q1[i] - p1[i] for i in range(3)]
    d2 = [q2[i] - p2[i] for i in range(3)]
    r = [p1[i] - p2[i] for i in range(3)]
    a, e, f = sum(c * c for c in d1), sum(c * c for c in d2), sum(d2[i] * r[i] for i in range(3))
    c = sum(d1[i] * r[i] for i in range(3))
    b = sum(d1[i] * d2[i] for i in range(3))
    den = a * e - b * b
    s = max(0.0, min(1.0, (b * f - c * e) / den)) if den > 1e-12 else 0.0
    t = (b * s + f) / e
    if t < 0.0:
        t, s = 0.0, max(0.0, min(1.0, -c / a))
    elif t > 1.0:
        t, s = 1.0, max(0.0, min(1.0, (b - c) / a))
    return math.dist([p1[i] + d1[i] * s for i in range(3)], [p2[i] + d2[i] * t for i in range(3)])


def tripod_legs(v, lafeta_pos):
    """The tripod's legs in seat space: (name, p, q, radius; the cup foot adds its radius at q)."""
    import build_stances as P
    o = tuple(lafeta_pos[i] - v.seat[i] for i in range(3))
    at = lambda q: tuple(q[i] + o[i] for i in range(3))
    return [(n, at(t), at(q), v.legs.sleeve[0]) for n, t, q in P.leg_ends(v.legs, -lafeta_pos[1])]


def body_clearance(v, lafeta_pos):
    skel = read_frames(os.path.join(MODELS, v.pose + '.4ds'))
    tr = pose_tracks(os.path.join(MODELS, v.pose + '.5DS'))
    legs = tripod_legs(v, lafeta_pos)
    worst = (9.0, None)
    for k, sample in [(k, SAMPLES[k]) for k in range(6)]:
        w = world(skel, sample_overrides(tr, k))
        for a, b, r in LIMBS:
            for n, p, q, lr in legs:
                d = seg_dist(w[a][1], w[b][1], p, q) - r - lr
                if d < worst[0]:
                    worst = (d, '%s %s-%s vs %s leg' % (sample, a, b, n))
    return worst


def variant_gun(v, path):
    gun = reference_gun(path)
    assert tuple(round(c, 4) for c in gun['hort']) == tuple(round(c, 4) for c in v.hort)
    return gun


def fit_report(root):
    import hd2_4ds as h
    import build_stances as P
    for v in P.VARIANTS.values():
        path = os.path.join(root, 'Models', v.model + '.4ds')
        report(v.model, v.pose, variant_gun(v, path))
        laf = next(f for f in h.load(path)['frames'] if f['name'] == 'lafeta')
        d, what = body_clearance(v, laf['pos'])
        print('  soldier to tripod legs: %+.3f m (%s)' % (d, what))


# ---- the soldier as capsules, for the previews -----------------------------------------------------

def two_bone(s, w, l1, l2, pole=(0.0, -1.0, 0.0)):
    """The elbow of an arm from shoulder s to wrist w, bent towards `pole` (as the game bends the
    gunner's elbows down)."""
    d = [w[i] - s[i] for i in range(3)]
    n = math.sqrt(sum(c * c for c in d))
    n2 = min(n, l1 + l2 - 1e-4)
    u = [c / n for c in d]
    a = (l1 * l1 - l2 * l2 + n2 * n2) / (2 * n2)
    hh = math.sqrt(max(0.0, l1 * l1 - a * a))
    pd = sum(pole[i] * u[i] for i in range(3))
    perp = [pole[i] - pd * u[i] for i in range(3)]
    pn = math.sqrt(sum(c * c for c in perp)) or 1.0
    return tuple(s[i] + u[i] * a + perp[i] / pn * hh for i in range(3))


BODY = (('a', 'b', 0.125), ('b', 'c1', 0.12), ('c1', 'd1', 0.13), ('d1', 'e', 0.115), ('e', 'f', 0.05),
        ('o', 'p', 0.078), ('p', 'q', 0.056), ('q', 'r', 0.045), ('s', 't', 0.078), ('t', 'u', 0.056),
        ('u', 'v', 0.045), ('g', 'h', 0.045), ('k', 'l', 0.045))
HEAD_R = 0.105


def skeleton_segments(v, path, trav=0.0, elev=0.0):
    """Model-space capsules (a, b, radius) of the gunner at an aim: the pose's samples blended as
    C_HumanWeaponPose::UpdateStaticWeapon does for the trunk (positions and normalized rotations),
    the arms reaching for the grips."""
    skel = read_frames(os.path.join(MODELS, v.pose + '.4ds'))
    tr = pose_tracks(os.path.join(MODELS, v.pose + '.5DS'))
    up, down, left, right = v.limits
    pitch = 0.5 + 0.5 * elev / up if elev >= 0 else 0.5 + 0.5 * elev / down
    if trav <= 0:
        turn, ks = min(1.0, -trav / left), (2, 3, 4, 5)
    else:
        turn, ks = 1.0 - min(1.0, trav / right), (0, 1, 2, 3)

    def blended():
        out = {}
        for n, e in tr.items():
            o = {}
            for kind, keys in e.items():
                if len(keys) < 6:
                    continue
                aa = [keys[ks[0]][i] * (1 - turn) + keys[ks[2]][i] * turn for i in range(len(keys[0]))]
                bb = [keys[ks[1]][i] * (1 - turn) + keys[ks[3]][i] * turn for i in range(len(keys[0]))]
                c = [aa[i] * (1 - pitch) + bb[i] * pitch for i in range(len(aa))]
                if kind == 'rot':
                    d = math.sqrt(sum(x * x for x in c))
                    c = [x / d for x in c]
                o[kind] = tuple(c)
            out[n] = o
        return out
    w = world(skel, blended())
    rest = world(skel)
    segs = []
    pos = {n: w[n][1] for n in w}
    for a, b, r in BODY:
        segs.append((pos[a], pos[b], r))
    segs.append((pos['f'], [pos['f'][0], pos['f'][1] + 0.08, pos['f'][2] + 0.02], HEAD_R))
    gun = reference_gun(path)
    for side, key in (('R', 'rws'), ('L', 'lws')):
        sh, el, wr = ARM[side]
        l1 = math.dist(rest[sh][1], rest[el][1])
        l2 = math.dist(rest[el][1], rest[wr][1])
        g_pos, g_rot = gun[key]
        g = aim(g_pos, trav, elev, True, gun['hort'], gun['vert'])
        axes = quat_matrix(g_rot)
        off = [sum(HAND_OFFSET[side][i] * axes[i][j] for i in range(3)) for j in range(3)]
        off = aim(off, trav, elev, False)
        target = tuple(g[j] - off[j] for j in range(3))
        elbow = two_bone(pos[sh], target, l1, l2)
        segs += [(pos[sh], elbow, 0.05), (elbow, target, 0.042), (target, g, 0.04)]
    return [([p[i] + v.seat[i] for i in range(3)], [q[i] + v.seat[i] for i in range(3)], r) for p, q, r in segs]


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if sys.argv[1] == 'fit':
        fit_report(root)
        return
    if sys.argv[1] == 'bones':
        # bones VARIANT OUT.json [TRAV ELEV]
        import json
        import build_stances as P
        v = P.VARIANTS[sys.argv[2]]
        aim_at = [float(c) for c in sys.argv[4:6]] if len(sys.argv) > 5 else [0.0, 0.0]
        path = os.path.join(root, 'Models', v.model + '.4ds')
        json.dump(skeleton_segments(v, path, *aim_at), open(sys.argv[3], 'w'))
        return
    if sys.argv[1] == 'dump':
        for i, f in enumerate(read_frames(sys.argv[2])):
            print('%3d %-14s type %2d parent %3d pos %s' % (i + 1, f['name'], f['type'], f['parent'],
                                                            tuple(round(c, 3) for c in f['pos'])))
        return


if __name__ == '__main__':
    main()
