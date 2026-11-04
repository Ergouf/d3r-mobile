"""Filter the UI registry dump for interesting text and write UTF-8 output."""
import io
import json
import sys

path = sys.argv[1]
out = sys.argv[2] if len(sys.argv) > 2 else None
d = json.load(io.open(path, encoding="utf-8"))
rows = []
for it in d["items"]:
    t = it.get("text")
    if not t or len(t.strip()) < 2:
        continue
    if t.startswith("!!Missing!!") or t.startswith("[PH]") or t.startswith("{icon"):
        continue
    rows.append((int(it["visible"]), it["obj"], it["rect"], t.replace("\n", " | ")))
rows.sort(key=lambda r: (-r[0], r[2][1], r[2][0]))
text = "\n".join(f"vis={v} obj={o} rect={[round(x,1) for x in r]} {t}" for v, o, r, t in rows)
if out:
    io.open(out, "w", encoding="utf-8").write(text)
    print(f"{len(rows)} rows -> {out}")
else:
    print(text)
