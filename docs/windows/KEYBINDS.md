# Skill keys

The six skill slots (A B X Y L R) are bound to keyboard keys by
`keybinds.ini` next to the game's executable, for example
`D:\Games\DiabloIII\01001B300B9BE000\keybinds.ini`:

```ini
a=space
b=z
x=c
y=v
l=q
r=e
```

- One line per slot; the key is an SDL scancode name (case-insensitive), such
  as `space`, `z`, `1`, `left`. Do not use `f1`-`f5`, `f8`-`f11`, `escape` or `i`:
  the runtime already uses those for help/menu/screenshot/fullscreen/back/Plus,
  so the key would act twice or never reach the skill. Unknown slot names and
  duplicate keys are warned about in the log.
- A missing file, or a missing line, keeps that slot's default:
  `a=Space b=Z x=C y=V l=Q r=E`.
- The file replaces the six slot keys as a whole: there is no second
  hard-coded alias. A key that is not one of the six keeps its other meaning
  (WASD/arrows/IJKL sticks, 1/3 ZL/ZR, Enter/Backspace, I Plus). Binding a
  movement key (W/A/S/D) or a right-stick key (J/K/L) takes it away from the
  stick.
- A/B are also the menu confirm/back keys, so binding `a` to another key moves
  menu confirm with it.
- The runtime logs the loaded map as
  `input: skill keys a=... b=... x=... y=... l=... r=...` on the first keyboard
  event after start.

The values are read on the first keyboard event after start. Restart the game
after editing the file.

`Tab` opens the map from the world and `Esc` returns from it through the native action path. From patch `0034`, `Tab` is ignored while another game UI is blocked, so it does not alias the menu Down action. Assigning `Tab` to a skill overrides its default map action; `Esc` remains the back key. The current-build matrix is in `KBM-INPUT-GUIDE.md`.
