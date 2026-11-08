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
36 in NED's numbering (`076-OLDI`). Physical button number (PBN) = 16 ×
panel + bit (0–127).

## Button map

`075-OLDL` (5/15/86) maps each PBN to a logical parameter (`ORK.LOOKUP`;
`ORK.PTR` in external memory is the reverse table, used to light buttons).
The simulator has it as `sim.devices.synth.ORK_BUTTONS` (names below are
NED's, `x.n` = `x.l+n`); `button_number("timb.0")` gives 104.

| PBN | Row 1 (bits 0–7) | Row 2 (bits 8–15) |
|---|---|---|
| 0–15 | `psel.0 psel.1` partial select; volume envelope `ve.del atk idec fdec peak sust` | `psel.2 psel.3`; harmonic envelope `he.del … he.sust` |
| 16–31 | `hgs1 hgs2`, harmonic coefficients `coef.0–5` | `scale.a ttben`, `coef.6–11` |
| 32–47 | sequencer `start stop record punch cont rew ff erase` | `eloop transp speed bounce smt skt click ext` |
| 48–63 | tracks `trak.0–7` | `trak.8–15` |
| 64–79 | `ptun vwave vrate vdepth vatk ponoff plogl prate` | `ratio decay repeat arpeg rrate chorus tbase oratio` |
| 80–95 | `vkvel vkpre vkpe1 vkpe2 vkmod vkrib vkkcv vkbth` | `smpte smin scon midi vkper vkrec vkove vkclr` |
| 96–111 | **banks** `bank.0–7` | **timbre recall** `timb.0–7` |
| 112–127 | sequence recall `seqr.0–5`, `bnkovwrt entrywrt` | filters `lpt lpfc hpt hpfc bpt bpfc bwdth dsel` |

**Recalling a timbre (Release L ORK-LM, simulator):** with the timbre
library floppy (`06-TIMBD`, file `.NEWDATA`) in F0, `bank.0` reads the
bank (34 sectors) and `timb.0` loads the timbre (258 FM writes); a key then
plays. At start-up bank 0 / timbre 0 are lit (D130 lights word 6 = `401`)
but no bank has been read, so keys are silent. **[OBS]**

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
