"""Click the world at an engine pixel a few times and report the goal log lines."""
import argparse
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOG = Path(r"D:\Games\DiabloIII\01001B300B9BE000\01001B300B9BE000.log")


def tail_native(n=6):
    try:
        text = LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out = [ln for ln in text if "native:" in ln]
    return out[-n:]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--x", type=float, required=True)
    ap.add_argument("--y", type=float, required=True)
    ap.add_argument("--times", type=int, default=1)
    ap.add_argument("--wait", type=float, default=3.0)
    args = ap.parse_args()
    for i in range(args.times):
        subprocess.run([sys.executable, str(HERE / "probe_pointer_click.py"), "--pid", str(args.pid),
                        "--x", str(args.x), "--y", str(args.y)], check=True, stdout=subprocess.DEVNULL)
        time.sleep(args.wait)
        for line in tail_native(4):
            print(line)
        print("---")


if __name__ == "__main__":
    main()
