from pathlib import Path
import subprocess, hashlib, json
source=Path('reference/extract/voice_zh/romfs')
files=sorted(source.glob('*.cpk'))
records=[]
for file in files:
    digest=hashlib.file_digest(file.open('rb'),'sha256').hexdigest()
    remote='/data/local/tmp/d3romfs/AddOnContent/11/'+file.name
    actual=subprocess.check_output(['adb','shell','sha256sum',remote],text=True).split()[0]
    assert actual==digest, file.name
    records.append(dict(name=file.name,bytes=file.stat().st_size,sha256=digest))
    print('verified',file.name,flush=True)
assert len(records)==14
Path('d3-android/build/touch-audio/zh-voice-manifest.json').write_text(json.dumps(records,indent=2))
subprocess.run(['adb','shell','tee','/data/local/tmp/d3romfs/AddOnContent/11/.d3-content-complete'],input='01001b300b9bf00b\n',text=True,check=True)
