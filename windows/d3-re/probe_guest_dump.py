"""Dump a guest-memory window through g_mem (read-only)."""
from __future__ import annotations
import argparse, json
from pathlib import Path
import frida
from version import assert_installed, js_consts

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--pid',type=int,required=True)
    ap.add_argument('--base',type=lambda s:int(s,0),required=True)
    ap.add_argument('--size',type=lambda s:int(s,0),default=0x1000)
    ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args()
    build=assert_installed()
    js=js_consts()+f'''\nrpc.exports.read=()=>{{const b=new Uint8Array(gm.add({args.base}).readByteArray({args.size})); return Array.from(b);}};'''
    session=frida.attach(args.pid)
    try:
        script=session.create_script(js); script.load(); data=script.exports_sync.read()
    finally: session.detach()
    raw=bytes(data)
    words=[int.from_bytes(raw[i:i+4],'little') for i in range(0,len(raw),4)] if len(raw)%4==0 else []
    report={'build':build,'base':args.base,'size':len(raw),'hex':raw.hex(),'u32':words}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report),encoding='utf8')
    print(json.dumps({'base':hex(args.base),'size':len(raw),'nonzero':sum(w!=0 for w in words)},ensure_ascii=False))
if __name__=='__main__': main()
