# D40/D41 printer port and printing from Release 5.3 (M21)

Scope: what SYN-5.3 (Release 5.3, Model D) sends to a printer on the D40Q
card's printer port, how the simulator (`sim/devices/printer.py`) and the
core (`hdl/dev/dev_printer.sv`, `hdl/core/print_capture.sv`) model it, how
the core keeps the printout (a capture file on the SD card) and how
`tools/print_render.py` turns it into pages. Paths below are relative to
the NED source tree `out/ned53/` unless they start with `sim/`, `hdl/`,
`tools/` or `docs/`.

Tags: **[OBS]** seen in source (file:line) or in the simulator running the
W0 image, **[INF]** inference with the reasoning given, **[CHOICE]** a
modelling decision, **[UNK]** not determined.

## 1. Summary

* **Ports:** D40 data, D41 status/control, interrupt through D54 bit 0
  (PSW bit 10, shared with the mouse on D54 bit 2). The D40Q's four
  ports are D40/41 printer, D42/43 voice, D44/45 mouse, D50/51 terminal
  (`SYNLITS/GLOBLITS`). [OBS]
* **Configuration:** MONITOR configuration word 17 bit `"20"` = `o#d40`
  "D40 (printer) is in system"; word 19 (`c#stype`) = printer type << 8
  | nulls (9 DECwriter III, 10 LA34, 11 Printronix, 12 Prism, 13 Diablo);
  word 20 = output redirection (`-XPL/SYSLITS:52,64,75,87-92,116-121`).
  SYN-5.3 tests only `o#d40` (`D40_PRESENT`); word 19 is read only by the
  MONITOR-level LISTING utility (`UTILCAT/LISTING:1187-1189`). [OBS grep]
* **Shipped W0:** word 17 = `"141473"` (`o#d40` clear), word 19 =
  `"026000"` (type 16, graphics 1: none of the listed types). [OBS]
* **What prints:** three commands in SYN-5.3 (§3). The graphics one, the
  Music Notation Display's screen hardcopy, is written for an IDS Paper
  Tiger / Prism (`-XPL/PLOTLIB:79` "dumps from screen to PAPER TIGER/PRISM
  series printer"; D40DOC "dumps graphics from the screen to the I.D.S."),
  so **Prism (12)** is the type the core configures. [OBS]
* **Core:** the bytes go into a capture file the user mounts in SD slot
  **S6**; `tools/print_render.py` renders it as PNG pages and a PDF.

## 2. The driver (`SYNSOU/D40MOD/D40SOU`) [OBS]

| Access | Use | Source |
|---|---|---|
| W D40 | a byte to the printer | `boot_d40`, `D40SOU:35-46` |
| W D41 = 0 | "acknowledge interrupt(s)" when nothing is left to send, or when stopped | `:43,66` |
| R D41 bit 1 | a byte has come from the printer (XON/XOFF): R D40 & 177; ^S stops, ^Q restarts | `:52-62` |
| W D54 | `d54bits` with bit 0 set (`enable_d40`) / cleared (`disable_d40`), only if `D40_PRESENT` | `:21-32` |
| WHEN D40INT | RTP `B10INT` reads D54, priority encoder → WHEN 16 + bit (bit 0 = D40INT) | `RTP/INTRO:1549-1554` |

Output is interrupt driven: `sendc` puts the byte in an 8-byte ring; if
the port is idle it writes D40 at once (`boot_d40`), otherwise the
transmit interrupt sends the next byte. With the ring full `sendc` waits,
calling `CHILL.OUT.AND.RUN.SYN` (`:105-107`). `d40_wait` waits for the
ring to empty; `disable_d40` turns the interrupt off.

D41 status bits, as D51's (`AbleInterpreter.h`): 1 transmit interrupt,
2 receive-ready, 4 transmitter empty [INF: same UART on the D40Q; SYN-5.3
only tests bit 1]. Baud: `"100000" | rate << 8` written to D41
(`SYSLITS:172-182`); SYN-5.3 never writes it [OBS grep], so the power-on
rate is the D40Q's default [UNK].

## 3. What SYN-5.3 prints [OBS]

| Where | Key | Routine | Bytes |
|---|---|---|---|
| K Music Notation Display | `H` ("Print screen with <H>", `MNOTMOD/PICSFNCS.xpl:20`) | `HARDCOPY` (`MNOTMOD/MAINFNCS.xpl:40-46`) | IDS graphics, read back from the terminal (§4) |
| G Recorder Display | `h` (`RECMOD/557REC1A:337-343`) | `SCREEN_DUMP` | text: for each 80-character screen row CR LF DC4 (`"15" "12" "24"`) then the row from the screen image in external memory; FF at the end (`D40SOU:137-161`) |
| B Sound File Directory (optical) | print command (`STORMOD/WINDOW:953`) | `Print.Directory` (`STORMOD/PRINT:63-294`) | text with page headers and FF |

Without `o#d40` both keys call `no.printer` (an error message). The Main
Menu's "<PF3> Music Printing" is a separate NED program (the MONITOR's
PLOT command) that is not on the W0 image; nothing here concerns it.

### 3.1 Screen hardcopy (`hardcopy`, `D40SOU:166-349`)

Returns at once unless `D40_PRESENT`, not an ADM terminal, and not under
the Synclavier³ interpreter ("doesnt work any more"). For a VT640: 640 ×
480 pixels read in 5-pixel groups (DQ640: 800 wide, 6; MG600/Macintosh:
1024 × 780, 4 with a different command, `ESC } 9`). Then, for each of the
69 swaths of 7 lines from the top:

1. read the 7 lines from the terminal (§4), OR each pixel into a byte
   per column: line j of the swath (0 = top) is bit j;
2. send the columns up to the last non-blank one, a data byte 3 sent
   twice; then ETX SO.

It starts with CR, ETX and ends with ETX FF, ETX STX, CR. So the
printer protocol is [INF from the bytes; IDS manual not in the source]:
ETX enters graphics; in graphics a byte is a column of 7 dots (bit 0 at
the top), ETX ETX a data byte 3, ETX SO a graphics line feed (7 dots),
ETX FF a form feed, ETX STX back to text.

**A wait corrupts the page.** The column loop reads the dot rows through
MAM/MAL (`write(mam)=trd.ptr; ... read(mdi)`, `:329-336`) and calls
`sendc` for each byte; when the ring is full `sendc` calls
`CHILL.OUT.AND.RUN.SYN` (`SYNRSOU/03-PRIM/410-TTY:35-53`), which runs
`MAIN.LOOP` and `PERFORM` without saving MAM/MAL (unlike `run.syn.loop`,
`:63`), so the row continues from another program's memory. [OBS in the
simulator: at 9600 and at 76800 baud the page is dot noise; at 20 µs a
byte it is the screen.] Hence the [CHOICE] in §5: the port is faster than
the CPU fills the ring.

## 4. VT640 read-back [OBS decoder, CHOICE reply]

`read_screen` (`D40SOU:190-286`) asks the terminal for line y (VT640
coordinates, 0 = bottom):

```
ESC " 0 ; <y> ; <groups> c          (VT640; DQ640: ESC " 0 ; y ; width C)
```

waits for the output to drain (`tty_wait`), **discards any input already
received** (`:221-226`), then decodes the reply from the terminal input:

| Byte(s) | Meaning |
|---|---|
| `$` n | n groups of 0 (n = byte & 077) |
| `%` n | n groups of all ones |
| `&` v n | n groups of value v |
| v | one group (bits 0–4: bit 0 = the group's rightmost pixel) |
| EOT (4) | end of line early |

then one trailer byte. The real VT640's reply is not in the source; the
model's (`tools/vt100.py readback_reply`, `tek_plane.sv`) is: runs of
equal groups (at most 63), 0 → `$` n, 037 → `%` n, others 3 or more → `&`
v n, else single bytes; values and counts sent as `0100 | x` (printable,
never one of `$ % &`, EOT, XON/XOFF or ESC, which SYN-5.3's input
interrupt treats specially, `TTYMOD/TTYSOU:126-393`); then CR. The reply
arrives 2 ms of simulated time after the command (`sim/boot.py
READBACK_NS`), after SYN-5.3 has flushed its input. [CHOICE]

The VT640's text (the VT100 side) is not in the graphics plane and is not
printed: the Music Notation Display's instruction box is text, so the page
shows the staves, the menu frame and the status box (drawn in graphics),
not the instructions.

## 5. Model (`sim/devices/printer.py`, `hdl/dev/dev_printer.sv`)

| Access | Behaviour |
|---|---|
| W D40 | byte out (Python `Printer.out`; HDL `tx_valid`/`tx_data`); transmitter busy one character time, then the transmit interrupt |
| R D40 | 0 (the printer never sends) |
| R D41 | 4 if the transmitter is empty, 1 if the transmit interrupt is set |
| W D41 | clears the transmit interrupt; bit 15 sets the baud rate from bits 10–8 |
| W D54 | enable: bit 0 (the mouse keeps bit 2; both see the write) |
| R D54 | bit 0 = enabled and transmit interrupt (ORed with the mouse's bit 2) |
| PSW bit 10 | while D54 bit 0 is pending |

[CHOICE] Until a baud rate is written (SYN-5.3 never does) a byte takes
**10 µs** (`FAST_NS`), faster than any D40Q rate, so SYN-5.3's ring never
fills and the hardcopy is right (§3.1). A baud write gives the real rate
(10 bits a character), as D51. The transmitter's timing is
`dev_terminal`'s.

Configuration: `sim/boot.py set_printer` (word 17 | `"20"`, word 19 =
type << 8); `boot_from_w0(printer="prism")`; `tools/w0_image.py
--printer [TYPE]` (`W0-53-…-PRN.SST`, state image device 3 index 18 = 1);
the OSD's Hardware page item "Printer (D40)" = On (`status[29]`) does the
same at load on any W0 state image: the boot loader ORs `o#d40` into the
staged MONITOR's word 17 and writes `"006000"` (Prism) to word 19
(`boot_loader.sv`, header word 35 locates them).

## 6. Capture file (`hdl/core/print_capture.sv`, slot S6)

512-byte blocks. Block 0: bytes 0–7 `SYNCPRNT`, 8–9 version 1, 10–13 the
byte count (big-endian), the rest 0. The bytes from block 1 on. At a mount
the core reads the header: a capture file is appended to (its partly
filled last block is read back first), any other file starts empty. A
full block is written as soon as it fills (a 1 KB buffer, two halves);
0.25 s after the last byte the partly filled block and then the header
are written and the OSD shows "Printout saved in S6". Bytes with no file
(or a read-only one) are lost ("Printer: no file in S6 (lost)"); bytes
past the end of the file too ("Printer: S6 file is full"). An `N` MB file
holds `N` MB − 512 bytes; the music notation page is about 15–20 KB, a
screen dump 2 KB.

`tools/print_render.py --blank FILE --mb 4` makes an empty one;
`tools/print_render.py FILE page.png --pdf page.pdf` renders it: text at
10.5 characters per inch and 6 lines per inch (the core's 8 × 8 font),
graphics at 84 dots per inch both ways, on 8.5 × 11 inch pages, a new page
at each form feed.

## 7. Verification

| Check | Result |
|---|---|
| `tests/sim/test_printer.py`: registers, interrupt, D54 shared with the mouse, `set_printer`, the read-back reply for every line of a drawn plane decoded as `read_screen` does, a transcription of `hardcopy` rendered by `print_render` = the plane pixel for pixel, text pages, PNG/PDF, capture header | pass |
| same, with `SYNCLAVIER_W0`: SYN-5.3 G, h → 24 rows of 80 characters, FF; VT640, K, H → the bytes equal the transcription of `hardcopy` applied to the screen as it was when the hardcopy began | pass |
| `print_capture_tb.sv` (`tests/hdl/test_board.py test_print_capture`): `dev_printer` + `print_capture` against `Printer` for 3,800 bytes: registers, interrupt; file contents and header after flush; re-mount appends; past the end; foreign file; no file; OSD notes | pass (a corrupted expectation is caught) |
| `term_display_tb.sv +rbout` (`test_term_display_readback`): `tek_plane`'s replies for 18 read-back commands = `tools/vt100.py`'s | pass |
| Board lockstep, SYN-5.3 with the printer: `w0boot --poly --vpk --printer --type Gh`, 19.6M instructions; `W0-53-FM8-PRN.SST`, and the default `W0-53-FM8.SST` with OSD printer | identical; the S6 capture = Python's 1,993 bytes |

In the board bench the core does not answer read-back requests itself
(`readback_en` = 0): a trace carries Python's replies as terminal input.

## 8. Open [UNK]

* The real VT640's read-back reply format and timing (only SYN-5.3's
  decoder is known).
* The D40Q's power-on baud rate; whether NED's own printers kept up with
  SYN-5.3's hardcopy (§3.1 suggests this 2021 build was not used with a
  slow printer).
* MG600/Macintosh read-back (`ESC } 9`): not modelled; the hardcopy needs
  the VT640 configuration (`--vt640`).
* LISTING's use of printer types (MONITOR utilities print through their
  own drivers): not exercised.
