# D130/D131: velocity/pressure keyboard (VPK), button panel and display

The velocity/pressure keyboard ("VK", "VKP", "new keyboard"): a clavier
with per-key velocity (transit time) and per-key pressure, a 160-button
lighted panel, a 2 × 16 character display, a control knob, ribbon, pitch
and mod wheels, breath input, two pedals and eight foot switches/toggles.
It sits on the same two device addresses as the original keyboard
([d130-original-keyboard.md](d130-original-keyboard.md)) but speaks a
different protocol: the low bits of CREG select a **mode**, D130 carries an
opcode/address word, and an EXW strobe on CREG bit 40 hands it to the
keyboard.

| Device | Name in NED source | Direction |
|---|---|---|
| D130 | `DREG` "keyboard interface data register" | read and write |
| D131 | `CREG` "keyboard interface control register" | write |

`SYNLITS/GLOBLITS:97-99` (`DREG`, `CREG`, `PULSE_EXWR`). Model:
`sim/devices/synth.py` `VelocityKeyboard` (section 8's choices),
`hdl/dev/dev_vpk.sv` (checked against it: `tests/hdl/test_board.py
test_dev_vpk`); MIDI to the VPK: `hdl/core/midi_vpk.sv`. The state image
selects it (device 7 index 30, `sim/lockstep.py`).

Tags: **[OBS]** read in the source (file:line, paths under `out/ned53/`),
**[INF]** concluded from it, **[UNK]** not settled, **[CHOICE]** the model's
decision.

## 1. Build flags and detection

SYN-5.3 is compiled as a **VK build that also handles an ORK**:
`new.pan = 1`, `inc.creg = 1`, `inc.kbd.maps = 1` (`SYNLITS/somelits:20,36,39`).
`NEW.ORK` ("TRUE TO HANDLE ORK IN VK BUILDS", `05-BUTT/VKBUTMOD:116`) is a
run-time variable set at start-up; every D130/D131 access below is guarded by
`NEW.ORK == 0`. Internally the program always uses the VK's 160-button
numbering, also with an ORK attached (`05-BUTT/150-BUTT:1607-1610`). [OBS]

**SYN-5.3 `KEYBOARD.CHECK`** (`08-INIT/610-INI1:127-226`, called from
`670-SCPT:170-171` after the external-memory allocations): [OBS]

| Step | D131 writes | D130 | Meaning |
|---|---|---|---|
| 1 | `105`, then `005` | read | `= 1` → `NEW.ORK = 1` (ORK, done). Anything else → VPK |
| 2 | (`WRITE(3)` × 2: D3 delay), `0`, `40`, `0`, `100`, `0` | — | "first clear the change register" |
| 3 | (`WRITE(3)` × 2), `0`, `40`, `0`, `100` | read `V1` | keyboard change register (KCR) |
| 4 | `0` | — | remove read |

`V1 = 077777` → `RESTORE.POWER` (VK present and on). Otherwise SYN prints
"Please Check Cable and Power to Velocity Keyboard" and loops (one read per
D3 delay, ~5 ms) until it has counted **200 reads of `077777`**; S or BREAK on
the terminal returns to MONITOR (`610-INI1:176-202`). [OBS]

**MONITOR `CLEAR.KEYBOARD`** (`MONCAT/MON:201-229`): only if `d130_present`
(options-word bit `o#d130 = 40000`, set by CONFIGUR, not probed;
`-XPL/SYSLITS:59,70`). Writes CREG `105`, reads D130: `= 1` clears the ORK
lights; otherwise clears the VK: lights 0–159 off (mode 3), characters 0–31
to space and DP words 32, 36, 40, 44, 48, 52 to 0 (mode 2). [OBS]

**What the VPK must return:** on CREG `105` + read, anything but `1`; in
mode 0, KCR = `077777` when idle (section 2.1). [OBS]

## 2. Register protocol

### CREG (D131)

| Bits | Meaning |
|---|---|
| 0–1 | mode: 0 keyboard change register, 1 "expanded opcodes" (keys, pressure, analog, buttons), 2 alpha display, 3 lights |
| 5 (`40`) | EXW strobe: hands DREG to the keyboard in the current mode |
| 6 (`100`) | read: D130 returns the keyboard's answer |

Every VK access is one of three sequences (all with interrupts off): [OBS]

| Sequence | Writes | Source |
|---|---|---|
| Mode 0 read (KCR) | DREG `0` (in the interrupt; not in `KEYBOARD.CHECK`), CREG `0`, `40`, `0`, `100`; read D130; CREG `0` | `10-INT/144-TIM3:1158-1166` |
| Mode 1 request/answer, `PULSE_EXWR` | CREG `1`; DREG = request; CREG `41`, `1`, `101`; read D130; CREG `1` | `GLOBLITS:99`, `072-NEWI:193-195` |
| Mode 2/3 write | CREG `m`; DREG = `addr << 8 \| data`; CREG `m + 40`, `m` | `072-NEWI:409-411, 471-473` |

The read follows the `101` write by one instruction, so the answer must be
ready then. [INF]

### 2.1 Mode 0: keyboard change register (KCR)

* Idle: `077777`. Bits use **negative logic**: a 0 marks a change. SYN
  uses only mask `017437` (bits 0–4 and 8–12) and ORs the two bytes: bit I
  (or I+8) = superoctave I changed (`072-NEWI:169,177`). [OBS]
* `0` = keyboard unplugged or off: `SCAN.VKP.FOR.NOTES` sets `POWER.OFF = 1`
  and returns (`072-NEWI:158-167`); `SCANDATA` then re-reads KCR each pass
  and counts 1000 reads of `0` (off) or 1000 reads of `077777` back to on,
  then `CLEAR.DISPLAY` + `RESTORE.POWER` (`155-SCN1:356-424`). [OBS]
* Which byte carries what (down vs up changes?) is not said. [UNK]
* Whether a read clears KCR: `KEYBOARD.CHECK` "first clear the change
  register … read twice" suggests so (`610-INI1:160-167`). The interrupt
  reads it once and `SCAN.VKP.FOR.NOTES` reads D130 again with no new EXW
  (`072-NEWI:158,169`), so the value must stay readable until the next EXW. [INF]

### 2.2 Mode 1: requests (DREG before the EXW) and answers

| Request (DREG) | Answer (D130) | Used by |
|---|---|---|
| `000 \| k`, k = key index 0–79 | bits 0–9: key k's velocity "transit time" (SYN masks `01777`) | key down, `072-NEWI:215-217` |
| `200 \| k`, k = key index 0–79 | bits 0–7: key k's pressure | `06-MAIN/370-REAL:117-127`, `155-SCN1:272-288`, `400-MISC:245-251` |
| `200 \| 88` … `200 \| 95` | bits 0–7: analog channel (section 4) | `072-NEWI:367-375` |
| `200 \| 89` | bits 8–15: eight switches (section 4) | `072-NEWI:377-395` |
| `400 \| (16 I + 15)`, I = 0–4 | superoctave I's 16 key bits, **1 = down** | `072-NEWI:193-195` |
| `600` | switch activity register (SAR): bit I−1 = bank I has a held button | `072-NEWI:341-344` |
| `600 \| I`, I = 1–10 | bank I's 16 buttons, 1 = held | `072-NEWI:308-311`, `170-SMPT:386-389` |

So bits 7–8 of the request are an opcode (0, 200, 400, 600) and bits 0–6 an
address. [INF]

## 3. Keys, velocity, pressure

### 3.1 Key scan (`SCAN.VKP.FOR.NOTES`, `072-NEWI:149-286`) [OBS]

1. KCR (mode 0, as above). If `KCR = 077777` and no leftovers (`OLDKCR`),
   done.
2. CREG `1`. For each superoctave I = 0–4 whose KCR bit is set: request
   `400 | (16I + 15)`, read the 16 key bits, compare with the bits SYN saw
   last time (`OLD.CLAVIER`).
3. Each **new key down** (0 → 1): request `000 | (16I + J)`, read the
   transit time `L = answer & 01777`; then stack note-on with key number
   `16I + J + 9 + KBD_TRANSPOSE`.
4. Each **key up** (1 → 0): stack note-off, same key number, no velocity.
5. If the 50-entry note list is full, the superoctave stays in `OLDKCR` and
   is re-read next millisecond.

Key number = key index + 9. Middle C is key 36 (`GLOBLITS:118`), so index 27
= middle C, index 0 = key 9 (A, 2 1/4 octaves below middle C).
`RESTORE.POWER` reads baseline pressure only for keys 9–84 ("KEY ACTUALLY
EXISTS ON VK", `155-SCN1:274-278`; `NUM.KEYS` = 85, `GLOBLITS:116`): a
**76-key** clavier, index 0–75, A to C (MIDI 33–108 with middle C = 60).
Indices 76–79 are never down. [INF]

### 3.2 Velocity

The answer is a transit time: **larger = slower = softer**. With
`INC.KBD.MAPS` it is limited to 255 (`072-NEWI:221`), optionally scaled for
velocity sensitivity (`V.S.MIN`, `V.S.MUL`, `231-237`), then looked up in a
256-word table `TTMAP` that gives a volume 0–225 (`RTE.MAX`, `GLOBLITS:124`)
stored as the note's velocity (`239-250`). [OBS]

`TTMAP` comes from `.SMAP-7` (`SYNMODS/FILEDCL:18`) if that file is found,
else `COMPUTE.SYNC.TTIME.MAP(mode)` (`072-NEWI:48-131`; start-up uses mode 3,
`670-SCPT:300`): `TTIME.MIN = 5 + 5 × mode`; entries 0…TTIME.MIN = 225, then
an exponential decay down to 3. [OBS] Mode 3, computed from that code: [INF]

| transit time | ≤ 20 | 21 | 25 | 30 | 40 | 50 | 60 | 80 | 100 | ≥ ~130 |
|---|---|---|---|---|---|---|---|---|---|---|
| volume | 225 | 212 | 168 | 127 | 75 | 46 | 30 | 13 | 7 | 3 |

Whether the W0 image has `.SMAP-7` and what time unit the real keyboard
counts in are not known. [UNK]

### 3.3 Pressure (aftertouch)

Polyphonic, per key, **not scanned periodically**: while a live keyboard
note has a timbre using pressure, the real-time loop reads `200 | (key − 9)`
for that note (`370-REAL:110-127`), subtracts the per-key baseline measured
by `RESTORE.POWER` (+5 dead band, `155-SCN1:272-292`) and maps it through a
calibration and pressure → volume table (`370-REAL:129-158`; without
`.SMAP-7`: calibration 225 for every key, square-law map, `155-SCN1:224-266`).
Rest value: whatever the key reads untouched (baseline), e.g. 0. [OBS]

## 4. Analog inputs and switches

`SCAN.VKP.ANALOG.INPUTS` (`072-NEWI:360-396`) requests `200 | 88` … `200 |
95` and stores `answer & 255` in `ANALOG.IN(0…7)`; names from
`SYNLITS/SYNCLITS:319-326`. Processing in `SCANDATA` (`155-SCN1`). [OBS]

| Channel | Request | `ANALOG.IN` | SYN's use | Rest value for the model |
|---|---|---|---|---|
| knob | `200 \| 88` | 0 `RAW.KNOB.POS` | delta from `RAW.KNOB.BASE` (read at power-on) | centre, e.g. 128 |
| ribbon | `200 \| 89` | 1 | active after two reads > 10; value = reading − first touch, ±100 (`155-SCN1` ribbon block) | ≤ 10 (0) |
| pedal 2 | `200 \| 90` | 2 | `235 − raw`, 0–225 (inverted) | ≥ 235 (255) |
| pedal 1 | `200 \| 91` | 3 | `235 − raw`, 0–225 | ≥ 235 (255) |
| pitch wheel | `200 \| 92` | 4 | delta from base (read at power-on); new wheel: d = |raw − base|, dead band 12, ±(d − 12) × 100/84, limit ±100 | centre, e.g. 128 |
| mod wheel | `200 \| 93` | 5 | new wheel: `(raw − 13) × 1.25`, 0–225 | ≤ 13 (0) |
| breath | `200 \| 94` | 6 | `raw − 20`, 0–225 | ≤ 20 (0) |
| (unused) | `200 \| 95` | 7 | `RESTORE.POWER`: ≥ 128 → `NEW.PM = 1` (new pitch/mod wheels), else old (`155-SCN1:162-175`) | 255 |

Switches: bits 8–15 of the `200 | 89` answer → `SWITCHDATA(0…7)`, 1 = on:
hold, repeat, glide, sustain, arpeggiate, punch, phrase, mute
(`072-NEWI:381-393`, `SYNCLITS:310-317`). [OBS]

**Knob → parameter** (`06-MAIN/395-UPDT`): `KNOB.DELTA = raw − base`; with
`NEW.PM` divided by 3. |delta| ≥ 12 adds a step to `AMOUNT` at a rate that
grows with the deflection (1 to ~90 per step, each 10 ms of elapsed time),
signed by the direction; |delta| < 8 resets. `AMOUNT` ≠ 0 calls
`MAJOR.UPDATE`, which changes the selected (last pressed) parameter. The
base follows the raw value by 1 every 10 000 passes. So the knob is read as
a **deflection from rest** (spring-return), not an absolute position. With
tone bend enabled the delta goes to the pitch wheel instead
(`155-SCN1` pitch-wheel block). [OBS]

## 5. Button panel and display

### 5.1 Buttons (read)

`SCAN.NEW.VKP.BUTTONS` (`072-NEWI:335-356`): request `600` → SAR. For each
bank I = 1–10 whose SAR bit (I−1) is set now or was last time, request
`600 | I` and compare with the previous word; each changed bit gives
physical button number **PBN = 16 × (10 − I) + bit**, with `100000` set if
now held. At most 2 changes are stacked per scan (`072-NEWI:320`); the rest
are picked up next time (`OLD.SAR`). [OBS]

So bank 10 holds PBN 0–15 and bank 1 holds PBN 144–159. Check: the SMPTE
generator polls STOP as bank 8 bit 1 (`170-SMPT:386-389`) = PBN 33 =
`stop.l`. [INF]

### 5.2 Button map (`05-BUTT/071-NEWL:23-63`, `LPN.LOOKUP`) [OBS]

160 buttons, `num.vkp.buttons = 160`. `x.n` = NED's `x.l+n`; `0` = no
function.

| PBN | bits 0–7 | bits 8–15 |
|---|---|---|
| 0–15 | `psel.0 psel.1 ve.del ve.atk ve.idec ve.fdec ve.peak ve.sust` | `psel.2 psel.3 he.del he.atk he.idec he.fdec he.peak he.sust` |
| 16–31 | `ptun pvol coef.0–5` | `ratio hgs coef.6–11` |
| 32–47 | `start stop record punch cont rew ff erase` | `mark sloop eloop speed click transp smpte ext` |
| 48–63 | `chain insert delete smt skt bounce just startup` | `tbase oratio scale.a 0 ttben trvol trackpan trrout` |
| 64–79 | `trak.0–7` | `trak.8–15` |
| 80–95 | `trak.16–23` | `trak.24–31` |
| 96–111 | `dsel bankb entryb slib seqb split 0 entrywrt` | `timb.0–7` |
| 112–127 | `kbdlkey kbdrkey repeat arpeg rrate chorus poly tname` | `dynenvl dynenvh 0 midixpos vkxpos 0 decay hadj` |
| 128–143 | `vwave vrate vdepth moddep vatk invert quant raise` | `stmode strate stdepth stcen pchorus ponoff plogl prate` |
| 144–159 | `vkvel vkpre vkpe1 vkpe2 vkmod vkrib vkkcv vkbth` | `info smin scon midi vkper vkrec vkove vkclr` |

### 5.3 Lights (mode 3)

`SET/CLEAR/BLINK.VKP.LIGHT` (`072-NEWI:402-439`): DREG = `addr << 8 |
state`, state **0 off, 1 on, 2 blink** (the keyboard blinks it). Light
address `addr = (PBN & 15) + 144 − (PBN & ~15)` = 16 × (I − 1) + bit for the
button read as bank I bit: **a light's address is its button's bank − 1 and
bit**. `ON/OFF/BLINK(lpn)` find the PBN through the inverse table built by
`panel.init` (`150-BUTT:130-230, 1612-1630`). All 160 are cleared by
`KBD.INIT`, `SILENCE.SYNTHS` and MONITOR (`072-NEWI:441-450`,
`03-PRIM/050-MEM:62-69`). [OBS]

### 5.4 Display (mode 2)

DREG = `addr << 8 | data`, latched by the EXW. [OBS]

| addr | data |
|---|---|
| 0–15 | upper line, 16 characters, ASCII (`EMIT.STRING`, `EMIT.CHAR`, `EMIT.NUMBER`, `072-NEWI:502-756`) |
| 16–31 | lower line, 16 characters |
| 32, 48, 36, 52 | decimal-point words for positions p with p & 3 = 0, 1, 2, 3 (`DP.TABLE`, `072-NEWI:27`) |

DP bit for position p: `2 × ((p & 15) >> 2) + (p ≥ 16)` in word `DP.TABLE(p &
3)` (`SET.DECIMAL.POINT`, `072-NEWI:462-479`): even bits = upper line, odd
= lower. MONITOR also clears 40 and 44. [OBS]

`073-NEWW` ("numeric window display routine for new panel") has no D130
access: it formats parameters, times and messages into the 32-character
"window" through the `EMIT.*` drivers and mirrors them in `WIMAGE` for the
Termulator/Synclavier³ screen (`NEW.CLAVIER.INFO`). Sign-on
(`DISPLAY.SIGNON`, `073-NEWW:84-133`): ` SYNCLAVIER` at 1, the release at 12,
voices at 16 and `VOICES` at 19, memory with `K`/`M` ending at 28–31. [OBS]

## 6. Timing [OBS]

| What | When | Where |
|---|---|---|
| KCR read, key scan, velocity reads | **every 1 ms** in the real-time clock interrupt (once per `OUR.MILLISECONDS` tick), interrupts on during the scan | `144-TIM3:558-563, 1157-1166`; `072-NEWI:135-140` |
| Button scan | main loop `SCANDATA` on alternate passes (`TOGGLE = 0`), ≥ 10 ms apart | `155-SCN1:428-435`, `157-SCN2:11` |
| Analog + switch scan | `SCANDATA`, `TOGGLE = 1`, > 10 ms since the last ("every 15 msec") | `155-SCN1:351, 437-442` |
| Pressure | per live note in the real-time update loop | `370-REAL:110-127` |
| Power-on measurements | `RESTORE.POWER`: analog twice (3 D3 delays apart), wheel type, 76 baseline pressure reads (keys 9–84) | `155-SCN1:128-294` |

Main-loop and interrupt accesses are separated by `DISABLE/ENABLE`, so a
request/answer pair is never interleaved with another. The only
timing-sensitive point for an emulation is that the answer is ready one
instruction after the strobe. [INF]

## 7. Release L ORK-LM; VPK alone

* **Release L ORK-LM uses none of this.** Its D131 writes (`out/ork-lm-io.csv`,
  10 s) are only ORK codes: `20`, `260`, `100–105`, `6`, `10–17`,
  `110–117`, `0–2`, `41`, `42`; no mode-1 requests, no mode-2/3 writes. [OBS]
* **SYN-5.3 runs with a VPK and no ORK model.** With `NEW.ORK = 0` every
  keyboard path (scan, buttons, lights, display, analog, pressure, power
  check) goes to the VPK drivers; the ORK drivers are only reached with
  `NEW.ORK = 1` (all call sites above). [OBS] Both use D130/D131, so one
  device must answer at a time: Release L needs the ORK, SYN-5.3 takes
  either. A core that runs both needs a run-time choice (OSD), or a VPK
  model only for SYN-5.3. [INF]
* With a VPK SYN-5.3 waits at start-up for KCR `077777` (section 1); a
  model that answers `1` to CREG `105` keeps the existing ORK behaviour.

## 8. Model choices (minimum VPK)

To be implemented as `sim/devices/synth.py VelocityKeyboard` and
`hdl/dev/dev_vpk.sv` (or a mode of `dev_keyboard.sv`). Each is a [CHOICE]
until hardware evidence turns up.

| Question | Model |
|---|---|
| CREG `105` read | `0` (anything but 1 selects the VPK) |
| Registers | CREG and DREG latched on write. On a CREG write with bit 40 set where the previous CREG had it clear: latch `request = DREG`, `mode = CREG & 3`; for mode 2/3 store `DREG & 377` at `DREG >> 8`. CREG with bit 20 (SMPTE's `20`, `260`) is ignored |
| D130 read | only with CREG bit 100; mode 0: KCR; mode 1: the answer to the latched request (computed at read time from current state); otherwise 0 |
| KCR | `077777` with bit I cleared while superoctave I's key bits differ from the bits last returned for request `400 \| (16I+15)`. Level, not latched: no read clears it, nothing is lost. High byte always 1s. Never 0 (always "powered") |
| Activity word | request `400 \| a`: key bits of superoctave `a >> 4` (low 4 address bits ignored), 1 = down |
| Velocity | per key, latched when the key goes down; returned for `000 \| k`. Host gives MIDI velocity 1–127; the model converts it to the transit time whose mode-3 volume is closest to `velocity × 225 / 127` (127 → 20, 64 → ~30, 1 → ≥ 130) |
| Pressure | per key, host-set, default 0; `200 \| k` (k < 80) returns it in bits 0–7 |
| Keys | key index 0–75 = NED key 9–84 = MIDI 33–108 (MIDI = index + 33); 76–79 never down |
| Analog | 8 host-set bytes, `200 \| (88 + n)`. Rest: knob 128, ribbon 0, pedals 255, pitch wheel 128, mod wheel 0, breath 0, channel 95 = 255 (new wheels). `200 \| 89` adds the 8 switches in bits 8–15 (rest 0) |
| Knob | host gives a signed deflection; the model returns `128 + deflection` (clamped 0–255) and returns to 128 when released, since SYN reads a rate from the deflection |
| Buttons | 10 bank words; `600` returns SAR = bit (I−1) for each bank I with any bit set; `600 \| I` returns bank I. Host API takes PBN 0–159 → bank `10 − (PBN >> 4)`, bit `PBN & 15` |
| Lights | 160 two-bit states at address 0–159 (0 off, 1 on, 2 blink; 3 treated as on). Host view by PBN: address `(PBN & 15) + 144 − (PBN & ~15)` |
| Display | 32 character bytes (power-on: spaces) and the DP words at 32/48/36/52; render 2 × 16 with the DP bit rule of 5.4 |
| Answer timing | HDL: answer combinational from the latched request and current state (valid on the next I/O read) |
| Coexistence | a run-time select (ORK or VPK) on D130/D131; default ORK so Release L and existing tests are unchanged |

**Result (simulator, Release 5.3 W0):** SYN-5.3 passes `KEYBOARD.CHECK`
(no cable message) and reaches its Main Menu; the display shows
` SYNCLAVIER 5.3 ` / `40 VOICES 36M` (8 FM + 32 poly, 32 + 4 MB); BANK,
2, ENTRY, 1 on the VPK panel recalls CLARA3 (`1-2-1 … CLARA3`); a key
plays it and SYN reads its velocity (request `044` → transit time 20 for
velocity 127). With PARTIAL VOLUME selected, a knob deflection of −40 for
20 ms changes it by 1 and of −61 by 3 (`midi_vpk.sv` uses these).
Velocity changes a note's volume only once a timbre patches it (VK VEL +
destination), as on the instrument.

Checks for the model: SYN-5.3 passes `KEYBOARD.CHECK` without the "Please
Check Cable" message; the display shows the sign-on (section 5.4); `timb.0`
(PBN 104) lights; a key with velocity 127 vs 1 gives FM/poly volumes 225 vs
3; turning the knob with a parameter selected changes the display.
