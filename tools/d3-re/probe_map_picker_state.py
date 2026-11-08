"""Read the world-map picker state and projected rows without invoking guest code."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import frida
import session_driver
import version

JS = version.js_consts() + r"""
function q(a){return gm.add(a).readU64().toNumber();}
function u(a){return gm.add(a).readU32();}
function f(a){return gm.add(a).readFloat();}
function hex(v){return '0x'+v.toString(16);}
rpc.exports.read=()=>{
  const state=q(0x9154E30);
  if(!state) return {state:0};
  let data=0,count=0,rows=[],errors=[];
  try{data=q(state+0x28);count=q(state+0x30);}catch(e){errors.push(String(e));}
  if(data && count>0 && count<=256) for(let i=0;i<count;i++){
    const row=data+i*24;
    try{rows.push({index:i,x:f(row),y:f(row+4),id:u(row+8),key:gm.add(row+16).readU64().toString()});}
    catch(e){errors.push(`row ${i}: ${e}`);break;}
  }
  const fields={};
  for(const off of [0x18,0x1c,0x20,0x24,0x28,0x30,0x38,0x40,0x44,0x48,0x4c,0x50,0x54,0x58])
    try{fields[hex(off)]=u(state+off);}catch(e){fields[hex(off)]=String(e);}
  return {state:hex(state),data:hex(data),count,fields,rows,errors};
};
"""

def main() -> None:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--pid',type=int,required=True)
    ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args()
    build=version.assert_installed()
    identity=session_driver._process_identity(args.pid)
    session=frida.attach(args.pid)
    try:
        script=session.create_script(JS)
        script.load()
        result=script.exports_sync.read()
    finally:
        session.detach()
    report={'build':build,'identity':identity,**result}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf8')
    print(json.dumps(report,indent=2,ensure_ascii=False))

if __name__=='__main__':
    main()
