# VT640 graphics terminal and D44 mouse — protocol spec from Release 5.3

Scope: what SYN-5.3 (Release 5.3, Model D) and MONITOR send to and expect
from a graphics terminal on D50/D51 and from the mouse, so both can be
modelled in `sim/` and in HDL (`term_display.sv`, plan.md M13). Source: the
NED/XPL text of Release 5.3 in `out/ned53/` (paths below are relative to
it). The Macintosh ("Termulator") and Pericom MG600 dialects are described
only where they differ from the VT640 path or where the shipped
configuration uses them.

Tags: **[OBS]** quoted from source (file:line) or decoded from the disk
image, **[INF]** inference with the reasoning given, **[UNK]** not
determined from the source.

Notation: XPL `"nnn"` is octal; bytes are given in octal with the ASCII
name, e.g. GS (035). `pc(x)` queues one byte for D50 output
(`SYNSOU/TTYMOD/TTYSOU:463`).

---

## 1. Summary

* **Detection:** no probe. The terminal type is configuration word 18
  (`C#PTYPE`) of MONITOR's configuration table, set by CONFIGUR/WINSTALL
  and copied by MONITOR/the loader into every program. VT640 =
  `"021400"`. No D51 bit describes the terminal or the mouse.
* **Shipped W0 image:** word 18 = `"101400"` = **Macintosh**; word 17
  (options) = `"141473"`, mouse bit `"100"` **clear**.
* **Protocol (VT640 path):** Tektronix 4010 subset — GS (vector), FS
  (point), US (alpha), CAN (back to VT100), 10-bit coordinates in
  1024 × 780 Tek units scaled from 640 × 480 VT640 pixels, plus
  ESC FF (erase graphics), ESC `/ n d` (draw / erase / complement),
  ESC `` ` ``/`a`–`d` (line type), ESC `0`–`3` (character size).
* **Mouse (VT640 path):** a Summagraphics/Logitech serial mouse on the
  D40Q mouse port **D44 (data) / D45 (status)**, interrupt via **D54 bit 2**;
  enabled only by options bit `"100"` (`O#D44`). Polled with `P` every
  20 ms, 3-byte delta reports. SYN-5.3 draws the crosshair itself.

## 2. Terminal type selection

### 2.1 Configuration word

| Word | Name | Meaning |
|---|---|---|
| `core(1)` | `C#CONTAB` | pointer to the program's configuration table (`-XPL/SYSLITS:16`) |
| +17 | `C#CMOPT` | options; bit `"100"` = `O#D44` "D44 (mouse) is in system" (`SYSLITS:39,54,66`) |
| +18 | `C#PTYPE` | terminal: bits 8–12 type, 13–15 graphics, 0–7 nulls (`SYSLITS:74,82-85`) |

Values (`SYSLITS:98-114`) [OBS]:

| Graphics (bits 13–15) | Type (bits 8–12) | Model | Word 18 |
|---|---|---|---|
| 0 | 3 `T#VT100` | VT100 | `"001400"` |
| 1 `G#VT640` | 3 | `T#VT640` | `"021400"` |
| 2 `G#DQ640` | 3 | `T#DQ640` | `"041400"` |
| 3 `G#MG600` | 3 | `T#MG600` (Pericom Monterey) | `"061400"` |
| 4 `G#MACINTOSH` | 3 | `T#MACINTOSH` | `"101400"` |

CONFIGUR's terminal field cycles Other / Hardcopy / ADM / VT100 /
Datamedia / VT640 / DQ640 / MG600 / Macintosh and writes `shl(i,8)`
(`UTILCAT/CONFIGUR:339-379`); the mouse is its yes/no field `O#D44`
(`CONFIGUR:575,608`). WINSTALL sets `O#D44` when D57 reports a D40Q or the
terminal is a Mac (`UTILCAT/WINSTALL:365-375`). [OBS]

Propagation: MONITOR's own file holds the table; MONITOR copies it to high
core and the loader copies it into each program it starts (`MONCAT/MON:707-709`;
`sim/boot.py` `boot_from_image` docstring). So patching words 17/18 in
MONITOR (as `sim/boot.py` `set_processor` does for the processor field)
configures SYN-5.3. [OBS mechanism; INF that the patch reaches SYN-5.3,
same path as the processor field]

### 2.2 No probe, no D51 bits

* MONITOR and SYN-5.3 never query the terminal. The only terminal query in
  the tree is `UTILCAT/MODS/SET_TERM:28` (ESC `[5n`, expects ESC `[0n` or
  ESC `[3n`), libraried only by the installers `UTILCAT/WINSTALL:29` and
  `WINFIRST:15`; it only distinguishes VT100 from ADM. [OBS]
* D51 bits 8–15 are card-present bits (`AbleInterpreter.h:26-33`); none is
  the terminal or mouse. [OBS]

### 2.3 What SYN-5.3 derives (`SYNSOU/TTYMOD/TTYSOU:985-1034`)

```
if terminal.type = t#adm3 then adm=1; else do; vt100=1; pc(ESC); pc('='); end;
gtype = terminal.graphics;
screen.width=1023; screen.height=779; char.width=13; char.height=22;   /* Pericom */
tchar.width=120; tchar.height=300;                                      /* pixels*10 */
if model = t#mg600 or t#macintosh then mg600=1;
else if model = t#vt640 then vt640=1; else if model = t#dq640 then dq640=1;
if vt640 or dq640 then do; screen.width=639; screen.height=479;
   char.width=8; char.height=14; tchar.width=75; tchar.height=200; end;
```
[OBS] So a Mac is driven as an MG600 (1024 × 780), and a VT640 as
640 × 480 with an 8 × 14 graphics-alpha cell and a 7.5 × 20 pixel
text (VT100) cell.

### 2.4 Shipped configuration [OBS]

Decoded from `W0 Disk Image.simg` (MONITOR and `.SYSTEM/CONFIGUR`, config
pointer word 1): word 17 = `"141473"` (processor 3 = Model D, `O#D44`
clear), word 18 = `"101400"` = `T#MACINTOSH`, nulls 0. The current core
therefore runs SYN-5.3 as if on a Mac: `gtype=4`, `mg600=1`,
`MOUSE.PORT.IS.D50=1` (§5.6), and `term_display` skips the Tek passages.

### 2.5 What a model must set

* **VT640 graphics:** word 18 = `"021400"`.
* **D44 mouse:** word 17 `| "100"`. Without it `D44_PRESENT`
  (`SYNAUXS/MOUSELIT:13`) is false: MOUSE.INIT skips D44
  (`MOUSFSOU:268`), `MOUSE.COMMAND` stays `M$HALT` (0), the 20 ms poll is
  never called (`10-INT/144-TIM2:413-415`) and GETSOU never updates the
  cursor (`SYNSOU/GETMOD/GETSOU:206`). [OBS]

### 2.6 Screens that require graphics [OBS]

| Screen | Gate |
|---|---|
| K Music Notation | `(vt640\mg600)=0` → "Graphics Terminal Required" (`SYNSOU/MNOTMOD/MNOTSOU.xpl:164`) |
| L STM Sound File Editor | `(vt640\dq640\mg600)=0` (`SYNSOU/STMMOD/STMSOU:44`) |
| Q Audio Event Editor | `mg600=0` → refused: **not available on VT640** (`SYNSOU/AUDMOD/AUD-MAIN:290`) |
| Y Keyboard Mapping | `(mg600=0) and (vt640=0)` (`SYNSOU/MAPMOD/MAPSOU:1504`); not built into SYN-5.3 (`SYNMAINS/BLD-DAEE:71`) |
| F Timbre display | `gtype<>0` selects the graphic composite display, else the numeric one (`SYNSOU/WELCMOD/WELCSOU:399`) |

Error text: `ERR.NGT` 20 "graphics terminal required" (`SYNAUXS/ERRLITS:29`,
`SYNSOU/ERRMOD/ERRSOU:321`).

## 3. Output protocol (VT640 path)

All graphics bytes in SYN-5.3 come from `SYNSOU/PLOTMOD/PLOTSOU` (the only
SYNSOU/SYNRSOU file that emits GS/US/FS/CAN; grep) plus escape commands
emitted by the screens through `pc`/`ps`. [OBS]

### 3.1 Modes

`#mode`: 0 transparent, 1 alpha, 2 vector, 3 point (`SYNAUXS/PLOTLITS`).

| Call | VT640 bytes | Source |
|---|---|---|
| `vector_mode` | GS (035); the next address is a move | `PLOTSOU:106-115` |
| `point_mode` | FS (034) — sent alone, also from transparent or alpha | `PLOTSOU:117-126` |
| `alpha_mode` | GS US (035 037); US alone if in point mode | `PLOTSOU:78-84` |
| `transparent_mode` | CAN (030), only if not already transparent | `PLOTSOU:128-138` |
| `enter.nonalias.text` | GS ETB (035 027) | `PLOTSOU:86-92`; used only by AEE (`AUD-CUE9:24`) |

MG600/Mac only: point → vector/transparent goes through alpha first
(`PLOTSOU:108-110,130-133`). [OBS]

### 3.2 Coordinates (`transmit_coords`, `PLOTSOU:236-282`)

```
x_tek = (x * 1023) / screen.width      (D4567: write(5)=x; write(6)=1023; write(7)=#px)
y_tek = (y *  779) / screen.height
HiY = (y_tek >> 5) + 040   LoY = (y_tek & 037) + 0140
HiX = (x_tek >> 5) + 040   LoX = (x_tek & 037) + 0100
```
* VT640: `#px=639`, `#py=479` (`punits` from `initialize.graphics.terminal`,
  `PLOTSOU:793-803`), so `x_tek = floor(x·1023/639)`,
  `y_tek = floor(y·779/479)`; origin bottom-left, y up. MG600/Mac: identity
  (`#px=1023`). [OBS]
* Byte order and short form: after GS (or FS) all of HiY LoY HiX LoX;
  otherwise HiY only if changed; LoY+HiX if HiX changed, else LoY if
  changed; LoX always. Standard Tek 4010 rules; no 4014 extra byte. [OBS]
* Clipping is done by SYN-5.3 (`draw`/`clip`, `PLOTSOU:303-375`), so
  `x ∈ 0..639`, `y ∈ 0..479` in VT640 pixels. [OBS]

### 3.3 Escape commands sent to a VT640

| Bytes | Meaning (source comment) | Source |
|---|---|---|
| ESC FF (033 014), in vector mode | clear graphics plane | `clear.term` `PLOTSOU:140-159`; MONITOR `04-IOMOD:341-348` |
| ESC `/0d`, `/1d`, `/2d` | data level: dots on / off (erase) / complemented | `data_level` `PLOTSOU:161-174` |
| ESC `` ` ``, ESC `a` `b` `c` `d` | line: solid, dotted, dot-dash, short dash, long dash | `line_type` `PLOTSOU:176-195` |
| ESC `/1;1a` ESC `x` | line type 5 "dot-dot no-dot" | `PLOTSOU:187-191` [UNK if used on VT640] |
| ESC `0`–`3` | char size 0 normal … 3 xlarge | `char_size` `PLOTSOU:203-210`; icon cmd 4 `SMG-ICON:138-144` |
| ESC `9`, ESC `8` (alpha mode) | "one size down", "restore" for the staff timbre name | `MNOTMOD/PLOTFNCS.xpl:217,225` |
| ESC STX / ESC ETX | MG600 block mode on/off; still sent by icon cmds 11/12 on any terminal | `PLOTSOU:470-481`; `SMG-ICON:209-223` |
| STX / ETX (bare) | "alias lines off/on" (nested counter) | `PLOTSOU:94-104`; `gbox`, `SMG-SBAR:151,245` |
| ESC `"0;`*y*`;`*g*`c` | read back screen line *y* in *g* 5-pixel groups | hardcopy only, needs D40 printer (`SYNSOU/D40MOD/D40SOU:201-210,307-311`) |

Not sent on a VT640 (gated by `mg600` or `termulator`) [OBS]: ESC `|P`*c*
fill pattern, ESC `|FF` fill, ESC `\O`*n* MG600 symbols (note heads), ESC
`\P`/`\p` Termulator polygon, ESC `!`…`M` Termulator mouse/cursor
commands, ESC `!Y`/`!X` RS-232 protocol, ESC `}9` MG600 readback
(`TPRIMSOU:430-460`, `SMG-ICON:159-205`, `PICSFNCS.xpl:225-232`,
`MOUSFSOU:44-216`, `D40SOU:197-200`).

Exception: MONITOR CLEARSCREEN sends ESC `!5M` only for `G#MACINTOSH`
(`04-IOMOD:343-345`; `MON:517-521`).

### 3.4 Text in graphics (alpha) mode

* After `alpha_mode`, printable bytes are drawn at the graphics position
  (`pstring`, `draw_text`, `PLOTSOU:212-218,557-568`). Cell per
  `char.width`/`char.height`: **8 × 14** VT640 pixels (`TTYSOU:1020-1021`);
  music notation uses the same `ALPHA_WIDTH=8`, `ALPHA_HIGHT=14`
  (`MNOTMOD/GLOBFNCS.xpl:686-687`). [OBS]
* BS (010) is used to overstrike: note heads are `o` BS `#` on VT640
  (`PICSFNCS.xpl:233-238`). [OBS]
* Data level applies to text: erase is `data_level(1)` + redraw the same
  string (`TPRIMSOU:272-283,302-314`). [OBS]
* Vertical labels: move_to, US, one char, repeated (`PLOTSOU:570-581`). [OBS]

### 3.5 Text plane and graphics plane alignment

SYN-5.3 places graphics around VT100 text with (`PLOTSOU:625-692`) [OBS]:

* `gpos.x(col·100) = col·7.5 + 8`, `gpos.y(row·100) = (23−row)·20`
* `TPOS.X(X) = (X+7)·10/75 − 2`, `TPOS.Y(Y) = 23 − Y/20` (mouse → cell)

[INF] In screen terms (y down, `Ys = 479 − y`): text row r = lines
20r … 20r+19; column c starts at pixel 8 + 7.5c; 80 columns span pixels
8 … 607. Boxes around text fields (`gbox`, SMGR objects) depend on this.

### 3.6 Who draws graphics (VT640-reachable screens)

Counted graphics-primitive calls per file (grep of `vector_mode|point_mode|
alpha_mode|connect|move_to|plot|draw_text|gbox|area.fill|data_level|
line_type|char_size|gdiam|gbow|draw.icon`, AEE excluded) [OBS]:

| Screen / module | Main files (calls) | Uses |
|---|---|---|
| F Timbre display: composite, partial, 3D harmonics, timbre frame | `TIMBMOD/TDSGSOU` (138), `TDSGSOUA` (66), `TPRIMMOD/TPRIMSOU` (43) | envelopes, tics, char sizes 0–1, point mode (3D), mouse hole |
| L STM Sound File Editor | `STMMOD/STDRSOU` (133), `STDRSOUA` (51), `STDRSOUB` (54), `STRECSOU` (25) | waveform in vector or point mode, data level |
| K Music Notation | `MNOTMOD/PICSFNCS.xpl` (89), `REFRFNCS.xpl` (41), `MENUFNCS.xpl` (23) | staves, ledger lines, alpha `o`/`#`, ESC 9/8, mouse hole at (607,449) |
| Screen manager objects (all SMGR screens: directories, recorder, patch, routing, system, sequence editor dialogs) | `SMGRMOD/SMG-SBAR` (56), `SMG-REGN`, `SMG-ICON`, `SMG-FRAM`, `SMG-GSTR`, `SMG-PROC`, `SMG-SROT` | scroll bars (VT640 branch: `gbox` + erase, `SMG-SBAR:336-360`), icons, frames, diamonds |
| Mouse cursor | `MOUSEMOD/MOUSSSOU:36-105` | 31 × 31 crosshair, complement mode |
| Every screen change | `clear.term` (45 callers) | ESC FF |

### 3.7 MONITOR

CLEARSCREEN for type 3 with graphics: GS, [Mac: ESC `!5M`], ESC FF, CAN,
then ESC `[r`, ESC `[0m`, ESC `(B`, ESC `[H`, ESC `[J`, 45 NULs
(`MONCAT/04-IOMOD:329-363`). [OBS]

### 3.8 Observed in the simulator (2026-11-09)

`sim.lockstep.syn53_cpu` on the Synclavier³ W0 image with MONITOR word 18
patched (scratch script, not in the repository), `O#D44` clear; bytes of
D50 output, parity stripped. [OBS]

* SYN-5.3 start, VT640 (`"021400"`): ESC `=` ESC `[m` · GS ESC `/0d`
  ESC `0` CAN (`initialize.graphics.terminal`) · GS ESC FF CAN ESC `[H`
  ESC `[J` (`clear.term`) · VT100 Main Menu · GS `` ` `` `@` CAN (move to
  0,0). Mac (shipped, `"101400"`) adds GS ESC `!6M` ESC `!4M` CAN ESC `!Y`
  and GS GS US ESC `8` CAN. No other graphics on the Main Menu.
* Leaving the menu (both screens): GS ESC `/2d` GS `)l4M'|M` GS `(t3Ut5E`
  = complement vectors (653,300)–(653,252) and (629,276)–(677,276) Tek =
  x 408, y 155…185 and y 170, x 393…423 VT640: the crosshair.
* `F` (graphic timbre display), 772 bytes in 60M instructions: 103 GS,
  24 US, 41 ESC; ESC `1` title size, ESC `a` / ESC `` ` `` dotted axes,
  ESC `/1d` erase-then-redraw of numbers, alpha labels.
* `K` (music notation), 1619 bytes: 114 GS, 36 US, 73 ESC; complement
  mode boxes, alpha text with **CR LF inside alpha mode**
  (`Trk` CR LF `Key` CR LF `Clf` …), and **DEL (0177) as a LoY byte**
  (`%` DEL `#X` DEL `?_`).

## 4. Input from the terminal

* **None required by the VT640 path.** No GIN/crosshair mode (no ESC SUB,
  ESC ENQ in the tree), no status query at run time (§2.2). [OBS grep]
* Keys: ESC `A`–`D` / ESC `[`… arrows, ESC `O` `P`–`S` PF1–4, keypad
  application mode ESC `O` `p`–`y` (SYN-5.3 sends ESC `=`), ESC `E`
  screen refresh, BREAK (`TTYSOU:347-376`). [OBS]
* Termulator only (any terminal type is parsed, `TTYSOU:335`): ESC `!`
  `e`–`l` / `E`–`L` → function keys 1–16; ESC `!Y` → start RS-232
  protocol; ESC `!0` b0 b1 b2 b3 b4 `M` → mouse report (§5.6). [OBS]
* Hardcopy readback (`D40SOU:221-250`): one byte per pixel group (5 pixels
  on a VT640), run-length coded (`$`n zeros, `%`n ones, `&`cn pattern),
  ended by a trailer or EOT; only with a D40 printer configured
  (`D40SOU:289`). [OBS]

## 5. Mouse

### 5.1 Devices [OBS]

`DCL D44 LIT '"44"'; DCL D45 LIT '"45"'; /* MOUSE PORT */`,
`DCL D54 LIT '"54"'; /* BITS FOR D4X INTERRUPT STATUS */`
(`SYNLITS/GLOBLITS:55-56`). D44/D45 are the third port of the D40Q
(D40/41 printer, D42/43 voice, D44/45 mouse, D50/51 terminal).

| Access | Use | Source |
|---|---|---|
| W D44 | byte to the mouse: 0 reset, `D` (0104) poll mode, `s` (0163) status, `P` (0120) position | `MOUSFSOU:239-242,289-293`; `MOUSRSOU:55-56,179,186,191` |
| R D44 | received byte (bits 0–7) | `MOUSFSOU:297,365`; `MOUSRSOU:178` |
| R D45 bit 1 (2) | receive character ready | `MOUSFSOU:296,360`; `MOUSRSOU:177` |
| W D45 = 0 | "clear status" / acknowledge transmit interrupt | `MOUSFSOU:288,295,361` |
| W D54 | interrupt enables: bit 0 D40, bit 1 D42, **bit 2 D44** | `MOUSFSOU:269-271,303-304`; `D40SOU:23`, `D42SOU:26` |
| R D54 | pending bit word; RTP `B10INT` → priority encoder → WHEN 16+bit (D44 → 18 = `D44INT`) | `RTP/INTRO:1549-1554`; `UTILCAT/DUMP:369` |

[INF] D45 bits 0 (transmit interrupt) and 2 (transmit empty) follow
D41/D51 (`AbleInterpreter.h:22-24,35-37`); SYN-5.3 never tests them. D45
baud (`"100000" | shl(b,8)`, `SYSLITS:172-182`) is never written by
SYN-5.3 or MONITOR [OBS grep]; the rate is a D40Q default [UNK].
Interrupt: PSW bit 10 (`D1_D54_IRQ 0x0400`, `AbleInterpreter.h:19`) [OBS].

### 5.2 Detection and initialisation (`MOUSE.INIT`, `MOUSFSOU:235-341`)

Called once after `initialization` (`SYNMAINS/BLD-DAEE:290`) and from
`REBOOT.TERMINAL`. With `D44_PRESENT` and not a Mac:

```
D54BITS &= ~4; WRITE(D54)=D54BITS;          /* D44 interrupt off */
loop until status = 'O' (0117):
   if now - start > 500 ms: SET.ERROR(ERR.NOMOU) /* 72 "mouse not in system" */; RETURN;
   W D45=0; W D44=0; wait; W D44='D'; wait; W D44='s'; wait;
   W D45=0; if (R D45 & 2) then status = R D44;
D54BITS |= 4; WRITE(D54)=D54BITS;           /* D44 interrupt on */
MOUSE.XMIT.DONE=0; MOUSE.COMMAND=M$POSITION;
```
[OBS] `M$WAIT` is `DO WHILE (M$TIMER - REAL.MILLISECONDS) ILT 10` (`:243`):
the difference is 0 then wraps to 65535 after one millisecond, so each wait
is ≤ 1 ms, not the commented 5–10 ms. [INF from the unsigned compare] A
reply that arrives later is still read on the next pass, because the loop
repeats. On timeout `MOUSE.READY` stays 0 and `MOUSE.COMMAND` stays
`M$HALT` (initial 0): no further D44 access. [INF]

Then for VT640/DQ640 (`:311-318`): refresh 60 ms, crosshair arm 15,
start (408,170), mouse hole (607,444); limits x 0…624, y 0…479 (`:327-330`);
`MOUSE.CURSOR.ON=1`, `MOUSE.CURSOR.TYPE=1`, `MOUSE.READY=1`. [OBS]

### 5.3 Polling and reception

* Poll: every 4th D03 tick (20 ms) if `MOUSE.COMMAND<>M$HALT`
  (`144-TIM2:408-415`), `MOUSE.SCAN.AND.POLL` (`MOUSRSOU:54-193`):
  processes a complete report if `MOUSE.XMIT.DONE`, then writes `P`
  (or `s` when `MOUSE.STATUS.REQUEST`). If no complete report arrived
  since the last poll ("timeout"): if D45 bit 1, read D44 and discard;
  write `P` again (`:174-181`). [OBS] → a report must be complete within
  20 ms of the `P`. [INF]
* Receive: `WHEN D44INT` (`MOUSFSOU:356-394`): if D45 bit 1 = 0, write
  D45=0 and return (transmit interrupt); else read D44. While
  `MOUSE.COMMAND=M$POSITION`, a byte with bit 7 set restarts the buffer;
  bytes are stored `&127`; the 3rd byte sets `MOUSE.XMIT.DONE`. Status: one
  byte. Bytes beyond 3 are ignored. [OBS]

### 5.4 Report format (response to `P`) [OBS `MOUSRSOU:104-126`; GETLITS]

| Byte | Bits |
|---|---|
| 0 | bit 7 = 1 (sync); bit 4 = X sign (1 = +); bit 3 = Y sign (1 = + = up); bit 2 left, bit 1 middle, bit 0 right (1 = down) |
| 1 | \|dX\|, 0–127 |
| 2 | \|dY\|, 0–127 |

Button bits: `MOUSE.LOOKUP` maps bit k → button k; `MOUSE(0)` returns
−1−k on press, 1+k on release; `SYNAUXS/GETLITS:74-79` defines −1 right,
−2 middle, −3 left. (The comment at `MOUSFSOU:442-450` says "button 1
left" and disagrees; GETLITS is what the screens test.) [OBS] Dynamic
scaling: a magnitude > 25 is doubled (`MOUSRSOU:107-108`). Position =
running sum, clamped to the limits (`:128-132`). Status reply: `O` (0117)
= OK. [OBS]

### 5.5 Cursor

`GETSOU:197-212`: every `MOUSE.REFRESH.RATE` (60 ms) with `D44_PRESENT`,
`MOUSE.CURSOR.UPDATE` (`MOUSSSOU:121-176`) redraws the crosshair if the
position changed: push attributes, viewport 0…639 × 0…479, vector mode,
`data_level(2)` (complement), erase old cross (2 vectors), draw new cross
(2 vectors), pop attributes (`MOUSSSOU:64-105`). It waits while more than
10 D50 output bytes are queued (`:156`). The terminal draws no cursor of
its own. Clicks are mapped to text cells with `TPOS.X/Y`
(`WELCSOU:785-786`). [OBS]

`MOUSE.CURSOR.ON=1` is set by MOUSE.INIT even without `O#D44`
(`MOUSFSOU:333`), and `MOUSE.SWITCH` calls `MOUSE.CURSOR.UPDATE` without a
`D44_PRESENT` test, so the crosshair is drawn at (408,170) on screen
changes even with no mouse (§3.8). [OBS source + simulator]

### 5.6 Macintosh alternative (shipped config) [OBS]

With `T#MACINTOSH`, `MOUSE.PORT.IS.D50=1` (`MOUSFSOU:263-266`): no D44
access; SYN-5.3 sends GS ESC `!6M` ESC `!4M` CAN (absolute, continuous
reports) and ESC `!Y` (protocol) (`MOUSFSOU:143-216,338-339`), and expects
from the terminal on D50: ESC `!0` b0 b1 b2 b3 b4 `M`, b0 = buttons (bits
0–2, as §5.4) + bit 3 relative format, X = b1<<7|b2, Y = b3<<7|b4 (14-bit,
two's complement when relative), all bytes with the same bit 7 as the ESC
(`TTYSOU:254-318,335-345`; `MOUSRSOU:71-100`). Coordinates are MG600 units
(0…1003 × 0…779). The terminal draws the cursor (hide/show ESC `!3;1M` /
`!3;0M`). Graphics then use the MG600/Termulator dialect (1024 × 780,
ESC `|P`, ESC `\O`, ESC `\P`, block mode), which the source does not
specify.

## 6. Model choices (M13)

### 6.1 Configuration

Patch MONITOR at boot (`sim/boot.py`, `tools/w0_image.py`): word 18 =
`"021400"` (VT640), word 17 `| "100"` (mouse). Reason for VT640 over the
shipped Mac setting: every VT640 byte is specified by §3 (Tek 4010 + 4
escape commands), and the mouse protocol is fully in the source (§5);
the Mac path needs the MG600/Termulator extensions (fill patterns, symbol
glyphs, polygon fill) that the tree does not define. Cost: AEE (screen Q)
refuses VT640 (§2.6); it also needs Direct-to-Disk. [INF]

### 6.2 Graphics plane and geometry

* **Bitmap: 640 × 480 × 1 bit** in VT640 pixels (300 Kbit; one
  dual-port BRAM), row = 479 − y.
* **Terminal area = the whole 640 × 480 while graphics are configured**:
  text row r on lines 20r…20r+19 (16-line glyph + 2 lines padding), column
  c at pixel 8 + ⌊7.5c⌋ (cells alternately 8 and 7 pixels wide; the 8 × 8
  font's column 7 is blank for most glyphs; line-drawing glyphs widen to
  the cell). Graphics OR text = lit pixel. [INF from §3.5]
* The current 640 × 384 text area + panel (`docs/hdl.md`) cannot hold this
  geometry: scaling graphics into 640 × 384 (x' = (x−8)·16/15,
  y' = (479−y)·4/5) keeps text alignment but clips x < 8 and x > 607,
  which loses the mouse hole (x 607…632, `TPRIMSOU:466-478`;
  `GLOBFNCS.xpl:692`) and the music-notation note area (`NOTE_RIGHT=631`,
  `GLOBFNCS.xpl:702`). So the panel strip must move (overlay / OSD toggle
  / taller video mode) when VT640 graphics are on. [INF]

### 6.3 Coordinate mapping (Tek → VT640 pixel)

Exact inverse of §3.2 for every value SYN-5.3 can send (checked for
x = 0…639, y = 0…479; Python, 2026-11-09) [OBS]:
```
x = (x_tek * 640 + 512) >> 10        (= round(x_tek * 5/8))
y = (y_tek * 630 + 640) >> 10        (x_tek ≤ 1023 → x ≤ 639; y_tek ≤ 779 → y ≤ 479; clamp y_tek > 779)
```
Plain `x_tek*5/8` and `y_tek*480/780` are wrong for 382 and 299 values.

### 6.4 Protocol subset (enough for SYN-5.3 on VT640)

State: `text` (VT100) / `vector` / `point` / `alpha`, plus `pen_down`,
last HiY/LoY/HiX, position, data level (set / clear / XOR), char size,
line type.

| Input | Action |
|---|---|
| GS in any state | → vector, pen up (next address moves) |
| FS in any state | → point [INF: SYN-5.3 may send FS from text, §3.1] |
| US in vector/point | → alpha at current position |
| CAN in graphics | → text (VT100 parser) |
| 040–077 / 0140–0177 / 0100–0137 in vector/point | Tek address bytes (HiY or HiX after LoY / LoY / LoX ends the address); vector: line from previous point if pen down, then pen down; point: plot the point |
| DEL (0177) in vector/point | LoY = 37 (a coordinate byte, not ignored; observed §3.8) |
| printable in alpha | glyph in an 8 × 14 cell scaled by (size+1), advance 8·(size+1); BS back one cell; CR → x = 0, LF → y − 14 (both observed in alpha, §3.8) |
| ESC FF | clear the bitmap (text plane untouched); pen up |
| ESC `/` digits `d` | data level 0/1/2 |
| ESC `` ` ``, `a`–`d`, ESC `x` | line type (dash patterns optional; solid acceptable [INF]) |
| ESC `/1;1a` | consume (`/`…letter) |
| ESC `0`–`3` | char size |
| ESC `8`–`;` | Tek 4014 sizes: treat as size 0 [UNK] |
| ESC STX, ESC ETX, STX, ETX, ETB, NUL | ignore |
| ESC `\|` *c c*, ESC `\` *c* (*c*), ESC `}`… | consume, ignore (MG600 only) |
| other controls / ESC + byte | ignore |

Throughput: a 640-pixel Bresenham line takes ≤ 640 clocks; one D50 byte at
38400 baud is ~4100 clocks at 16 MHz, so a pixel-per-clock rasteriser
keeps up with any byte stream. [INF]

### 6.5 Mouse model (D44/D45/D54 from MiSTer `ps2_mouse`)

* D44 write `P`: build one report from the PS/2 deltas accumulated since
  the last report (dx right +, dy up + as in PS/2), each clamped to
  ±127 with the remainder kept; buttons left → bit 2, middle → bit 1,
  right → bit 0. Queue 3 bytes. `s` → queue `O`. 0 and `D` → no reply.
* Deliver queued bytes one at a time into the D44 receive register
  (≥ 0.1 ms apart, all 3 within 20 ms); set D45 bit 1; raise D54 bit 2 if
  enabled (PSW bit 10). R D44 returns the byte and clears bit 1.
  W D45 = 0 clears only the transmit interrupt, not bit 1 (otherwise
  MOUSE.INIT, which writes D45=0 just before testing bit 1, could never
  succeed). [INF]
* R D54 → pending & enabled bits (bit 2 only, unless D40/D42 exist).
* No transmit interrupts (the handler's transmit branch then never runs).
* Gain: 1 PS/2 count = 1 VT640 pixel; SYN-5.3 doubles moves > 25. [INF;
  tune on hardware]
* Share the PS/2 mouse with `panel_mouse.sv`: in VT640 mode the pointer
  belongs to SYN-5.3 (it draws its own crosshair); hide the core's pointer
  over the terminal. [INF]

### 6.6 Checks

* `tools/vt100.py` → reference Tek interpreter producing the 640 × 480
  bitmap; compare with `term_display` pixel for pixel as for text.
* Simulator: the §3.8 captures (Main Menu, F, K) as golden byte streams;
  then a `sim/devices` D44/D45/D54 mouse model and the same screens with
  `O#D44` set and a scripted mouse.

## 7. Open questions [UNK]

1. VT640 meaning of ESC `0`–`3` (scale factors) and of ESC `8`/`9` sent by
   music notation; whether a real VT640 enters graphics on FS from text.
2. D40Q mouse-port electrical details: D45 bits other than 1, baud default,
   whether a D45 write clears receive-ready, D54 read when nothing pends.
3. Exact VT640 text/graphics registration (SYN-5.3's 7.5 × 20 cell and
   8-pixel left margin are taken as truth here) and the alpha-mode cell
   origin (lower-left assumed) and font.
4. Line-type dash lengths and the type-5 user pattern.
5. Whether to keep the Mac configuration instead and implement the
   Termulator/MG600 dialect (needed only for AEE).
6. Whether WINSTALL-style auto-setting of `O#D44` from D57's D40Q bit should
   be mirrored, i.e. does any shipped W0 already have `O#D44` set.
