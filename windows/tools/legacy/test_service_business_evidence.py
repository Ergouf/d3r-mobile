"""Verify same-process mouse business evidence for blacksmith and mystic.

Historical snapshots retain their own build hashes. This test requires observed
resource/item/durability changes, not only selector or highlight state.
"""
from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
D=ROOT/"out/windows/kbm/session"

def load(name):
    return json.loads((D/name).read_text("utf-8"))
def texts(d): return [t["text"] for t in d["texts"]]
import re
def gold(d):
    values=[int(m.group(1)) for t in texts(d) if (m:=re.match(r"^(\d+) \{icon:gold\}",t))]
    return f"{max(values)} {{icon:gold}}" if values else None
def has(d,value): return any(value in t for t in texts(d))
def count(d,value): return texts(d).count(value)
def item(d,ident):
    return next(i for i in d["heroes"][0]["items"] if i["id"].endswith(ident))

def main():
    checks=[]
    def check(name,condition,detail=None):
        if not condition: raise AssertionError(name+((": "+str(detail)) if detail is not None else ""))
        checks.append(name);print("PASS "+name)
    craft0=load("business-smith-0039-mouse-selected.json");craft1=load("business-smith-0039-mouse-after.json")
    check("mouse-craft-same-build",craft0["build"]==craft1["build"])
    check("mouse-craft-gold-1000",gold(craft0)=="998000 {icon:gold}" and gold(craft1)=="997000 {icon:gold}" and has(craft1,"-1000 {icon:gold}"))
    check("mouse-craft-two-materials-5",count(craft0,"990/5")==2 and count(craft1,"985/5")==2)
    check("mouse-craft-new-item",has(craft1,"完成") and has(craft1,"{c:ff6969ff}魔法匕首{/c}"))
    sal0=load("mouse-salvage-0039-select1.json");sal1=load("mouse-salvage-0039-after.json")
    check("mouse-salvage-same-build",sal0["build"]==sal1["build"])
    check("mouse-salvage-result",has(sal1,"获得物品") and has(sal1,"1") and not has(sal1,"分解为\n{c_white}制作材料{/c}"))
    tr0=load("persist-training-before.json");tr1=load("persist-training-after.json")
    check("mouse-smith-training-same-build",tr0["build"]==tr1["build"])
    check("mouse-smith-training-cost-5000",gold(tr0)=="996000 {icon:gold}" and gold(tr1)=="991000 {icon:gold}" and has(tr1,"-5000 {icon:gold}"))
    trs=load("persist-training-save-after-menu.json")
    check("smith-training-persisted",trs["partitions"][0]["currencies"]["0"]==991000 and trs["partitions"][0]["crafter_levels"][0]==2)
    rep0=load("mouse-repair-0039-before.json");rep1=load("mouse-repair-0039-after.json")
    check("mouse-repair-same-build",rep0["build"]==rep1["build"])
    check("mouse-repair-cost-2",gold(rep0)=="990998 {icon:gold}" and gold(rep1)=="990996 {icon:gold}" and has(rep1,"-2 {icon:gold}"))
    check("mouse-repair-clears-list",has(rep0,"修复费用{c:ffffffff}2 {icon:gold}{/c}") and has(rep1,"没有物品") and has(rep1,"费用{c:ffffffff}0 {icon:gold}{/c}"))
    rs0=load("mouse-repair-0039-save-before.json");rs1=load("mouse-repair-0039-after-save.json")
    a=item(rs0,"784c008f");b=item(rs1,"784c008f")
    check("mouse-repair-persisted",rs0["partitions"][0]["currencies"]["0"]==990998 and rs1["partitions"][0]["currencies"]["0"]==990996 and a["durability"]==577 and b["durability"]==677 and a["max_durability"]==b["max_durability"]==677)
    my0=load("mystic-train-before-mouse.json");my1=load("mystic-train-after8.json")
    check("mouse-mystic-training-same-build",my0["build"]==my1["build"])
    check("mouse-mystic-level-2-to-10",has(my0,"2") and has(my1,"10") and gold(my0)=="990996 {icon:gold}" and gold(my1)=="976996 {icon:gold}" and has(my1,"-4000 {icon:gold}"))
    jw0=load("jeweler-training-before.json");jw1=load("jeweler-training-after.json")
    check("mouse-jeweler-training-same-build",jw0["build"]==jw1["build"])
    check("mouse-jeweler-training-cost-1000",gold(jw0)=="976996 {icon:gold}" and gold(jw1)=="975996 {icon:gold}" and has(jw1,"-1000 {icon:gold}") and has(jw0,"等级{c_white}2{/c}") and has(jw1,"等级{c_white}2{/c}"))
    fsave=load("final-save-0039.json")
    check("jeweler-training-persisted",fsave["partitions"][0]["currencies"]["0"]==975996 and fsave["partitions"][0]["crafter_levels"]==[2,2,10,0])
    ms=load("mystic-level10-save.json")
    check("mystic-level10-persisted",ms["partitions"][0]["currencies"]["0"]==976996 and ms["partitions"][0]["crafter_levels"][2]==10)
    kad=load("kadala-mouse-success.json")
    check("kadala-mouse-cost-75",has(kad,"75 {icon:x1_shard}") and has(kad,"-75 {icon:x1_shard}") and has(kad,"25/500 {icon:x1_shard}"))
    k0=load("kadala-save-before.json");k1=load("kadala-save-after.json")
    check("kadala-purchase-persisted",k0["partitions"][0]["currencies"]["1"]==100 and k1["partitions"][0]["currencies"]["1"]==25 and len(k0["heroes"][0]["items"])==10 and len(k1["heroes"][0]["items"])==11)
    fixture=json.loads((ROOT/"local/saves/kbm-artisan-repair-v2/fixture-manifest.json").read_text("utf-8"))
    check("repair-fixture-byte-safe",fixture["xor_noop_byte_exact"] and fixture["protobuf_noop_byte_exact"] and fixture["candidate_protobuf_stable"] and fixture["restore_rehearsal_byte_exact"] and fixture["non_target_fields_byte_exact_when_restored"] and fixture["changed_files"]==[fixture["hero_file"]])
    report={"scope":__doc__,"checks":checks,"builds":sorted({craft0["build"]["exe_sha256"],tr0["build"]["exe_sha256"],rep0["build"]["exe_sha256"],my0["build"]["exe_sha256"],kad["build"]["exe_sha256"]}),"script_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (D/"service-business-0039-summary.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),"utf-8")
    print(f"{len(checks)} business checks passed")
if __name__=="__main__": main()
