"""Verify F2 runtime menu over a game pause plus exit confirmation closes only itself."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/continue-20261108"
BUILD = "4F05819440313DEE84D83C9DC9D1A78A1481ECD2D07320ADA0F8B0836C9D0F00"

fails = []
checks = 0


def load(name):
    return json.loads((EVID / name).read_text(encoding="utf-8"))


def texts(doc):
    return "\n".join(item.get("text") or "" for item in doc["ui"]["items"])


def check(name, ok, detail=None):
    global checks
    checks += 1
    if not ok:
        fails.append({"name": name, "detail": detail})


pause = load("stack3-pause.json")
confirm = load("stack3-confirm.json")
overlay = load("stack3-f2-open-session.json")
overlay_bindings = load("stack3-f2-open2.json")
closed_overlay = load("stack3-f2-closed.json")
closed_bindings = load("stack3-f2-closed-bindings.json")
space = load("stack3-space-close-confirm.json")
world = load("stack3-esc-close-pause.json")

for name, doc in (("pause", pause), ("confirm", confirm), ("overlay", overlay),
                  ("closed-overlay", closed_overlay), ("space", space), ("world", world)):
    check(f"{name}-build", doc["build"]["exe_sha256"] == BUILD, doc["build"])
check("pause-one-layer", pause["state"]["ui_blocked"] == 1 and "游戏已暂停" in texts(pause) and
      "你想要退出当前游戏并返回到主菜单吗" not in texts(pause))
check("pause-object-count", len(pause["ui"]["items"]) == 662, len(pause["ui"]["items"]))
check("confirm-second-layer", confirm["state"]["ui_blocked"] == 1 and "提示" in texts(confirm) and
      "你想要退出当前游戏并返回到主菜单吗" in texts(confirm))
check("confirm-object-count", len(confirm["ui"]["items"]) == 680, len(confirm["ui"]["items"]))
check("runtime-menu-third-layer", overlay_bindings["shown"] == 1 and len(overlay["ui"]["items"]) == 680,
      {"shown": overlay_bindings["shown"], "items": len(overlay["ui"]["items"])})
check("runtime-menu-close-leaves-two", closed_bindings["shown"] == 0 and
      closed_overlay["state"]["ui_blocked"] == 1 and len(closed_overlay["ui"]["items"]) == 680 and
      "你想要退出当前游戏并返回到主菜单吗" in texts(closed_overlay))
check("space-closes-confirm-only", space["state"]["ui_blocked"] == 1 and
      len(space["ui"]["items"]) == 662 and "游戏已暂停" in texts(space) and
      "你想要退出当前游戏而返回到主菜单吗" not in texts(space) and
      "你想要退出当前游戏并返回到主菜单吗" not in texts(space))
check("esc-closes-pause", world["state"]["ui_blocked"] == 0 and "游戏已暂停" not in texts(world))

summary = {
    "build": BUILD,
    "pid": overlay["identity"]["pid"],
    "scope": "three layers: game pause, exit confirmation, F2 runtime menu; each key closes only its top layer",
    "items": {"pause": len(pause["ui"]["items"]), "confirm": len(confirm["ui"]["items"]),
              "runtime_menu_shown": overlay_bindings["shown"], "after_space": len(space["ui"]["items"]),
              "after_final_esc": len(world["ui"]["items"])},
    "checks": checks,
    "failures": fails,
}
(EVID / "three-layer-stack-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(summary, ensure_ascii=True))
raise SystemExit(bool(fails))
