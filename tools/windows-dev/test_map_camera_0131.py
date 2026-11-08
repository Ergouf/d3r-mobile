"""Verify current-build native map wheel zoom and mouse-map drag."""
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[2]
E=ROOT/'out/windows/kbm/session/takeover-font-startup'
BUILD='4F05819440313DEE84D83C9DC9D1A78A1481ECD2D07320ADA0F8B0836C9D0F00'
def load(n):return json.loads((E/n).read_text(encoding='utf-8'))
def camera(n):
 d=load(n);f=d['objects'][0]['f'];return f[0x1f8//4],f[0x1f8//4+1],f[0x214//4]
base=camera('0131-map-camera-zoom-out.json')
zoom=camera('0131-map-camera-zoom-in.json')
drag=camera('0131-map-camera-dragged.json')
recenter=camera('0131-map-camera-recentered.json')
wheel_in=load('0131-map-wheel-in.json');wheel_out=load('0131-map-wheel-out.json');move=load('0131-map-drag.json');closed=load('0131-map-recenter-close.json')
checks={
 'build': wheel_in['build']['exe_sha256']==BUILD==wheel_out['build']['exe_sha256']==move['build']['exe_sha256'],
 'wheel-in-pushed': wheel_in['actions'][0]['type']=='wheel',
 'wheel-out-pushed': wheel_out['actions'][0]['type']=='wheel',
 'zoom-in': abs(base[2]-1.0)<1e-6 and abs(zoom[2]-0.95)<1e-6,
 'zoom-out': abs(recenter[2]-1.0)<1e-6,
 'drag-pushed': move['actions'][0]['type']=='drag' and all(move['actions'][0]['pushed']),
 'drag-pan': abs(drag[0]-67)<1e-6 and abs(drag[1]-33)<1e-6,
 'recentered': abs(recenter[0])<1e-6 and abs(recenter[1])<1e-6,
 'map-closed': closed['state']['ui_blocked']==0
}
fails=[k for k,v in checks.items() if not v]
summary={'checks':len(checks),'failures':fails,'build':BUILD,'base':base,'zoom_in':zoom,'dragged':drag,'recentered':recenter}
(E/'0131-map-camera-summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False))
raise SystemExit(bool(fails))