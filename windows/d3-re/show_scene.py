import io
import json
import sys

path = sys.argv[1] if len(sys.argv) > 1 else 'out/windows/kbm/r9/scene.json'
d = json.load(io.open(path, encoding='utf-8'))
r = d['result']
p = r['pos']
print('player', [round(v, 1) for v in p], 'place', r['place'])
for e in r['entities']:
    dx = e['pos'][0] - p[0]
    dy = e['pos'][1] - p[1]
    dz = e['pos'][2] - p[2]
    sx = e['screen'][0] - 640
    sy = e['screen'][1] - 395.5
    print(f"{e['id']} t{e['type']} sno{e['sno']:>7} d={e['distance']:6.1f} "
          f"dW=({dx:7.1f},{dy:7.1f},{dz:6.1f}) dS=({sx:7.1f},{sy:7.1f})")
