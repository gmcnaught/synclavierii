# D130/D131: original keyboard, button panel and display

The original Synclavier II keyboard ("ORK"): a 61-key clavier (C1–C6), a
button panel of up to 8 × 16 lighted buttons, and a 4-digit LED display,
all behind one data register and one control register.

| Device | Name in NED source | Direction |
|---|---|---|
| D130 | `DREG` "keyboard interface data register" | read and write |
| D131 | `CREG` "keyboard interface control register" | write |

Model: `sim/devices/synth.py` `OriginalKeyboard`. Tests:
`tests/sim/test_synth.py`.

## Control register (D131)

| Bits | Meaning |
|---|---|
| 0–2 | address `I`: clavier octave 0–5, panel 0–7, or display word 0–2 |
| 3 (`10`) | panel (buttons/lights) instead of clavier/display |
| 4 (`20`) | "stop the write in progress" / select the external I/O address counter |
| 5 (`40`) | EXW latch strobe for the display |
| 6 (`100`) | read: D130 returns data for address `I` |
| 7 (`200`) | with `20` and `40` (`260`): "set up external write, start counting" / "start conversion" |

## Sequences

| Operation | Writes to D131 | D130 |
|---|---|---|
| Scan the clavier (every 5 ms) | `20`, then for I = 0…5: `100 + I` | read: octave I's keys, **bit = 0 when the key is down**; octave 5 has one key (bit 0). Idle: `7777` × 5, then `1` |
| …end of scan | `I` (= 6), `20`, `260` | — |
| Read panel I | `20`, `10 + I`, `110 + I` | read: 16 buttons, bit = 1 when pressed |
| Set panel I's lights | `20`, `10 + I` | write: 16 light bits |
| Load the display | `20`; for I = 0…2: `I`, (D130 write), `40 + I`, `I`; then `20`, `260` | write: display word I, latched on the `40` strobe |
| Keyboard type (MONITOR) | `105` | read `1` = original keyboard (it is octave 5, idle) |

Key number = 12 × octave + bit + 12, i.e. 12–72 (C1–C6); middle C (C3) is
36 in NED's numbering (`076-OLDI`). Physical button number = 16 × panel +
bit (0–127); the mapping to logical buttons is a table in external memory
(`ORK.PTR`), not yet decoded.

## Evidence

* NED `Able/SYNRSOU/05-BUTT/076-OLDI` (`9c3914be9a6e`, "official" creation
  of release-M modules 5/15/86): `SCAN.ORK.FOR.NOTES`,
  `SCAN.NEW.ORK.BUTTONS`, `LOAD.ORK.DISPLAY`; the comments give the
  negative key logic and the strobe.
* `Able/SYNLITS/GLOBLITS` (`cdf09796191a`): `DREG` = 130, `CREG` = 131.
* `Able/MONCAT/MON` `CLEAR.KEYBOARD`: `WRITE("131")="105"; IF
  READ("130")=1 THEN /* OLD KEYBOARD */`.
* **Release L ORK-LM** (`out/ork-lm-io.csv`, 10 simulated seconds) follows
  these sequences exactly: 1,159 scans of `20, 100…105, 6, 20, 260`; panel
  reads `10+I / 110+I` for I = 0…7 (10 each); 4 display loads with `I`,
  `40+I`. **[OBS]**

## Open

* What `20` and `260` start ("external I/O address counter", "conversion")
  has no visible effect in the model.
* The velocity/pressure keyboard (VK) uses D130/D131 differently
  (`CLEAR.KEYBOARD`'s other branch); not modelled.
