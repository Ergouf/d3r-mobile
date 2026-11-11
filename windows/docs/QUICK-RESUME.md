# Xbox-like Quick Resume (process suspend/resume)

This is intentionally not a save-game reload. It keeps the running game process
alive and suspends all of its threads. Resuming returns to the exact in-game
page, including the Damp Cellar, without the main menu or a story load.

## Commands

```powershell
# Verify the current process and state
& windows/tools/QuickResume.ps1 -Action Status

# Save the PID/window/start-time binding (do this while the game is at the
# page you want to resume)
& windows/tools/QuickResume.ps1 -Action Save

# Suspend all game threads
& windows/tools/QuickResume.ps1 -Action Suspend

# Resume the same process at the same page
& windows/tools/QuickResume.ps1 -Action Resume
```

State file: `out/windows/kbm/session/quick-resume.json` (atomic write).

The helper verifies PID + process start time before suspend/resume, so a reused
PID cannot be frozen by mistake. `session_memory.py read` includes this state as
`quick_resume` and the last page as `ui_state` / `place_name`. `Status` without a
state file returns `state=null` and `note=NO_QUICK_RESUME_STATE` instead of throwing.

## Verified in this round

- Historical pre-transition page: PID `10196`, player
  `(2293.56,2561.41,27.10)`, place `1999503360` (do not use as current state).
- `Suspend` returned success; `Status` showed `same_process_alive=true`,
  `live_suspended=true`.
- `Resume` returned success; `Status` showed `live_suspended=false`.
- CUA visual after resume showed the same Damp Cellar page; the later machine
  transition is place `1999699971`.
- Frida probes must still run serially; do not suspend while a probe is attached.

## Limits

- If the game process exits, Quick Resume cannot restore it; fall back to the
  game's Continue/save mechanism.
- This is process-level resume, not a memory/VM snapshot. The game remains
  resident in RAM while suspended.
- Do not send CUA input while the process is suspended; call `Resume` first.

## Hardening after review

- `Status` now reports `live_suspended`, `same_process`, `window_valid`, `resume_required` from the live process in addition to the file state.
- `Suspend` refuses when live threads are already suspended; `Save` refuses while suspended.
- State timestamps are UTC (`Z`); `suspend_count` is recorded.
- A state-write failure after suspend immediately calls `NtResumeProcess`.

## Verified current state

- Page: `潮湿的地窖 / Damp Cellar`; label seen by CUA.
- `place`: `1999503360` before entry, `1999699971` after entry (machine-readable scene transition).
- Player: `(52.27,126.20,0.10)` (latest snapshot; earlier entry was `(49,132)`).
- Post-resume visual evidence: 截图 `damp-cellar-resume.png` 已在 2026-11-05 清理中移除；机器证据保留 `damp-cellar-skill-ui.json` 与 `quick-resume.json`。
- Active skill: `惩罚 / Punish`, A slot; key `Space` (`keybinds.ini` a=Space).
- Skill-page machine evidence: `out/windows/kbm/session/damp-cellar-skill-ui.json`
  contains visible text `惩罚`; screenshot `damp-cellar-skill.png`.
- Directional mouse casting is **not implemented or verified**; Punish is currently a frontal melee skill.

## Coordinate-space warning

`last_session.json` keeps three different spaces: world `player.pos`,
DPI-virtualized `window.rect`, and probe `nearby.screen` projection. The latter
can exceed the window height (earlier capture: y=942 in a 230-pixel-high window; current 1024x576 still has off-screen projections).
Never add `nearby.screen` directly to `window.rect`; use the production
pointer/projection path and re-probe the live viewport.
