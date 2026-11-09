# D70–D72: MIDI subsystem card — register-level spec from Release 5.3

Scope: every access SYN-5.3 (Release 5.3, Model D) makes to the original NED
MIDI subsystem card ("D70 type device"), what it expects back, and what it
does with the bytes, so the card can be modelled in `sim/` and in HDL
(`dev_midi.sv`, plan.md M8). Source: the NED/XPL text of Release 5.3 in
`out/ned53/` (paths below are relative to it). The MIDInet (D115 / NN#MIDI)
and OMS (`interp_*`) MIDI paths are mentioned only where they change the card
path.

Tags: **[OBS]** quoted from source (file:line), **[INF]** inference with the
reasoning given, **[UNK]** not determined from the source.

Notation: XPL `"nnn"` is octal, `"Hnn"` hex; `READ(x)`/`WRITE(x)` are device
reads/writes. XPL `IF x` / `DO WHILE x` on a bare expression tests **bit 0
only**: MONITOR's `DO WHILE READ("100"); END;` (`MONCAT/11-MAIN:465`)
compiles to `D100 TO R0; IM(1) TO TAND0; IM(-3) TO RTNZ`
(`../mon.dis:3057-3059`). [OBS]

---

## 1. Devices and card organisation

| Device | Name (GLOBLITS) | Write | Read |
|---|---|---|---|
| D70 | `SYSSEL` | subsystem select (16–23 = MIDI cards) | select readback (= the select value if that card exists) |
| D71 | `MCHA` (write) / `MSTA` (read) | channel select + reset bit | input FIFO status |
| D72 | `MDAT` | output byte to the selected output | next input byte |
| D73 | — | not used by the MIDI code | not used by the MIDI code |

[OBS] `SYNLITS/GLOBLITS:58-73` ("FOR MIDI BOARD - NOTE: THEY MATCH SMPTE");
`MIDI.SUBSYS = 16` "SUBSYSTEMS ARE ADDRESSED 16 TO 23 (8 CARDS)"
(`SYNLITS/SYNCLITS:273`).

Card: "THE MIDI SYSTEM WILL SUPPORT UP TO 8 MIDI I/O SUBSYSTEM CARDS. EACH
MIDI SUBSYSTEM CONTAINS 4 OUTPUT CHANNELS AND 1 INPUT CHANNEL."
(`SYNRSOU/05-BUTT/142-MIDI:44-45`) [OBS]. A "channel" in `MCHA` is a UART
port, not a MIDI channel: 0–3 = output jacks, 4 = the input jack. MIDI
channels (0–15) live only in the status bytes.

Other users of the shared D70–D73 bus (a card model that owns D70–D73 must
answer them):

| Select written to D70 | User | Readback test |
|---|---|---|
| 8 (`SMPTE.SUBSYS`) | SMPTE reader: `171-PRF1:862-863`, `SYNSOU/LINKMOD/LINKSOU:783-784` (probe), `03-PRIM/143-SIO:110-120` (`INIT.SMPTE`), `10-INT/144-TIM1:793-819` (`SMPTE.SCAN`, only while `SMPTE.ONOFF<>0`, `144-TIM2:411`) | `(READ(D70)&255)=8`; bit 8 (256) = "data available" |
| `"40"` (32, `DSPEnable\|DSP#`) | DSP70 probe `SYNSOU/DSPMOD/TSMSOU:326-328` (STM screens only, `SYNSOU/STMMOD/STINSOU1`) | `(READ(D70)&"40")="40"` |
| 16–23 | MIDI (this doc) | `READ(SYSSEL)=I` (whole word) |

[OBS] All of these are gated by D51 bit 8 (`256` = `"400"`): `142-MIDI:509`,
`171-PRF1:856`, `LINKSOU:781`, `TSMSOU:322`. The NED interpreter header calls
it `D51_D70_EXISTS 0x0100 /* set if D70 SMPTE is present */`
(`out/ned-software/Code/Includes/Able Interpreter/AbleInterpreter.h:26`);
the simulator already names it `D70_EXISTS` (`sim/devices/terminal.py:28`).

## 2. Detection

### 2.1 Who probes and when

* MONITOR: no D70–D73 access. `grep` of `MONCAT/` and `-XPL/` for `"70"`–`"73"`,
  `SYSSEL`, `MIDI` finds none (only `-XPL/INTRPRTR:22`, a literal). [OBS]
* SYN-5.3 start-up, `08-INIT/670-SCPT:367-368`: `MIDI.SYNC.IS.TC = true;
  CALL INIT.MIDI.SUBSYSTEMS;` — after `INIT.SYNTHS` / `INIT.EXPAND.SYSTEM`,
  before `INIT.DEFAULTS` and before `INITIALIZE.COMPLETED=1` (`670-SCPT:539`).
  [OBS]
* Re-run on keyboard power restore: `RESTORE.POWER` (`05-BUTT/155-SCN1:177`,
  called from `08-INIT/610-INI1:175,202,222`), only if `MIDI.THERE<>0`. [OBS]
* Re-run when MIDInet comes/goes (`SYNSOU/TRAPMOD/TRAPNET`). [OBS]

With D51 bit 8 **clear** SYN-5.3 never touches D70–D73 (every path is gated
by D51 bit 8, by `MIDI.THERE & MIDI.THERE.ORIG`, by a non-zero
original-hardware routing word, or by `SMPTE.ONOFF`). [OBS gating above;
INF that no other path exists, from the exhaustive grep of `SYSSEL|MCHA|MSTA|
MDAT|D70..D73|"70".."73"` outside `* Old` files]

### 2.2 `INIT.MIDI.SUBSYSTEMS` (`142-MIDI:494-583`)

```
DISABLE.INTERRUPTS;
MIDI.THERE = MIDI.THERE & not(MIDI.THERE.ORIG);   /* 0x3FFF, SYNCLITS:436 */
MAX.MIDI.CHAN = 0;
IF ((READ("51")&256)<>0)
&& ((interp_real_time_prefs(SYNCLAVIER_PREF_POLL_DD70MIDI) & SYNCLAVIER_PREF_POLL_DD70MIDI) != 0)
THEN DO;
   I=16; J=I;
   DO WHILE (J=I) AND (I<24);
      WRITE(SYSSEL)=I;
      IF (READ(SYSSEL)=I) AND ((READ(MSTA)&2)=0) THEN DO;   /* exists, cables OK */
         MIDI.THERE = MIDI.THERE \ BITS(I-16);
         MAX.MIDI.CHAN = MAX.MIDI.CHAN+4;
         DO J="10" TO "14";              /* 8..12 */
            WRITE(MCHA)=J;               /* select UART J&7, assert reset */
            WRITE(MDAT)=READ(MDAT);      /* init rotary ptrs */
         END;
         WRITE(MCHA)=0;                  /* deassert reset */
         J=I;
      END;
      ELSE J=0;
      I=I+1; J=J+1;
   END;
END;
```
[OBS] `142-MIDI:506-531`.

* `interp_real_time_prefs` is Native 122 (`-XPL/INTRPRTR:126`), compiled as
  `IM(n) TO RTNV` (a transfer *never*, docs/release-5.3.md §5). On NED
  hardware it returns its argument: `04-SEQ/160-SEQ0:74-75` "pass in
  SYNCLAVIER_PREF_CREATE_CLOCK - should return that to default to ON on model
  D". Here the argument is the bit itself (`0x0002`), so the test is true on
  Model D. [OBS comment; INF for this call site]
* Cards must be contiguous from 16: the loop stops at the first missing
  select. [OBS]

**Exact access sequence, one card at 16:**

| # | Access | Card must return |
|---|---|---|
| 1 | W D70 = 16 | — |
| 2 | R D70 | **16** (exact word) |
| 3 | R D71 | bit 1 = 0 (cables OK) |
| 4–18 | for J = 8..12: W D71 = J; R D72; W D72 = (that value) | any (ignored) |
| 19 | W D71 = 0 | — |
| 20 | W D70 = 17 | — |
| 21 | R D70 | anything ≠ 17 |
| 22 | R D71 (probably) | anything (result ANDed with a false term) |

[INF] Access 22: XPL `AND` in an `IF` is a bitwise AND of two 0/1 values;
nothing in the source suggests short-circuit, so D71 is read for select 17 as
well. The model must answer D70/D71/D72 reads for *any* select value without
halting.

Observed in the simulator (SYN-5.3 with `sim/devices/midi.py`, 2026-11-09):
accesses 1–21 exactly as above, and **no** access 22: after `R D70` for
select 17 returns 0 the next access is `W D70 = 16` (the 1 ms scan). So
the compiled `IF` does not read MSTA once the readback test fails (question
4 below). [OBS]

Results: `MIDI.THERE` bit 0 set; `MAX.MIDI.CHAN = 4` (4 outputs, numbered
1–4 in the UI). Then the routine resets MIDI controller values
(`MIDI.ANALOG.IN`: pedal 1 = `RTE.MAX` (225), pedal 2 = 0 unless
`SYNCLAVIER_PREF_PEDAL2_MAX` — called with argument 0 so 0 on hardware —
others 0; `MIDI.SWITCHDATA` = 0) (`142-MIDI:556-575`). [OBS]

## 3. Registers

### 3.1 D70 `SYSSEL`

* Write: subsystem number. Values written: 16–23 (MIDI), `R&"37"` from the
  routing word (`142MIDIA:115` etc.), 8 (SMPTE), 32 (DSP70). [OBS]
* Read: MIDI code compares the whole word with the select value
  (`142-MIDI:486,515`). [OBS] → model: return the latched select if it names
  an existing MIDI card, else 0. [INF; 0 also fails the SMPTE `&255 = 8` and
  DSP70 `&"40"` probes, i.e. "no SMPTE, no DSP70"]
* Selection persists across accesses; code always re-selects after any
  `ENABLE` window (`142-MIDI:1230,1262`; TIM4 re-selects 16 before testing
  MSTA). [OBS]

### 3.2 D71 write `MCHA`

| Bits | Meaning | Values seen |
|---|---|---|
| 0–2 | UART / port: 0–3 output jack, 4 input jack | 0–4 |
| 3 (`"10"`) | reset line ("SELECT UART AND ASSERT RESET LINE") | 8–12 during init, then 0 |

[OBS] `142-MIDI:487-489,523-526,849,1254`; outputs: `142MIDIA:118-119`
(`SHR(R,5)&3`), sync output `((MIDI.SYNC.OUT&"377")-1)&3`
(`142MIDIA:687`, `144-TIM2:874`).

Reset protocol: with bit 3 set, `WRITE(MDAT)=READ(MDAT)` "INIT ROTARY PTRS"
— [INF] one MDAT access while reset is asserted empties that port's FIFO
(read and write pointers). Model: any MDAT access with MCHA bit 3 set clears
the FIFO of port `MCHA&7`; the read returns 0 and the write is discarded.

### 3.3 D71 read `MSTA`

| Bit | Meaning | Source |
|---|---|---|
| 0 | input FIFO not empty | `DO WHILE READ(MSTA)` tests bit 0 (`142-MIDI:847,1252`); change log "12/31/86 MODIFIED SCAN.MIDI TO ONLY LOOK AT INPUT BIT" (`142-MIDI:27`) [OBS] |
| 1 | cable/port fault; 0 = "CABLES ARE OK" | `142-MIDI:516` [OBS]; electrical meaning [UNK] |
| 2–15 | [UNK] — must read 0 | TIM4 calls `SCAN.MIDI` on `READ(MSTA)<>0` (whole word, `144-TIM4:81,90`) [OBS] |

MSTA is read right after `WRITE(SYSSEL)` with `MCHA` still holding whatever
the last writer left (0–3 after output, 0 after init); `MCHA=4` is written
only after the test (`142-MIDI:845-849`). [OBS] → MSTA reports the input FIFO
regardless of the `MCHA` port. [INF]

There is no output status: no code reads a "transmit full/empty" bit before
writing MDAT. [OBS every `WRITE(MDAT)` site in §5]

### 3.4 D72 `MDAT`

* Read (with `MCHA=4`): next byte from the input FIFO, one byte per read, in
  bits 0–7. No port number, no timestamp: the byte is used directly (`MIDI&128`,
  `MIDI<240`, `KEY = MIDI + …`) (`142-MIDI:850-877`). [OBS] Bits 8–15 must be
  0. [INF from those uses]
* Write (with `MCHA=0..3`): one byte queued on that output jack. [OBS]
* Input FIFO depth: 64 bytes. `IF MIDI.BYTES.READ>63 /* I.E., INPUT BUFFER
  WAS FULL */ … MIDI.OVERRUN=1` (`142-MIDI:1235-1239`, aux `1267-1270`). [OBS
  test; INF depth = 64]
* Output FIFO depth: [UNK]. Each of the 5 ports has a FIFO with "rotary
  pointers" (init loop J=8..12). `ALL.MIDI.NOTES.OFF` writes 48 bytes to each
  output back-to-back without status checks (`142-MIDI:640-658`), so a port
  must buffer ≥ 48 bytes or lose bytes. [INF]

## 4. Input path

### 4.1 Polling (no interrupt)

`TIME.BASE.SCAN.QUE.AND.SCAN.INPUTS` (`144-TIM2:447` … `144-TIM4:128`), with
interrupts disabled:
```
IF ((MIDI.THERE & MIDI.THERE.ORIG)<>0) THEN DO;
   WRITE(SYSSEL)=MIDI.SUBSYS;
   IF READ(MSTA)<>0 THEN CALL SCAN.MIDI;
   ELSE IF EXT.CLOCK.MODE=4 THEN DO;            /* aux jack sync */
      WRITE(SYSSEL)=MIDI.SUBSYS+1;
      IF READ(MSTA)<>0 THEN CALL SCAN.MIDI;
   END;
END;
```
[OBS] `144-TIM4:76-97`.

Cadence: from the D16 interrupt every 1 ms once D16 is measured
(`144-TIM2:280-357`; `MEASURE.D16` only after `INITIALIZE.COMPLETED`), or
from the D03 interrupt every 5 ms while no D16 is found (`144-TIM2:378-380`).
Skipped if re-entered (`WITHIN.SCAN`, `144-TIM2:605-612`). [OBS] No MIDI interrupt
or PSW bit is used. [OBS: no other `MSTA` reader]

### 4.2 `SCAN.MIDI` (`142-MIDI:765-1275`)

```
DISABLE; WRITE(SYSSEL)=16;
DO WHILE READ(MSTA);          /* bit 0 */
   WRITE(MCHA)=4;
   MIDI=READ(MDAT);
   ENABLE; …parse one byte…; DISABLE;
   WRITE(SYSSEL)=16;
END;
ENABLE;
IF MIDI.BYTES.READ>63 THEN overrun;
IF EXT.CLOCK.MODE=4 THEN same loop on subsystem 17, bytes to PROCESS.MIDI.AUX.BYTE (sync only);
```
[OBS] `142-MIDI:844-850,1228-1270`.

* Bytes per pass: all bytes present, including ones that arrive during the
  loop. [OBS] 64 or more in one pass is treated as overrun.
* Overrun (`MIDI.OVERRUN=1`; also set when the note, controller or program
  stacks are full: `NEW.NOTE.LIST.SIZE`=50, `SYNCLITS:84`): the main loop
  (`06-MAIN/300-MAIN:358-392`) calls `MIDI.OVERRUN.ERROR`, clears all held
  keys, and calls `INIT.MIDI.FIFO(16,4)` (select, readback check, `MCHA=12`,
  `MDAT` read+write, `MCHA=0`; `142-MIDI:475-492`). [OBS]

### 4.3 Parsing

State machine, running status supported (`142-MIDI:1181-1215`) [OBS]:

| Byte | Action |
|---|---|
| `80`–`EF` | `CHANNEL=b&15`, `MIDI.STATE=((b>>4)&7)+1` (1 note off … 7 pitch wheel), `SUBSTATE=0` |
| `F0` | if `MIDI.INPUT.CHAN>-2`: enter sysex; bytes saved only while recording or echo on (`SAVE.SYSEX.BYTE`, `142-MIDI:802-822`) |
| `F1`–`F7` | system common state 8: `F2` song position (used only if `EXT.CLOCK.MODE=3`), `F3` song select, others ignored; any status ends a sysex |
| `F8`–`FF` | only if `EXT.CLOCK.MODE=3`: `SYNC.TO.MIDI` (F8 clock, FA start, FB continue, FC stop); otherwise ignored |

Data bytes are processed when (`142-MIDI:857-863`):
`MIDI.STATE>7` (system common / sysex), or (`MIDI.INPUT.CHAN=-1` or
`=CHANNEL`) and `PTMC=0` (MIDI mapped to keyboard), or `PTMC=1` and
`MIDI.MAPPING(CHANNEL+2)<>1` (mapped to recorder track). [OBS]

**Note on / off** (`142-MIDI:874-969`) [OBS]:
* `KEY = note + (36-60) + KBD_TRANSPOSE` (`GLOBLITS:118-119`): MIDI 60 =
  Synclavier key 36 (middle C).
* Note on with velocity ≠ 0: push `NEW.NOTE.STAK` = `1\"10"\SHL(ORIGIN,8)`,
  `NEW.NOTE.KEY#`=KEY, `NEW.NOTE.TIME`=`KBD.MILLISECONDS` (no sync delay),
  `NEW.NOTE.VEL` = `VMAP.PTR` table lookup of the velocity (after the
  sensitivity scaling when `V.S.MIN<>100`) — a 0–`RTE.MAX` (225) volume;
  default table is the hand-made one at `142-MIDI:306-440`; sets `NEWKEY=1`.
* Note on velocity 0 or note off: push release code `2\"10"\SHL(ORIGIN,8)`,
  time 0; release velocity ignored.
* `ORIGIN` = 0 (keyboard track) when `PTMC=0`, else
  `MIDI.MAPPING(CHANNEL+2)`.
* The per-track "velocity active" gate is commented out (`142-MIDI:943-948`):
  velocity always applies. [OBS]

From there the notes take the same path as the Synclavier keyboard
(`NEW.NOTE.STAK` → note start code), so a note on track 0 plays the current
keyboard timbre. [OBS for the stack; INF that no further MIDI-specific gate
exists, since `144-TIM4:45-60` pushes external-trigger notes the same way]

### 4.4 Defaults at start-up and what the user must set

| Setting | Default | Source |
|---|---|---|
| `POLY.TIMBRE.MIDI.CONTROL` (PTMC) | 0 = "MIDI MAPPED TO KEYBOARD" | `670-SCPT:398` [OBS] |
| `MIDI.MAPPING(2..201)` | 1 = off (used only when PTMC=1) | `670-SCPT:394-396` [OBS] |
| `MIDI.INPUT.CHAN` | from defaults file word 73; if the file's word 0 is 0 (not initialised) → **−1 = OMNI** | `08-INIT/600-INIT:749-774,847` [OBS] |
| `MIDI.ECHO.DISABLED` | defaults word 74; uninitialised → **1 (echo off)** ("changed to default to echo disable CJ 2007-08-08") | `600-INIT:775,848` [OBS] |
| Active MIDI RTEs per timbre | `Misc#ActiveMIDIRTEs` default `"100000"\|B.MWHEEL\|B.PWHEEL\|B.VELOCITY`; a timbre loaded from a bank gets `GID(Default.MIDI.RTEs)` | `600-INIT:785,867`; `11-TIMB/162-TMB2:716,740` [OBS] |
| `EXT.CLOCK.MODE` | 0 (internal) | [INF: set only from panel/screens] |

The defaults file in this tree (`W0X/*SYSTEM/*SDEF-7.sdat`, 16 KB) is all
zero words [OBS: decoded], so the uninitialised defaults apply. [UNK] whether
the user's Synclavier³ W0 image has a different `.SDEF-7`.

**User action needed: none.** With one card detected, a MIDI keyboard on any
channel plays the current keyboard timbre with velocity. [INF from the table]
Settings that change this: the MIDI input channel field on the routing
screen cycles ALL → 1…16 → OFF (`SYNSOU/ROUTMOD/ROUTSOUA:241-250`; −2 = OFF
ignores channel data); the "MIDI mapped to recorder" toggle
(`05-BUTT/171-PRF1:1144`) switches to per-channel track routing via
`MIDI.MAPPING`, where all channels start off.

## 5. Controllers

Routing tables `MIDI.CROUT(0..63)` (continuous) and `MIDI.SROUT(0..31)`
(switches 64–95), set by `INIT.MIDI.ROUTINGS` (`142-MIDI:207-225`, called
`670-SCPT:391`). Continuous values are applied only if the matching bit is
set in the track's `THD.ACTIVE.MIDI.RTES` (`142-MIDI:1017-1021`); switches
are not gated. [OBS]

| MIDI message | Synclavier destination | Scaling | Default active? |
|---|---|---|---|
| CC 1 | R.MWHEEL (mod wheel, index 2) | 0–127 → 0–225 | **yes** (B.MWHEEL) |
| CC 2 | R.BREATH (3) | 0–127 → 0–225 | no (B.BREATH clear) → dropped |
| CC 4 | R.PEDAL2 (1) | 0–127 → 0–225 | no → dropped |
| CC 7 | R.PEDAL1 (0) | 0–127 → 0–225 | no → dropped |
| CC 64 | R.SUST.SW (sustain, `SYNCLITS:278`) | >63 = on (`RTE.MAX`), else off | **yes** (switches ungated) |
| CC 65 | not routed (`142-MIDI:223` commented out) | — | stored only |
| Pitch bend `E0` | R.PWHEEL (4); LSB ignored, MSB 0–127 → −100…+100 | `142-MIDI:1111-1133` | **yes** (B.PWHEEL) |
| Channel pressure `D0` | `MIDI.PRESSURE(ORIGIN)` (or per-key if mono-to-poly) | 0–127 → 0–225 | no (B.PRESSURE clear) → dropped |
| Poly pressure `A0` | per-key pressure table | 0–127 → 0–225 | no → dropped |
| Program change `C0` | `NEW.PROGRAM.STAK` | — | see below |
| Any other CC (incl. 32–63 LSBs, 65, 96–127, 120–127 mode messages) | `MIDI.RTE.STAK` → `MIDI.TRACK.RTES` table; echoed if echo on; recorded if recording | — | no sound effect |

[OBS] `142-MIDI:1000-1075,1091-1133`; `B.*`/`R.*` in `SYNLITS/TIMLITS:299-318`;
unmapped-CC consumer `05-BUTT/155-SCN1:1040-1103`.

Ribbon: no MIDI controller is routed to R.RIBBON. [OBS]

Program change does **not** recall timbres: `06-MAIN/313-GHLD:27-80` echoes
it (if echo on and the track has MIDI output) and records it into the
sequence when recording; nothing else. [OBS]

All Notes Off (CC 123) from the keyboard is an unmapped CC: no effect on
sounding notes. [OBS by the CC path above]

## 6. MIDI output

All output writes: `DISABLE; WRITE(SYSSEL)=R&"37"; WRITE(MCHA)=SHR(R,5)&3;
WRITE(MDAT)=status; WRITE(MDAT)=data…; ENABLE` with no status polling
(`142MIDIA:115-131,192-208,277-293,356-371,457-473,536-552,625-641,
1032-1047,1161-1163`). `RUNNING.STATUS LIT '00'` (`142-MIDI:47`): every
message carries its status byte. [OBS] Output number n (1–32 in the UI) =
subsystem `16+(n-1)/4`, port `(n-1)&3` (`142MIDIA:686-687`). Routing word
`THD.MIDI` bits 0–4 subsystem (16–23), 5–6 port, 8–11 MIDI channel
(`142-MIDI:65-68`). [OBS]

What SYN-5.3 sends by default:

| Source | Bytes | Default |
|---|---|---|
| Track/keyboard notes, controllers, pressure, program | `9n/8n/Bn/En/Dn/An/Cn` | **none**: every timbre loads with `THD.MIDI=0` (`162-TMB2:714`, `161-TMB1:198-199`) |
| Echo of MIDI input | as above | **none**: echo disabled and needs a routed track |
| MIDI sync out | `F8` clock (idle and playing), `FA`/`FB`/`FC`, `F2` SPP, MTC `F1 xx` quarter frames and full-frame sysex | **none**: `MIDI.SYNC.OUT=0` until set on the routing/sync screen (`182-UPD2:694,746`, `ROUTSOUB:562`); code `144-TIM2:873-876,913-915,970-972`, `142MIDIA:686-861` |
| `ALL.MIDI.NOTES.OFF` | `Bk 7B 00` for k=0..15 on each of the 4 ports of each detected card (192 bytes/card) | **sent regardless of routing** on: STOP pressed twice (`173-PRF3:440-447`), note memory reset (`03-PRIM/050-MEM:377-378`), `182-UPD2:794`, `TRAPPB:65` |

[OBS rows; INF "none" = no other `WRITE(MDAT)` site is reachable with zero
routing words and `MIDI.SYNC.OUT=0`]

## 7. Timing

* No timeouts, no timestamps from the card, no baud-rate setting: SYN-5.3
  never programs the UARTs (only the reset bit). 31250 baud is implicit.
  [OBS: the only MCHA writes are 0–4 and 8–12]
* Note time = `KBD.MILLISECONDS` when the byte is parsed (1 ms poll), so
  latency is ≤ 1 ms + parse time. [OBS `142-MIDI:926`]
* At 31250 baud at most ~3 bytes arrive per 1 ms poll; the 64-byte overrun
  test assumes that pace. A model fed faster than 31250 baud (USB-MIDI
  bursts, or MidiLink at higher speed) can trip `MIDI.OVERRUN` (error
  message, all keys released, input FIFO flushed). [INF]
* `SYNC.TO.MIDI` (`142-MIDI:687-728`) has CASE entries for F8–FC only;
  with `EXT.CLOCK.MODE=3`, `FD`–`FF` (e.g. active sensing `FE`) index past
  the table. [OBS case list; UNK what the compiled `DO CASE` does out of
  range] With the default `EXT.CLOCK.MODE=0` these bytes are ignored.

## 8. Open questions [UNK]

1. MSTA bits 2–15 and the electrical meaning of bit 1.
2. Output FIFO depth and behaviour when full (the code never checks).
3. What the real card returns on D70/D71/D72 reads when the selected
   subsystem is absent (bus float vs 0).
4. ~~Whether XPL's `AND` short-circuits (decides access 22 in §2.2).~~
   Observed: it does at this site; no D71 read for select 17.
5. Whether the user's Synclavier³ `.SDEF-7` sets MIDI input channel / echo /
   active RTEs differently from the zero defaults.
6. Out-of-range `DO CASE` for `FD`–`FF` in MIDI sync mode.

## 9. Model choices (minimum card for one subsystem, 1 in + 1 out)

Goal: SYN-5.3 detects one MIDI subsystem, receives notes, and may send bytes.

* **D51 bit 8 (`0o400`) set** in the terminal's device bits. This also tells
  SYN-5.3 a SMPTE/DSP70 board may exist; the model answers those probes
  with "absent" (below).
* Own D70–D73; never halt on any read or write of them.
* **D70**: write latches `sel` (16-bit). Read returns `sel` if `sel == 16`,
  else 0.
* **D71 write**: latch `mcha = value & 0xF` (port = bits 0–2, reset =
  bit 3).
* **D71 read**: if `sel == 16`: `1 if input FIFO not empty else 0` (bit 1 =
  0, other bits 0) regardless of `mcha`; else 0.
* **D72 read**: if `sel == 16` and `mcha & 8`: clear FIFO of port
  `mcha & 7` (input FIFO for 4), return 0. If `sel == 16` and `mcha == 4`:
  pop one byte (0 if empty), return it in bits 0–7. Otherwise 0.
* **D72 write**: if `sel == 16` and `mcha & 8`: clear that port's FIFO,
  discard. If `sel == 16` and port 0–3: append `value & 0xFF` to that port's
  output queue. Port 0 → MiSTer UART TX (MIDI out); ports 1–3 → discard (or
  merge onto the same TX if a single jack should carry all four).
  Otherwise ignore.
* **D73**: reads 0, writes ignored.
* Input FIFO: 64 bytes, fed from the UART RX at ≤ 31250 baud pacing; drop
  new bytes when full. Output queue: ≥ 64 bytes per port (≥ 48 needed for
  `ALL.MIDI.NOTES.OFF`), drained at the UART rate; drop when full.
* No interrupts, no PSW bit.
* Pass all received bytes through unfiltered (SYN-5.3 parses running
  status, real-time and sysex itself). Optionally strip `FE` active sensing
  and `F8` clocks to save FIFO space; they are ignored in the default
  `EXT.CLOCK.MODE=0`.

Implemented this way in `sim/devices/midi.py` (`MidiSubsystem`) and
`hdl/dev/dev_midi.sv`; `hdl/core/midi_card_feed.sv` feeds the input FIFO
from the MiSTer UART (messages re-sent with their status byte; F8/FA/FB/FC
passed; FE, SysEx and system common dropped; panel-control messages kept
back for the keyboard paths). Ports 0–3 share one 256-byte output FIFO
and one UART output. State images with the card: `tools/w0_image.py
--midi`. Lockstep trace event `K` kind 8 puts a byte in the input FIFO.

Expected result with defaults (OMNI, mapped to keyboard, echo off): note
on/off with velocity on any channel plays the keyboard timbre; CC1 → mod
wheel, pitch bend → pitch wheel, CC64 → sustain; CC2/4/7, pressure and
program change have no audible effect; SYN-5.3 sends nothing on output
except the 192-byte All-Notes-Off burst (ports 0–3) on double STOP and
similar resets.
