"""Prepare a hash-verified local save copy with one deliberately damaged item.

Uses the audited D3Edit source snapshot, verifies complete XOR/protobuf
roundtrips, changes only the selected hero item's Generator.durability, and
restores the field to prove every other protobuf field remains byte-exact.
Never installs or touches the live game directory.
"""
from __future__ import annotations
import argparse, hashlib, json, os, shutil, subprocess, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
LOCAL=(ROOT/"local/saves").resolve()
D3EDIT=ROOT/"local/tools/d3edit-clean"
PROVENANCE=ROOT/"local/tools/d3edit-source-provenance.json"

def sha(path: Path)->str: return hashlib.sha256(path.read_bytes()).hexdigest()
def inside(path: Path)->Path:
    x=path.resolve()
    if x==LOCAL or not x.is_relative_to(LOCAL): raise ValueError("path must be a dedicated folder under local/saves")
    return x

def main()->int:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source",type=Path,required=True)
    ap.add_argument("--destination",type=Path,required=True)
    ap.add_argument("--hero",default="9af81ba794cf5b64.dat")
    ap.add_argument("--item-index",type=int,default=5)
    ap.add_argument("--damage",type=int,default=100)
    args=ap.parse_args()
    source=inside(args.source) if not args.source.is_absolute() else args.source.resolve()
    destination=inside(args.destination)
    if destination.exists(): raise FileExistsError("refusing to overwrite existing fixture")
    if source==destination or not source.is_dir(): raise ValueError("invalid source")
    files=[source/"account.dat",source/"profile.dat",source/"prefs.dat"]
    files += sorted((source/"heroes").glob("*.dat"))
    files += sorted(source.glob("prefs.dat.bak-*"))
    if not all(p.is_file() for p in files): raise RuntimeError("source save set is incomplete")
    before={str(p.relative_to(source)):sha(p) for p in files}
    hero_rel=Path("heroes")/args.hero
    hero_path=source/hero_rel
    if not hero_path.is_file(): raise RuntimeError("selected hero file missing")
    prov=json.loads(PROVENANCE.read_text("utf-8"))
    for rel,want in prov["file_sha256"].items():
        if sha(D3EDIT/rel)!=want: raise RuntimeError("D3Edit source changed: "+rel)
    if subprocess.check_output(["git","-C",str(D3EDIT),"rev-parse","HEAD"],text=True).strip()!=prov["git_commit"]: raise RuntimeError("D3Edit commit mismatch")
    if subprocess.check_output(["git","-C",str(D3EDIT),"status","--porcelain"]): raise RuntimeError("D3Edit checkout dirty")
    os.environ["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"]="python";sys.dont_write_bytecode=True
    sys.path.insert(0,str(D3EDIT))
    import Hero_pb2, D3Edit
    raw=hero_path.read_bytes(); plain=D3Edit.decrypt_save(raw)
    hero=Hero_pb2.SavedDefinition(); consumed=hero.ParseFromString(plain)
    if consumed!=len(plain) or not hero.IsInitialized(): raise RuntimeError("hero protobuf incomplete")
    if D3Edit.encrypt_save(plain)!=raw or hero.SerializeToString()!=plain: raise RuntimeError("hero no-op roundtrip not byte exact")
    items=list(hero.items.items)
    if not 0<=args.item_index<len(items): raise RuntimeError("item index out of range")
    item=items[args.item_index]; gen=item.generator
    if not gen.HasField("durability") or gen.durability==0 or gen.max_durability==0: raise RuntimeError("selected item has no repairable durability")
    if args.damage<=0 or args.damage>=gen.durability: raise ValueError("damage must leave positive durability")
    original=gen.durability; candidate=original-args.damage
    gen.durability=candidate
    encoded=hero.SerializeToString(); encrypted=D3Edit.encrypt_save(encoded)
    check=Hero_pb2.SavedDefinition()
    if check.ParseFromString(encoded)!=len(encoded) or not check.IsInitialized() or check.SerializeToString()!=encoded: raise RuntimeError("candidate hero not parseable/stable")
    if check.items.items[args.item_index].generator.durability!=candidate: raise RuntimeError("candidate durability mismatch")
    gen.durability=original
    if hero.SerializeToString()!=plain: raise RuntimeError("non-target hero fields changed")
    save=destination/"save"; restore=destination/"restore-check"
    for rel in before:
        for base in (save,restore):
            target=base/rel; target.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(source/rel,target)
    (save/hero_rel).write_bytes(encrypted)
    changed=[rel for rel in before if sha(save/rel)!=before[rel]]
    if changed!=[str(hero_rel)]: raise RuntimeError("unexpected changed files: "+str(changed))
    shutil.copyfile(save/hero_rel,restore/hero_rel);shutil.copyfile(hero_path,restore/hero_rel)
    if any(sha(restore/rel)!=want for rel,want in before.items()): raise RuntimeError("restore rehearsal failed")
    manifest={"scope":__doc__,"source":str(source),"destination":str(destination),"hero_file":str(hero_rel),
      "item_index":args.item_index,"item_id":f"{item.id.id_high:016x}:{item.id.id_low:016x}",
      "item_slot":item.item_slot,"item_square":item.square_index,"gbid":gen.gb_handle.gbid,
      "durability_before":original,"durability_after":candidate,"max_durability":gen.max_durability,
      "source_file_sha256":before,"candidate_file_sha256":{rel:sha(save/rel) for rel in before},
      "changed_files":changed,"xor_noop_byte_exact":D3Edit.encrypt_save(plain)==raw,
      "protobuf_noop_byte_exact":True,"candidate_protobuf_stable":True,
      "restore_rehearsal_byte_exact":True,"non_target_fields_byte_exact_when_restored":True,
      "installed":False}
    (destination/"fixture-manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),"utf-8")
    print(json.dumps(manifest,ensure_ascii=False,indent=1));return 0
if __name__=="__main__": raise SystemExit(main())
