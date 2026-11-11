"""Read the runtime's held-key bitmask for a single injected key phase."""
from __future__ import annotations
import argparse, json
import frida
import version

KEYS = {
    'w': (26,119), 'a':(4,97), 's':(22,115), 'd':(7,100),
    'home':(74,0x4000004A), 'end':(77,0x4000004D), 'insert':(73,0x40000049), 'delete':(76,0x4000004C),
}

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--pid',type=int,required=True)
    ap.add_argument('--key',choices=KEYS,required=True)
    ap.add_argument('--phase',choices=('down','up'),default='down')
    ap.add_argument('--out')
    args=ap.parse_args()
    build=version.assert_installed(); syms=version._symbol_table(version.EXE)
    rva=syms['keys_held']
    session=frida.attach(args.pid)
    source=version.js_consts()+f'''\nconst heldRva=0x{rva:X};\nrpc.exports.read=()=>{{const held=base.add(heldRva).readU64(); return held.toString();}};'''
    try:
        script=session.create_script(source); script.load()
        held=script.exports_sync.read()
    finally: session.detach()
    result={'build':build,'key':args.key,'phase':args.phase,'keys_held':held}
    if args.out: open(args.out,'w',encoding='utf8').write(json.dumps(result,indent=2))
    print(json.dumps(result))

if __name__=='__main__': main()
