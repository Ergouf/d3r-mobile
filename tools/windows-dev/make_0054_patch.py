"""Generate patches/windows/0054-native-dialog-labels.patch from the live tree."""
from __future__ import annotations
import hashlib, json, shutil, subprocess, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; SRC=ROOT/'reference/ScarletNX-src'; PATCHES=ROOT/'patches/windows'
NAME='0054-native-dialog-labels.patch'; FILES=['src/nx/runtime/native_world.c']
def run(a,cwd=None): return subprocess.run(a,cwd=cwd,capture_output=True,text=True,encoding="utf-8",errors="replace")
def lf_hash(b): return hashlib.sha256(b.replace(b'\r\n',b'\n')).hexdigest()
def main():
 m=json.loads((PATCHES/'base.json').read_text(encoding='utf-8')); chain=[m['patch']]+[e['patch'] for e in m.get('extra_patches',[])]
 if NAME in chain: chain=chain[:chain.index(NAME)]
 work=Path(tempfile.mkdtemp(prefix='snx-0054-',dir=ROOT/'out')); tree=work/'tree'
 add=run(['git','-C',str(SRC),'worktree','add','--detach',str(tree),m['base_commit']])
 if add.returncode: print(add.stderr); return 2
 try:
  run(['git','-C',str(tree),'config','core.autocrlf','false'])
  for n in chain:
   ap=run(['git','-C',str(tree),'apply','--ignore-whitespace','--whitespace=nowarn',str(PATCHES/n)])
   if ap.returncode: print(n,ap.stderr); return 3
  run(['git','-C',str(tree),'add','-A']); cm=run(['git','-C',str(tree),'-c','user.email=snx@local','-c','user.name=snx','commit','-m','intermediate through 0053'])
  if cm.returncode: print(cm.stderr); return 4
  for rel in FILES: (tree/rel).write_bytes((SRC/rel).read_bytes().replace(b'\r\n',b'\n'))
  run(['git','-C',str(tree),'add','-N']+FILES)
  diff=run(['git','-C',str(tree),'diff','--']+FILES)
  if diff.returncode or not diff.stdout.strip(): print('empty',diff.stdout,diff.stderr); return 5
  out=PATCHES/NAME; out.write_bytes(diff.stdout.replace('\r\n','\n').encode('utf-8'))
  print('patch',out,'sha256',hashlib.sha256(out.read_bytes()).hexdigest())
  for rel in FILES: print(rel,lf_hash((tree/rel).read_bytes()))
 finally:
  assert work.resolve().is_relative_to((ROOT/'out').resolve()) and tree.resolve().parent == work.resolve()
  run(['git','-C',str(SRC),'worktree','remove','--force',str(tree)]); shutil.rmtree(work,ignore_errors=True)
 return 0
if __name__=='__main__': raise SystemExit(main())




