"""Read the current UI navigation group without changing state."""
from __future__ import annotations
import argparse, json
import frida
from version import assert_installed, js_consts
JS = js_consts() + r"""
rpc.exports={read(){
  const u64=a=>gm.add(a).readU64();
  const u32=a=>gm.add(a).readU32();
  const holder=u64(0x9152080), nav=u64(holder), first=u64(nav), group=u64(Number(nav.toString())+0x108);
  const out={holder:holder.toString(),nav:nav.toString(),first:first.toString(),group:group.toString()};
  try{out.count=u64(Number(group.toString())+8).toString();out.selected=u32(Number(group.toString())+0x18);out.player=u32(Number(group.toString())+0x1c);}catch(e){out.error=String(e)}
  try{const data=u64(group);out.data=data.toString();const n=Number(u64(Number(group.toString())+8).toString());out.entries=[];for(let i=0;i<Math.min(n,16);i++){const p=Number(data.toString())+i*0x18;out.entries.push({open:u64(p).toString(),close:u64(p+8).toString(),enabled:u32(p+0x10)});}}catch(e){out.entryError=String(e)}
  return out;
}};
"""
ap=argparse.ArgumentParser();ap.add_argument('--pid',type=int,required=True);ap.add_argument('--out',required=True);a=ap.parse_args();b=assert_installed();s=frida.get_local_device().attach(a.pid)
try:
 j=s.create_script(JS);j.load();d=j.exports_sync.read()
finally:s.detach()
d['build']=b;open(a.out,'w',encoding='utf-8').write(json.dumps(d,indent=2));print(json.dumps(d,indent=2))
