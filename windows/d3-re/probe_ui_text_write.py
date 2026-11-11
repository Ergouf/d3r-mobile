"""Write a UTF-8 string into one named UI text object's live buffer (diagnostic)."""
from __future__ import annotations
import argparse, json
from pathlib import Path
import frida
from version import assert_installed, js_consts
MASK64=(1<<64)-1
def fnv1a64(data: bytes)->int:
 h=0xCBF29CE484222325
 for c in data: h=((h^c)*0x100000001B3)&MASK64
 return h
JS=js_consts()+r"""
function q(a){return gm.add(a).readU64().toNumber();}
function u(a){return gm.add(a).readU32();}
rpc.exports.write=function(keyText,newText,nbytes){
 const global=q(0x914f840),world=q(global+0x10),manager=q(world+0xb80),map=q(manager);
 const mask=u(map),buckets=q(map+0x10); let obj=0;
 for(let b=0;b<=mask&&!obj;b++)for(let n=q(buckets+b*8),g=0;n&&g++<2048;n=q(n))
  if(gm.add(n+8).readU64().toString()===keyText){obj=q(n+0x10);break;}
 if(!obj)return {ok:false,error:'object not found'};
 const ptr=q(obj+0x398),cap=u(obj+0x3a0);
 if(!ptr||cap<2||cap>4096)return {ok:false,error:'bad buffer',ptr,cap};
 if(nbytes+1>cap)return {ok:false,error:'too long',cap,len:nbytes};
 gm.add(ptr).writeUtf8String(newText);
 const read=gm.add(ptr).readUtf8String();
 return {ok:true,obj,ptr,cap,len:nbytes,read};
};
"""
ap=argparse.ArgumentParser(); ap.add_argument('--pid',type=int,required=True); ap.add_argument('--path',required=True); ap.add_argument('--text',required=True); ap.add_argument('--out',type=Path); args=ap.parse_args()
build=assert_installed(); key=str(fnv1a64(args.path.lower().encode()))
s=frida.get_local_device().attach(args.pid)
try:
 j=s.create_script(JS); j.load(); r=j.exports_sync.write(key,args.text,len(args.text.encode("utf-8")))
finally: s.detach()
r.update({'path':args.path,'text':args.text,'build':build})
print(json.dumps(r,ensure_ascii=False))
if args.out: args.out.write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
