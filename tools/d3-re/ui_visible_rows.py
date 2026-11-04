import io
import json
import sys

d = json.load(io.open(sys.argv[1], encoding="utf-8"))
rows = []
for i in d["items"]:
    t = i.get("text")
    if not t or not i["visible"]:
        continue
    rows.append((i["obj"], t.replace("\n", " ")[:30], i["rect2"], i["vt"], i["cbA"], i["parent"]))
lines = [f"{o} {t!r} rect2={[round(v,1) for v in r]} vt={v:#x} cbA={c:#x} parent={p}"
         for o, t, r, v, c, p in rows]
io.open(sys.argv[2], "w", encoding="utf-8").write("\n".join(lines))
print(len(lines), "rows")
