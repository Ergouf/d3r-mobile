"""Summarize a scene scan by entity type / SNO / kind with world deltas."""
import collections
import io
import json
import sys

path = sys.argv[1]
d = json.load(io.open(path, encoding="utf-8"))
r = d["result"]
p = r["pos"]
groups = collections.Counter()
for e in r["entities"]:
    if e["type"] == 7:
        continue
    groups[(e["type"], e["sno"], e["kind"])] += 1
print("type sno kind count")
for (t, sno, kind), n in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1])):
    print(f"{t:4} {sno:8} {kind:5} {n}")
print()
for e in r["entities"]:
    if e["type"] != 2:
        continue
    dx = e["pos"][0] - p[0]
    dy = e["pos"][1] - p[1]
    print(f"{e['id']} sno {e['sno']:>7} kind {e['kind']:>3} d {e['distance']:6.1f} "
          f"dW=({dx:7.1f},{dy:7.1f}) screen ({e['screen'][0]:7.1f},{e['screen'][1]:7.1f})")
