"""Look up SDK symbols from reference/d3-symbols/sdk.symbols.json.

Usage:
  py -3 tools/sdk_sym.py 0x4c32c 0x9041c          # nearest symbol <= address
  py -3 tools/sdk_sym.py -f account::             # substring search (name -> address)
  py -3 tools/sdk_sym.py -f Initialize -m 40      # limit matches
"""

import json
import sys
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent.parent / "reference" / "d3-symbols" / "sdk.symbols.json"


def load():
    with PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def main(argv):
    symbols = load()
    pairs = sorted((addr, name) for name, addr in symbols.items() if addr)
    filter_text = None
    limit = 20
    addresses = []
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "-f":
            index += 1
            filter_text = argv[index]
        elif arg == "-m":
            index += 1
            limit = int(argv[index])
        else:
            addresses.append(int(arg, 0))
        index += 1

    if filter_text is not None:
        shown = 0
        needle = filter_text.lower()
        for name, addr in sorted(symbols.items(), key=lambda item: item[1]):
            if needle in name.lower():
                print(f"{addr:#x}  {name}")
                shown += 1
                if shown >= limit:
                    break
        if shown == 0:
            print("(no match)")
        return 0

    for address in addresses:
        best_addr, best_name = None, None
        for addr, name in pairs:
            if addr <= address:
                best_addr, best_name = addr, name
            else:
                break
        if best_name is None:
            print(f"{address:#x}  (before first symbol)")
        else:
            print(f"{address:#x}  {best_name} + {address - best_addr:#x}   [{best_addr:#x}]")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
