"""Resolve a UI pixel to a button/list row; optionally invoke its native callback.

No global confirm event, input bits, Npad state or window focus is generated.
The list setter and owning control callback run together on the game thread.
This diagnostic is deliberately limited to native list and button classes.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import frida
import probe_guest_call as bridge
from version import assert_installed

EXTENSION = r"""
function q(a){return gp(a).readU64().toNumber();}
function u(a){return gp(a).readU32();}
function childKey(parent,suffix){
 let h=BigInt(gp(parent+0x30).readU64().toString());
 for(let i=0;i<suffix.length;i++)h=((h^BigInt(suffix.charCodeAt(i)))*0x100000001b3n)&0xffffffffffffffffn;
 return h.toString();
}
function uiClick(cpu,req){
  const sp=cpu.add(248).readU64().toNumber(),buf=sp-0x20000;
  const manager=q(q(q(0x914f840)+0x10)+0xb80),map=q(manager),mask=u(map),buckets=q(map+0x10);
  if(mask>262143)throw new Error('invalid UI map');
  const objects=new Map();
  for(let b=0;b<=mask;b++)for(let n=q(buckets+b*8),g=0;n&&g++<1024;n=q(n))
    objects.set(gp(n+8).readU64().toString(),q(n+0x10));
  const focusRef=callGuest(cpu,0x832d180,[],null,null).ret;
  let focusObj=0;
  if(focusRef>0){try{focusObj=objects.get(gp(focusRef).readU64().toString())}catch(e){}}
  const focused=req.root||focusObj;
  if(!focused)return {ok:false,reason:'no active UI focus'};
  const children=new Map();
  for(const [key,obj] of objects){
    let pk; try{pk=gp(obj+0x38).readU64().toString()}catch(e){continue}
    if(!children.has(pk))children.set(pk,[]);
    children.get(pk).push(obj);
  }
  if(req.root){
    const subscriptions=q(manager+0x10),entries=q(subscriptions),n=u(subscriptions+8);
    if(n>1024)throw new Error('invalid subscriptions');
    let active=false;for(let i=0;i<n;i++)if(q(entries+i*8)===focused)active=true;
    if(!active||objects.get(gp(focused+0x30).readU64().toString())!==focused)
      throw new Error('requested root is not an active registered subscriber');
  }
  const parents=o=>objects.get(gp(o+0x38).readU64().toString());
  let ancestor=focused,visible=false;
  for(let k=0;ancestor&&k<64;k++,ancestor=parents(ancestor)){
    if(!(u(ancestor+0x18)&4))break;
    if(gp(ancestor+0x38).readU64().toString()==='18446744073709551615'){visible=true;break;}
  }
  if(!visible)return {ok:false,reason:'focused control has hidden/missing ancestor'};
  let owner=focused,cb=0,ownerTrace=[];
  for(let k=0;owner&&k<64;k++,owner=parents(owner)){
    ownerTrace.push({owner,key:gp(owner+0x30).readU64().toString(),vt:q(owner),table:q(owner+0x118)});
    if(q(q(owner)+0xb0)!==0x83b81f0)continue;
    const table=q(owner+0x118);
    if(table && (cb=q(table+0x20)))break;
  }
  if(!owner)return {ok:false,reason:'no active callback owner',focused,ownerTrace};
  gp(buf).writeS32(req.screen[0]);gp(buf+4).writeS32(req.screen[1]);
  callGuest(cpu,0x8350bf0,[buf,buf+0x20],null,null);
  const point=[gp(buf+0x20).readFloat(),gp(buf+0x24).readFloat()];
  let visited=0;
  function inside(o){
    const r=[0x88,0x8c,0x90,0x94].map(n=>gp(o+n).readFloat());
    if(!r.every(Number.isFinite)||r[2]<=r[0]||r[3]<=r[1])return false;
    const xf=callGuest(cpu,0x83b7ee0,[o],null,null).ret;
    callGuest(cpu,0x8a385b0,[o+0x88,xf,buf+0x40],null,null);
    const clip=[0,4,8,12].map(n=>gp(buf+0x40+n).readFloat());
    return point[0]>=clip[0]&&point[0]<clip[2]&&point[1]>=clip[1]&&point[1]<clip[3];
  }
  function visit(o,depth){
    if(++visited>20000||depth>48)return null;
    const visible=!!(u(o+0x18)&4);
    const vt=q(o);
    if((visible||req.root)&&q(vt+0xe0)===0x838c6c0&&(o===focused||req.root)&&inside(o)){
      const model=q(o+0x258),refs=q(o+0x210),count=u(o+0x218),page=gp(o+0x1e4).readS32();
      if(!model||count>4096)return null;
      const size=callGuest(cpu,q(q(model)+0x10),[model],null,null).ret;
      for(let i=count-1;i>=0;i--){
        const row=objects.get(gp(refs+i*8).readU64().toString());
        const index=page<0?-1:i+page*gp(o+0x2a4).readS32();
        if(!row||index<0||index>=size||!inside(row))continue;
        const allowed=callGuest(cpu,q(q(model)+0x30),[model,o,index],null,null).ret;
        if(allowed)return {kind:'list',obj:o,row,index,owner,callback:cb};
        return {kind:'disabled',obj:o,row,index};
      }
    }
    if(!visible&&!req.root)return null;
    const key=gp(o+0x30).readU64().toString();
    const kids=children.get(key)||[];
    for(let i=kids.length-1;i>=0;i--){const hit=visit(kids[i],depth+1);if(hit)return hit;}
    if(!kids.length){
      const n=u(o+0x68),oldChildren=q(o+0x60);
      if(n>4096)throw new Error('invalid child array');
      for(let i=n-1;i>=0;i--){const hit=visit(q(oldChildren+i*24+8),depth+1);if(hit)return hit;}
    }
    if(q(vt+0x60)===0x8392410&&inside(o)){
      const table=q(o+0x118);let callback=table?q(table):0,callbackOwner=o;
      if(!callback&&cb===0x816aab0){
        const k=gp(o+0x30).readU64().toString();
        if(k===childKey(owner,'.buttonlist.okbutton')){callback=cb;callbackOwner=owner;}
        else if(k===childKey(owner,'.buttonlist.cancel')){
          const cancel=q(q(owner+0x118)+0x28);
          if(cancel===0x816a9c0){callback=cancel;callbackOwner=owner;}
        }
      }
      if(callback){
        if(!(u(o+0x3c8)&1))return {kind:'disabled',obj:o};
        const predicate=q(o+0x488);
        if(predicate&&!callGuest(cpu,predicate,[o+0x30],null,null).ret)return {kind:'disabled',obj:o};
        return {kind:'button',obj:o,owner:callbackOwner,callback};
      }
    }
    return null;
  }
  const hit=visit(owner,0),out={ok:true,screen:req.screen,point,focused,owner,visited,hit};
  if(req.invoke&&hit&&hit.kind!=='disabled'){
    if(hit.kind==='list'){
      out.select=callGuest(cpu,0x838a6e0,[hit.obj,hit.index],null,null);
      if(gp(hit.obj+0x1e0).readS32()!==hit.index)throw new Error('list selection rejected');
    }
    out.invoke=callGuest(cpu,hit.callback,[hit.owner+0x30,0],null,null);
  }
  return out;
}
"""


def build_js() -> str:
    js = bridge.JS.replace("__CONTEXT__", "null").replace("__FRAME__", "0x80fc310")
    js = js.replace("__AFTER__", "true").replace("__EVENT__", "null")
    js = js.replace("function runCall(cpu, req) {", EXTENSION + "\nfunction runCall(cpu, req) {")
    return js.replace("if (req.mode === 'project') {",
                      "if (req.mode === 'ui-click') { result=uiClick(cpu,req); } else if (req.mode === 'project') {")


def main() -> None:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid",type=int,required=True)
    ap.add_argument("--screen",required=True)
    ap.add_argument("--invoke",action="store_true")
    ap.add_argument("--root",type=lambda s:int(s,0),help="explicit currently subscribed list for no-focus ABI diagnosis")
    ap.add_argument("--out",type=Path,required=True)
    args=ap.parse_args()
    build=assert_installed()
    session=frida.attach(args.pid)
    try:
        script=session.create_script(build_js())
        script.load()
        script.exports_sync.arm({"mode":"ui-click","screen":[int(v) for v in args.screen.split(",")],"invoke":args.invoke,"root":args.root})
        deadline=time.monotonic()+12
        data={}
        while time.monotonic()<deadline:
            data=script.exports_sync.result()
            if data.get("result"):break
            time.sleep(.1)
    finally:
        session.detach()
    data.update(build=build,pid=args.pid)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(data,indent=2),"utf-8")
    print(json.dumps(data.get("result"),indent=2))


if __name__=="__main__":
    main()
