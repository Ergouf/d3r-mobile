"""Verify a boolean option toggles through the native pad path.

The options list shows a `切换` footer legend for a boolean row; the click
sends A, the setting changes in memory and is written to `prefs.dat` when the
options screen is left.  The before/after files differ in exactly one key.
"""
from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BEFORE = ROOT / "out/windows/kbm/session/prefs-toggle-0056/prefs-before.dat"
AFTER = ROOT / "out/windows/kbm/session/options-hold-0056/prefs-back0.dat"
PAGE = ROOT / "out/windows/kbm/session/options-hold-0056/page232.json"
SOUND = ROOT / "out/windows/kbm/session/options-round-0056/subtitle-page.json"
SHA_BEFORE = "B1692B5D80D6F001E0160FAAC53D5148ABF7108C5D3B64B35F1458E07CB549FD"
SHA_AFTER = "3BFCE79BD7D8B5FE72A9789BF42914B6FFB770F296284ADB2C32C000D987BF24"


def parse(path):
    out = {}
    for line in path.read_text("utf-8", errors="replace").splitlines():
        parts = line.split(' "', 1)
        if len(parts) == 2:
            out[parts[0]] = parts[1].rstrip('"')
    return out


def check(name, condition, detail=None):
    if not condition:
        raise AssertionError(name + ((": " + str(detail)) if detail is not None else ""))
    print("PASS " + name)


def main():
    checks = 0
    before = parse(BEFORE)
    after = parse(AFTER)
    check("before-hash", hashlib.sha256(BEFORE.read_bytes()).hexdigest().upper() == SHA_BEFORE)
    check("after-hash", hashlib.sha256(AFTER.read_bytes()).hexdigest().upper() == SHA_AFTER)
    checks += 2

    check("before-subtitles-off", before["CinematicsSubtitlesEnabled"] == "0")
    check("after-subtitles-on", after["CinematicsSubtitlesEnabled"] == "1")
    check("elective-untouched", before["ElectiveMode"] == after["ElectiveMode"] == "0")
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    check("only-one-key-changed", changed == ["CinematicsSubtitlesEnabled"], changed)
    checks += 4

    page = json.loads(PAGE.read_text("utf-8"))
    texts = [o["text"] for o in page["items"] if o.get("text")]
    check("gameplay-page-rows", any("自选模式" in t for t in texts) and any("显示怪物生命条" in t for t in texts))
    check("toggle-footer", any("切换" in t for t in texts))
    checks += 2

    sound = json.loads(SOUND.read_text("utf-8"))
    stexts = [o["text"] for o in sound["items"] if o.get("text")]
    check("video-page-rows", all(any(x in t for t in stexts) for x in ("电影片段字幕", "伽玛校正", "任务对话框字幕")))
    checks += 1

    print(f"{checks} options toggle checks passed")


if __name__ == "__main__":
    raise SystemExit(main())
