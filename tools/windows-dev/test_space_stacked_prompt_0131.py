"""Verify Space closes only the topmost confirmation over the pause menu."""
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[2]
E=ROOT/'out/windows/kbm/session/takeover-font-startup'
BUILD='4F05819440313DEE84D83C9DC9D1A78A1481ECD2D07320ADA0F8B0836C9D0F00'
def load(n):return json.loads((E/n).read_text(encoding='utf-8'))
def texts(d):return [x.get('text') for x in d['ui']['items'] if x.get('text')]
b=load('0131-prompt-stack-before.json');a=load('0131-prompt-stack-after.json')
checks={
 'build': b['build']['exe_sha256']==BUILD==a['build']['exe_sha256'],
 'confirmation-visible': any('你想要退出当前游戏' in (x or '') for x in texts(b)),
 'pause-visible-before': '游戏已暂停' in texts(b),
 'confirmation-closed': not any('你想要退出当前游戏' in (x or '') for x in texts(a)),
 'pause-preserved': '游戏已暂停' in texts(a),
 'space-only-top-layer': a['state']['ui_blocked']==1 and len(a['ui']['items'])<len(b['ui']['items'])
}
fails=[k for k,v in checks.items() if not v]
summary={'checks':len(checks),'failures':fails,'before_items':len(b['ui']['items']),'after_items':len(a['ui']['items']),'build':BUILD}
(E/'0131-stacked-prompt-summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
print(json.dumps(summary))
raise SystemExit(bool(fails))