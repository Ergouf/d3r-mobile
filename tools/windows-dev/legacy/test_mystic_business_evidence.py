"""Verify the mouse-path mystic enchant business evidence.

Reads the 0048 live UI snapshots plus the two save checkpoints:
  kbm-mystic-enchant3-before-20261105  gold 899315, affix count 2
  kbm-mystic-enchant3-mouse-20261105   gold 886474, affix count 3
"""
from __future__ import annotations
import hashlib, json, os, sys
from pathlib import Path
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/mystic-enchant-0048"
SAVES = ROOT / "local/saves"
sys.path.insert(0, str(ROOT / "local/tools/d3edit-clean"))
import Hero_pb2, Account_pb2, D3Edit  # noqa: E402

BUILD = "92A3DAB0DC121182A731E7EDA38D575E5B3A7E3125D6EC9FCA8EE4BA6EEBD7F2"
HERO = Path("heroes/9af81ba794cf5b64.dat")
SQ = 51


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


def save_state(folder):
    base = SAVES / folder
    hero = Hero_pb2.SavedDefinition()
    hero.ParseFromString(D3Edit.decrypt_save((base / HERO).read_bytes()))
    account = Account_pb2.SavedDefinition()
    account.ParseFromString(D3Edit.decrypt_save((base / "account.dat").read_bytes()))
    gold = account.partitions[0].currency_data.currency[0].count
    counts = {i.square_index: i.generator.enchanted_affix_count for i in hero.items.items}
    item = next(i for i in hero.items.items if i.square_index == SQ)
    return gold, counts, item.generator.enchanted_affix_old, item.generator.enchanted_affix_new, len(hero.items.items)


def main():
    evidence = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(EVID.glob("*.json"))}
    for folder in ("kbm-mystic-enchant3-before-20261105", "kbm-mystic-enchant3-mouse-20261105"):
        evidence[folder + "/" + HERO.as_posix()] = hashlib.sha256((SAVES / folder / HERO).read_bytes()).hexdigest()
        evidence[folder + "/account.dat"] = hashlib.sha256((SAVES / folder / "account.dat").read_bytes()).hexdigest()

    item_ui = load("enchant-item-ui.json")
    select_ui = load("enchant-select-ui.json")
    confirm_ui = load("enchant-confirm-ui.json")
    complete_ui = load("enchant-complete-ui.json")
    accept_ui = load("enchant-accept-ui.json")
    check("enchant-ui-same-final-build",
          all(d["build"]["exe_sha256"] == BUILD for d in (item_ui, select_ui, confirm_ui, complete_ui, accept_ui)))
    check("enchant-item-selected", item_ui["pageSelected"] == 0 and "选择" in footer(item_ui))
    check("enchant-affix-list", "查看可替换的属性" in footer(select_ui) and
          "12841 {icon:gold}" in texts(select_ui) and "899315 {icon:gold}" in texts(select_ui))
    check("enchant-confirm-prompt", footer(confirm_ui).strip().endswith("取消"))
    check("enchant-complete", "完成" in texts(complete_ui) and "接受" in footer(complete_ui))
    check("enchant-cost", "-12841 {icon:gold}" in texts(complete_ui) and "886474 {icon:gold}" in texts(complete_ui))
    check("enchant-accept-returns", "选择" in footer(accept_ui) and "对比" in footer(accept_ui))

    gold0, counts0, old0, new0, n0 = save_state("kbm-mystic-enchant3-before-20261105")
    gold1, counts1, old1, new1, n1 = save_state("kbm-mystic-enchant3-mouse-20261105")
    check("enchant-save-before", gold0 == 899315 and counts0[SQ] == 2 and n0 == 21, (gold0, counts0.get(SQ), n0))
    check("enchant-save-after", gold1 == 886474 and counts1[SQ] == 3 and n1 == 21, (gold1, counts1.get(SQ), n1))
    check("enchant-only-target-affix-count", all(counts0[k] == counts1[k] for k in counts0 if k != SQ), (counts0, counts1))
    check("enchant-affix-id-retained", old0 == old1 and new0 == new1 and old1 == 49371923, (old0, old1, new0, new1))

    summary = {"scope": __doc__, "build": BUILD, "checks": 11, "evidence_sha256": evidence,
               "checkpoints": ["kbm-mystic-enchant3-before-20261105", "kbm-mystic-enchant3-mouse-20261105"]}
    (EVID / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    print("11 mystic enchant checks passed")


if __name__ == "__main__":
    main()
