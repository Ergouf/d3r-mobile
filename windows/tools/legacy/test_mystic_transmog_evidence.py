"""Verify the mystic transmog business snapshots and known limits.

Business results are save-backed. The 0049 mouse footer mapping is covered by
stubs; the live mouse confirm still selected the current appearance in the
recorded tm2-c2 state, so full mouse-only apply remains open.
"""
from __future__ import annotations
import hashlib, json, os, sys
from pathlib import Path
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/mystic-transmog-0049"
SAVES = ROOT / "local/saves"
sys.path.insert(0, str(ROOT / "local/tools/d3edit-clean"))
import Hero_pb2, Account_pb2, D3Edit  # noqa: E402

BUILD = "58FBA062A65E0F836D21386BE01EFC1E2C429E4B7E1636AA861C87F1718D2C40"
HERO = Path("heroes/9af81ba794cf5b64.dat")


def load(name):
    return json.loads((EVID / name).read_text("utf-8"))


def texts(d):
    return [t["text"] for t in d["texts"]]


def footer(d):
    return " ".join(t for t in texts(d) if t.startswith("{icon:button"))


def check(name, condition, detail=None):
    if not condition:
        raise AssertionError(name + ((": " + str(detail)) if detail is not None else ""))
    print("PASS " + name)


def state(folder):
    base = SAVES / folder
    hero = Hero_pb2.SavedDefinition()
    hero.ParseFromString(D3Edit.decrypt_save((base / HERO).read_bytes()))
    account = Account_pb2.SavedDefinition()
    account.ParseFromString(D3Edit.decrypt_save((base / "account.dat").read_bytes()))
    gold = account.partitions[0].currency_data.currency[0].count
    tm = {i.square_index: i.generator.transmog_gbid for i in hero.items.items}
    return gold, tm, len(hero.items.items)


def main():
    evidence = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(EVID.glob("*.json"))}
    for folder in ("kbm-transmog-before-20261105", "kbm-transmog-after2-20261105",
                   "kbm-transmog-after3-20261105", "kbm-transmog-mouse-before-20261105",
                   "kbm-transmog-mouse-20261105"):
        evidence[folder + "/" + HERO.as_posix()] = hashlib.sha256((SAVES / folder / HERO).read_bytes()).hexdigest()
        evidence[folder + "/account.dat"] = hashlib.sha256((SAVES / folder / "account.dat").read_bytes()).hexdigest()

    listed = load("transmog-list-ui.json")
    applied = load("transmog-applied-ui.json")
    mouse_confirm = load("transmog-mouse-confirm-ui.json")
    check("transmog-ui-build", listed["build"]["exe_sha256"] == BUILD and
          applied["build"]["exe_sha256"] == BUILD and mouse_confirm["build"]["exe_sha256"] == BUILD)
    check("transmog-mouse-click-opens-list", "选择" in footer(listed) and "对比" in footer(listed))
    check("transmog-applied-text", "幻化" in " ".join(texts(applied)) and "875474 {icon:gold}" in texts(applied))
    check("transmog-mouse-confirm-limit", footer(mouse_confirm).strip().endswith("返回"))

    g0, tm0, n0 = state("kbm-transmog-before-20261105")
    g1, tm1, n1 = state("kbm-transmog-after2-20261105")
    g2, tm2, n2 = state("kbm-transmog-after3-20261105")
    g3, tm3, n3 = state("kbm-transmog-mouse-before-20261105")
    g4, tm4, n4 = state("kbm-transmog-mouse-20261105")
    check("transmog-first-save", g0 == 886474 and g1 == 885974 and tm0[31] == -1 and tm1[31] == -1303415302)
    check("transmog-second-save", g2 == 885474 and tm2[51] == -1303415302)
    check("transmog-mouse-save", g3 == 885474 and g4 == 875474 and tm3[51] == -1303415302 and tm4[51] == -101310578)
    check("transmog-items-stable", n0 == n1 == n2 == n3 == n4 == 21)

    summary = {"scope": __doc__, "build": BUILD, "checks": 8, "evidence_sha256": evidence,
               "note": "mouse confirm selected the current appearance in tm2-c2; full mouse-only apply remains open"}
    (EVID / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    print("8 transmog checks passed")


if __name__ == "__main__":
    main()
