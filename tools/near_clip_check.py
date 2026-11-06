"""Which faces of a static gun the first-person camera's near plane would cut. A cut face shows
the model's hollow inside (the user saw the ground through the receiver in game): the game
draws the scene with a 0.1 m near clip (scene2.bin chunk 0x3011, C_game +0xC0).

    python tools/near_clip_check.py MODEL.4ds [--near 0.1] [--tanv 0.754] [--aspect 1.3333]
                                    [--pose TRAV,ELEV]

For every triangle (level 0) clips it to the part of the view frustum nearer than the near
plane and reports what is left. tanv: tangent of half the vertical field of view (0.754 =
37 degrees, measured on an in-game 4:3 screenshot of this gun's first-person view).
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hd2_4ds as h          # noqa: E402
import render4ds as r        # noqa: E402

NEAR, TANV, ASPECT = 0.1, 0.754, 4 / 3


def _clip(poly, n, d):
    out = []
    for i in range(len(poly)):
        a, b = poly[i], poly[(i + 1) % len(poly)]
        da = sum(n[k] * a[k] for k in range(3)) + d
        db = sum(n[k] * b[k] for k in range(3)) + d
        if da >= 0:
            out.append(a)
        if (da >= 0) != (db >= 0):
            t = da / (da - db)
            out.append(tuple(a[k] + (b[k] - a[k]) * t for k in range(3)))
    return out


def _area(poly):
    if len(poly) < 3:
        return 0.0
    s = [0.0, 0.0, 0.0]
    for i in range(1, len(poly) - 1):
        u = [poly[i][k] - poly[0][k] for k in range(3)]
        v = [poly[i + 1][k] - poly[0][k] for k in range(3)]
        c = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
        s = [s[k] + c[k] for k in range(3)]
    return 0.5 * math.sqrt(sum(x * x for x in s))


def check(path, near=NEAR, tanv=TANV, aspect=ASPECT, pose=None, camera='camerafpv'):
    """{frame name: (triangles, area m2, nearest depth)} of faces inside the near clip."""
    m = h.load(path)
    if pose:
        r.pose_seat_weapon(m, 0, pose[0], pose[1])
    names = [f['name'] for f in m['frames']]
    tris, wm = r.triangles(m, 0)
    cam = wm[[n.lower() for n in names].index(camera)]
    tanh = tanv * aspect
    planes = [((0, 0, 1), -1e-4), ((0, 0, -1), near), ((0, -1, tanv), 0.0), ((0, 1, tanv), 0.0),
              ((-1, 0, tanh), 0.0), ((1, 0, tanh), 0.0)]

    def to_cam(p):
        d = [p[k] - cam[3][k] for k in range(3)]
        return tuple(sum(d[k] * cam[a][k] for k in range(3)) for a in range(3))
    hits = {}
    for a, b, c, mat, fi in tris:
        poly = [to_cam(a), to_cam(b), to_cam(c)]
        for n, d in planes:
            poly = _clip(poly, n, d)
            if not poly:
                break
        ar = _area(poly)
        if ar > 1e-8:
            e = hits.setdefault(names[fi], [0, 0.0, 9.0])
            e[0] += 1
            e[1] += ar
            e[2] = min(e[2], min(p[2] for p in poly))
    return hits


if __name__ == '__main__':
    args = sys.argv[1:]

    def opt(name, default):
        return float(args[args.index(name) + 1]) if name in args else default
    pose = [float(v) for v in args[args.index('--pose') + 1].split(',')] if '--pose' in args else None
    near, tanv = opt('--near', NEAR), opt('--tanv', TANV)
    hits = check(args[0], near, tanv, opt('--aspect', ASPECT), pose)
    if not hits:
        print('%s: nothing inside the near clip (near %.3f m, half fov %.1f deg)'
              % (os.path.basename(args[0]), near, math.degrees(math.atan(tanv))))
    for k, (n, ar, dz) in hits.items():
        print('%s: %-12s %3d triangles, %.1f cm2 inside the near clip (nearest %.3f m ahead)'
              % (os.path.basename(args[0]), k, n, ar * 1e4, dz))
    sys.exit(1 if hits else 0)
