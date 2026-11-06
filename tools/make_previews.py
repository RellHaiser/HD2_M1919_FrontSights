#!/usr/bin/env python3
"""Renders previews/ of the prone and standing models with Blender (textures from MAPS_DIR). The
orange figure is the gunner: the game's pose file for the trunk and legs, the arms reaching for
the grips (tools/pose_fit.py bones).

    python tools/make_previews.py [--maps H:/HD2_Unpacked/MAPS] [--samples 32]
"""
import argparse
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BLENDER = r'C:\Program Files\Blender Foundation\Blender 4.1\blender.exe'

# (name, eye, target, lens) in game coordinates
VIEWS = {
    'lie': [('iso', (-1.3, 0.75, 1.2), (0.0, 0.15, 0.2), 40),
            ('side', (-2.2, 0.12, 0.25), (0.0, 0.12, 0.25), 40)],
    'stand': [('iso', (-2.3, 1.8, 2.0), (0.08, 0.8, 0.45), 40),
              ('side', (-3.6, 0.75, 0.45), (0.08, 0.75, 0.45), 40)],
}
GUNNER = {
    'lie': ((-2.6, 1.1, 0.6), (0.0, 0.25, -0.3), 40),
    'stand': ((-3.4, 1.2, -0.3), (0.08, 0.85, 0.0), 40),
}


def at(eye, target, lens):
    return 'at:%s:%s:%g' % (','.join(map(str, eye)), ','.join(map(str, target)), lens)


def blender(model, maps, prefix, views, samples, extra=()):
    cmd = [BLENDER, '-b', '--factory-startup', '--python', os.path.join(HERE, 'blender_preview.py'), '--',
           model, maps, prefix, '--views', ';'.join(views), '--size', '960,640', '--samples', str(samples)]
    subprocess.run(cmd + list(extra), check=True, stdout=subprocess.DEVNULL)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--maps', default='H:/HD2_Unpacked/MAPS')
    ap.add_argument('--samples', type=int, default=32)
    a = ap.parse_args()
    sys.path.insert(0, HERE)
    import build_stances as P
    out = os.path.join(ROOT, 'previews')
    work = os.path.join(ROOT, 'build')
    os.makedirs(out, exist_ok=True)
    os.makedirs(work, exist_ok=True)
    for v in P.VARIANTS.values():
        model = os.path.join(ROOT, 'Models', v.model + '.4ds')
        prefix = os.path.join(out, v.model)
        named = VIEWS[v.key]
        blender(model, a.maps, prefix, [at(e, t, l) for _n, e, t, l in named] + ['fpv', 'fpvzoom'], a.samples)
        for k, (name, _e, _t, _l) in enumerate(named):
            shutil.move('%s_at%d.png' % (prefix, k), '%s_%s.png' % (prefix, name))
        bones = os.path.join(work, v.key + '_bones.json')
        subprocess.run([sys.executable, os.path.join(HERE, 'pose_fit.py'), 'bones', v.key, bones], check=True)
        blender(model, a.maps, prefix, [at(*GUNNER[v.key])], a.samples, ['--bones', bones])
        shutil.move(prefix + '_at0.png', prefix + '_gunner.png')
        print(v.model, 'done')


if __name__ == '__main__':
    main()
