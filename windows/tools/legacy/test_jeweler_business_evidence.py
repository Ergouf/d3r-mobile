"""Verify the mouse-path jeweler combine/socket/remove business evidence.

Reads the 0045 live UI snapshots plus four save checkpoints.  The checkpoints
are local game saves produced by normal main-menu exits:
  kbm-jeweler-combine-before-20261105   Square 3 / Flawless 2 / gold 930180
  kbm-jeweler-combine-after-20261105    Square 1 / Flawless 3 / gold 920180
  kbm-jeweler-socketed-20261105         Flawless socketed into a crafted knife
  kbm-jeweler-removed-20261105          same item, gem returned to the bag
"""
from __future__ import annotations
import hashlib, json, os, sys
from pathlib import Path
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/jeweler-0045"
SAVES = ROOT / "local/saves"
sys.path.insert(0, str(ROOT / "local/tools/d3edit-clean"))
import Hero_pb2, Account_pb2, D3Edit  # noqa: E402

BUILD = "F4001FD8364E2287890F3C853493BAF26EE737AD2D3E646D15A80F8180E5F595"
SQUARE = 1019190636
FLAWLESS = 1019190637
KNIFE = -635269580
HERO = Path("heroes/9af81ba794cf5b64.dat")


def load(name):
    return json.loads((EVID / name).read_text("utf-8"))


def texts(d):
    return [t["text"] for t in d["texts"]]


def footer(d):
    return " ".join(t for t in texts(d) if t.startswith("{icon:button"))


def value(d, wanted):
    return any(t.strip().split(" ")[0] == wanted for t in texts(d))


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
    gems = {i.generator.gb_handle.gbid: i.generator.stack_size
            for i in hero.items.items if i.generator.gb_handle.gbid in (SQUARE, FLAWLESS)}
    socketed = [(i.square_index, i.generator.gb_handle.gbid, i.used_socket_count,
                 [(c.generator.gb_handle.gbid, c.generator.stack_size) for c in i.generator.contents])
                for i in hero.items.items if i.used_socket_count or i.generator.contents]
    return gold, gems, socketed


def main():
    evidence = {}
    for path in sorted(EVID.glob("*.json")):
        evidence[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    for folder in ("kbm-jeweler-combine-before-20261105", "kbm-jeweler-combine-after-20261105",
                   "kbm-jeweler-socketed-20261105", "kbm-jeweler-removed-20261105"):
        evidence[folder + "/" + HERO.as_posix()] = hashlib.sha256((SAVES / folder / HERO).read_bytes()).hexdigest()
        evidence[folder + "/account.dat"] = hashlib.sha256((SAVES / folder / "account.dat").read_bytes()).hexdigest()

    before = load("combine-before-ui.json")
    confirm = load("combine-confirm-ui.json")
    after = load("combine-after-ui.json")
    check("combine-ui-same-final-build",
          all(d["build"]["exe_sha256"] == BUILD for d in (before, confirm, after)))
    check("combine-before-is-flawless-square",
          before["pageSelected"] == 0 and before["groupIndex"] == 6 and
          "3/2" in texts(before) and "无瑕的方形红宝石" in " ".join(texts(before)))
    check("combine-before-select-action", "选择" in footer(before))
    check("combine-confirm-action", "合成" in footer(confirm))
    check("combine-after-complete", "完成" in texts(after))
    check("combine-after-cost", "-10000 {icon:gold}" in texts(after))
    check("combine-after-gold", "920180 {icon:gold}" in texts(after))

    gold, gems, socketed = save_state("kbm-jeweler-combine-before-20261105")
    check("combine-save-before", gold == 930180 and gems == {SQUARE: 3, FLAWLESS: 2} and not socketed,
          (gold, gems, socketed))
    gold, gems, socketed = save_state("kbm-jeweler-combine-after-20261105")
    check("combine-save-after", gold == 920180 and gems == {SQUARE: 1, FLAWLESS: 3} and not socketed,
          (gold, gems, socketed))

    category = load("socket-category-ui.json")
    item = load("socket-item-ui.json")
    socket_after = load("socket-after-ui.json")
    check("socket-ui-same-final-build",
          all(d["build"]["exe_sha256"] == BUILD for d in (category, item, socket_after)))
    check("socket-gem-list", category["pageSelected"] == 1 and
          "无瑕的方形红宝石 (2)" in " ".join(texts(category)) and "镶孔" in footer(category))
    check("socket-item-present", "狂热刀刺" in " ".join(texts(item)) and value(item, "51.8") and
          "镶孔" in footer(item))
    check("socket-after-continue", "继续" in footer(socket_after) and
          any("无瑕的方形红宝石" in t for t in texts(socket_after)) and
          not any("无瑕的方形红宝石 (2)" in t for t in texts(socket_after)))

    gold, gems, socketed = save_state("kbm-jeweler-socketed-20261105")
    check("socket-save", gold == 930180 and gems == {SQUARE: 1, FLAWLESS: 1} and
          socketed == [(32, KNIFE, 1, [(FLAWLESS, 1)])], (gold, gems, socketed))

    remove_page = load("remove-page-ui.json")
    remove_after = load("remove-after-ui.json")
    remove_after2 = load("remove-after-ui2.json")
    check("remove-ui-same-final-build",
          all(d["build"]["exe_sha256"] == BUILD for d in (remove_page, remove_after, remove_after2)))
    check("remove-page-socketed-item", remove_page["pageSelected"] == 2 and
          "狂热刀刺" in " ".join(texts(remove_page)) and value(remove_page, "135.8") and
          "移除" in footer(remove_page))
    check("remove-after-removed", "已移除" in " ".join(texts(remove_after)) and "继续" in footer(remove_after))
    check("remove-after-repeat", "已移除" in " ".join(texts(remove_after2)))

    gold, gems, socketed = save_state("kbm-jeweler-removed-20261105")
    check("remove-save", gold == 930180 and gems == {SQUARE: 1, FLAWLESS: 2} and not socketed,
          (gold, gems, socketed))

    summary = {"scope": __doc__, "build": BUILD, "checks": 19,
               "evidence_sha256": evidence,
               "checkpoints": ["kbm-jeweler-combine-before-20261105", "kbm-jeweler-combine-after-20261105",
                               "kbm-jeweler-socketed-20261105", "kbm-jeweler-removed-20261105"]}
    (EVID / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    print("19 jeweler business checks passed")


if __name__ == "__main__":
    main()
