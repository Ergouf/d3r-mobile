"""Sample live player position and HP repeatedly inside one Frida attach."""
from __future__ import annotations
import argparse, json, time
from pathlib import Path
import frida
import probe_click_interact
import session_driver
import version

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--pid',type=int,required=True)
    ap.add_argument('--seconds',type=float,default=5.0)
    ap.add_argument('--sample-ms',type=int,default=250)
    ap.add_argument('--context',type=lambda s:int(s,0),default=0x150030e60)
    ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args()
    build=version.assert_installed()
    identity=session_driver._process_identity(args.pid)
    session=frida.get_local_device().attach(args.pid)
    samples=[]; errors=[]
    started=time.monotonic()
    try:
        script=session.create_script(probe_click_interact.build_js(args.context))
        script.load()
        while time.monotonic()-started <= args.seconds:
            t=time.monotonic()-started
            script.exports_sync.arm({'mode':'player_state'})
            data={}
            deadline=time.monotonic()+3.0
            while time.monotonic()<deadline:
                data=script.exports_sync.result()
                if data.get('result'):
                    break
                time.sleep(0.01)
            result=data.get('result')
            if result:
                samples.append({'t':round(t,3),**result})
            else:
                errors.append({'t':round(t,3),'data':data})
            time.sleep(args.sample_ms/1000.0)
    finally:
        session.detach()
    values=[s['hp']['cur'] for s in samples if isinstance(s.get('hp',{}).get('cur'),(int,float))]
    report={'build':build,'identity':identity,'seconds':args.seconds,'sample_ms':args.sample_ms,
            'samples':samples,'errors':errors,
            'min_hp':min(values) if values else None,'max_hp':max(values) if values else None,
            'drop':(max(values)-min(values)) if values else None}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf8')
    print(json.dumps({'samples':len(samples),'errors':len(errors),'min_hp':report['min_hp'],
                      'max_hp':report['max_hp'],'drop':report['drop']},ensure_ascii=False))
if __name__=='__main__': main()
