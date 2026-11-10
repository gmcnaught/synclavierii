# SMPTE reader (D70 subsystem 8) from MIDI Time Code — M20

Scope: how SYN-5.3 (Release 5.3, Model D) reads time code, why it cannot
chase MIDI Time Code (MTC) through the MIDI subsystem card, and the model
that lets it chase MTC on the MiSTer: the NED SMPTE reader, fed from the
MTC that arrives on MIDI in (MidiLink). Files: `sim/devices/smpte.py`,
`hdl/dev/dev_smpte.sv`, `tests/sim/test_smpte.py`, `hdl/sim/dev_smpte_tb.sv`.
Source paths are relative to the NED Release 5.3 tree (`out/ned53/`).

Tags as in [`d70-midi-subsystem.md`](d70-midi-subsystem.md): **[OBS]**
seen in source or in the simulator, **[INF]** inferred, **[CHOICE]** model
choice, **[UNK]** not determined.

## 1. SYN-5.3 does not chase MTC through the MIDI card

* [OBS] `SCAN.MIDI` takes `F1` as system common state 8 with `CHANNEL=1`;
  state 8 handles only `F2` (song position, used in `EXT.CLOCK.MODE=3`)
  and `F3` (song select); `F1` falls into "EITHER TUNE REQUEST OR
  UNDEFINED", which is ignored (`05-BUTT/142-MIDI:1141-1168`). The
  quarter-frame data byte is then dropped (`MIDI.STATE=NULL.STATE`).
* [OBS] The full-frame SysEx is only stored for echo or recording
  (`SAVE.SYSEX.BYTE`, `142-MIDI:802-822`); nothing parses it.
* [OBS] MIDI sync input is MIDI clock: `SYNC.TO.MIDI` takes `F8` clock,
  `FA` start, `FB` continue, `FC` stop (`142-MIDI:687-728`), with `F2` song
  position, in `EXT.CLOCK.MODE` 3 (input jack) or 4 (aux jack). Every MTC
  routine in the source is output: `PREP.FOR.MTC.OUTPUT`, `BROADCAST.MTC`,
  the full-frame sender (`142MIDIA:835-979`) and the quarter-frame sender
  (`10-INT/144-TIM2:827-876`).
* [OBS] `hdl/core/midi_card_feed.sv` drops system common and SysEx; passing
  `F1` through would not change the above.
* [OBS, simulator] `tests/sim/test_smpte.py` `test_syn53_chases_mtc`: with
  MIDI IN sync on (hold MIDI, press EXT twice: the VPK shows "MIDI IN
  Sync") and 0.5 s of quarter frames put straight into the card's input
  FIFO, SYN-5.3 reads them all and the sequencer's play time stays 0.

Time code reaches the sequencer only through the SMPTE reader (`SMPTE.SCAN`
→ `TIME.BASE.MODE` 2/3/4). [INF] Synclavier³ chases MTC the same way: its
interpreter answers SYN-5.3's SMPTE reader accesses from MTC. The source
has interpreter-only paths in `SMPTE.SCAN` ("Handle coasting and underrun
errors when using interpreter", `144-TIM1:901-937`), `SMPTE.STARTUP.TIME`
"switched to 100 for Sync3" (`144-TIM1:730`) and `SMPTE.COAST.MSEC`
"changed to 100 for MTC" (`08-INIT/670-SCPT:418`). So the MiSTer gets an
SMPTE reader that reads MTC.

## 2. The SMPTE reader as SYN-5.3 uses it

Devices (`SYNLITS/GLOBLITS:58-64`, "THE SMPTE BOARD IS ACCESSED USING 4
DEVICE ADDRESSES"), shared with the MIDI card: [OBS]

| Device | Write | Read |
|---|---|---|
| D70 | 8 = `SMPTE.SUBSYS` ("WRITE 8 TO RESET") | low byte 8 if the reader is there (`(READ(D70)&255)=8`); bit 8 (256) = data available |
| D71 | opcodes: frame mode `SMPTE.FRAME.CODES` = "220" (30, also drop frame and 29.97), "221" (25), "222" (24); then "200" "SELECT ERROR CORRECTION MODE" (`03-PRIM/143-SIO:86-120`) | status (upper byte), bit 0–79 within the frame (lower byte) |
| D72 | — | seconds (upper), frames (lower) |
| D73 | — | hours (upper), minutes (lower); "READ OF D73 TRIGGERS NEW INFO" |

Status bits (`144-TIM1:882-889`): "200" data invalid (no sync), "040"
repeated frame (with "020"), "020" discontinuity, "010" computer
underrun, "004" drop-frame bit. Times are binary, not BCD (the display
divides by 10, `06-MAIN/325-NEW:324`). [OBS]

Who touches it [OBS]: (all gated by D51 bit 8)

* `TOGGLE.SMPTE.STATE` (`05-BUTT/171-PRF1:848-879`): with the SMPTE button
  held, press EXT (or EXT held, press SMPTE): checks D51 bit 8 and
  `(READ(D70)&255)=8`, else error 29 "SMPTE IS NOT AVAIL"; then
  `INIT.SMPTE` (frame mode opcode, 10 ms, "200", 10 ms, `SMPTE.ONOFF=1`).
* `SMPTE.SCAN` (`10-INT/144-TIM1:738-1215`), every 20 ms from the timer
  interrupt while `SMPTE.ONOFF<>0` (`144-TIM2:407-412`): select 8; if D70
  bit 8 is clear, a fabricated "no data" reading; else read D71, D72, D73.
  The first readings after `SMPTE.STARTUP.TIME` (100 ms) of valid data set
  up the rate measurement; `SMPTE.RATE` (bits in 10 s) is measured over
  0.2 s, then 5 s windows; invalid readings are coasted over for
  `SMPTE.COAST.MSEC` (100 ms) once locked, then the rate goes to 0.
* The main loop, 10 times a second (`325-NEW:236-480`): displays the time,
  and while the rate is not 0 calls `LOCK.TO.SMPTE` (`143-SIO:228-677`):
  checks the drop-frame bit against the SMPTE mode (error 35, "SIGNAL DOES
  NOT MATCH SMPTE MODE"), skips readings at bit 0 or 79 ("FIRMWARE BUG"),
  adds 80 bits ("WE DON'T NORMALLY SEE THE SMPTE FRAME UNTIL THE END OF THE
  FRAME") and the bits of one scan ("THE D70 BOARD PROVIDES SMPTE READINGS
  THAT ARE 1 BEHIND"), fast-forwards or rewinds the sequencer to 200–400 ms
  ahead and starts it when the time code gets there (`TIME.BASE.MODE` 2 →
  3 → 4). Locked, it trims `SMPTE.TRACK.RATE` from the bit count. When the
  rate drops to 0 it stops the sequencer.
* Sync mode string on the terminal's sync screen (`SYNSOU/LINKMOD/
  LINKSOU:781-791`): the same D70 probe.

SMPTE modes (`SM.MODE`, per sequence; `073-NEWW:1141-1146`,
`143-SIO:76-90`): 0 Drop Frame (29.97), 1 Non Drop (30), 2 25 Frame,
3 24 Frame, 4 NTSC 30 Fr (29.97 non-drop). Mode 0 needs the drop-frame
bit, the others need it clear. [OBS] With the empty sequence after
start-up the mode is 0, Drop Frame [OBS, simulator: the VPK shows "Drop
Frame SMPTE" when SMPTE is turned on]. Press EXT while the mode is shown
to step to the next mode (`173-PRF3:1609-1620`). The SMPTE start time
(offset; sequence time 0.000 = this time code) is set with the SMPTE
button; default 00:00:00:00.

## 3. Model (`sim/devices/smpte.py`, `hdl/dev/dev_smpte.sv`)

* [CHOICE] Present when the state image has it (device 3 index 17,
  `tools/w0_image.py --smpte`) or the OSD item is on; needs the MIDI card
  (D51 bit 8, which it shares). Without it, select 8 reads 0 as before.
* D70 read with 8 selected: 8 | 256 — always "data available" [CHOICE;
  the real reader's acquisition delay after a D73 read is UNK].
* D71 writes are accepted and ignored [CHOICE]: the frame rate comes from
  the time code itself.
* A reading is latched when D73 is read and returned by the next scan's
  D71–D73 reads (the "1 BEHIND" above) [INF]. It holds: status "200" when
  not valid, "004" when the time code is 29.97 drop frame (MTC rate code
  2); the bit; the time of the last complete frame (the frame before the
  one the bit counts in) [INF from the two comments in `LOCK.TO.SMPTE`].
* MTC decoding: every byte from MIDI in (`receive`; on the core the UART's
  raw bytes, not the card's filtered feed). Quarter frames `F1 0nnn dddd`:
  eight in order (pieces 0–7) give the time T0 of piece 0; after piece 7
  the reader stands at frame T0 + 1, quarter 3 (piece n is sent at T0 +
  n/4 frames); each further piece in order moves it a quarter frame (20
  bits), counting frames at the time code's rate (24, 25, 30 drop frame,
  30), drop frame skipping frames 0 and 1 except every tenth minute.
  Full frame `F0 7F id 01 01 hh mm ss ff F7`: located there (shown), not
  valid. Not valid also before the first eight pieces, after a piece out
  of order (until eight in order again), and when no quarter frame has
  come for 50 ms (`LIMIT_NS`) [CHOICE: the longest quarter-frame period is
  10.4 ms at 24 fps]. Real-time bytes anywhere are ignored; another status
  byte ends a cut-short message.
* Between quarter frames the bit advances 20 per measured quarter-frame
  period (the time between the last two), in simulated time, at most to
  the quarter's last bit: per tick, `acc += 20 x tick_ns`, and when `acc`
  reaches the period one more bit (up to 19). Python and HDL run the same
  integer steps, so lockstep reads match.
* Not modelled: LTC input (the MiSTer has no audio input for it), the
  repeated-frame and underrun status, user bits, reverse play (pieces
  backwards: not valid).

HDL cost: about 250 flip-flops (time counters, the latched reading, the
current and previous frame, the eight nibbles) and no block RAM.

## 4. Results

Simulator (`tests/sim/test_smpte.py`, W0-53.IMG, VPK, MIDI card with the
reader): SMPTE on at 11 s; 29.97 drop-frame MTC from 00:00:05:00. Sequence
time = SYN-5.3's play time word (`0o53712`, found by behaviour: 0 until
lock, then 1 ms per ms) − `ZERO.TIME` (50, `GLOBLITS:123`, "PLAY.TIME.LSB
OF SCRIPT=0.000"); wanted = the sender's position in ms (80 bits a frame at
SYN-5.3's 2.3976 bits/ms). The lockstep scenario below (`w0_smpte_actions`):

| Simulated time | Incoming MTC | Wanted (ms) | Sequence (ms) | VPK lower line |
|---|---|---|---|---|
| 11.75 s | 00:00:05:07 | 5247 | (not started) | `00:00:05:03    1` |
| 12.00 s | 00:00:05:14 | 5497 | 5785 (located ahead, waiting) | `00:00:05:12   12` |
| 12.50 s | 00:00:05:29 | 5998 | 6000 | `00:00:05:25   13` |
| 13.50 s | 00:00:06:29 | 6999 | 7000 | `00:00:06:26   15` |
| 14.50 s | 00:00:07:29 | 7991 | 8000 | `00:00:07:25   17` |
| 15.00 s | stopped at 14.5 s | — | 8212 (stopped) | `00:00:07:28   17` |
| 15.75 s | 00:00:20:16 (from 15.2 s) | 20562 | 20881 (located ahead) | `00:00:20:12   42` |
| 16.25 s | 00:00:21:01 | 21063 | 21065 | `00:00:20:27   43` |
| 17.00 s | 00:00:21:23 | 21813 | 21815 | `00:00:21:19   44` |

Locked, the sequence follows within 0–10 ms (the wanted column is to the
quarter frame); it locks 0.5–0.6 s after the time code starts and stops
about 100 ms (the coast time) after the time code stops. The right-hand
number on the VPK is [INF] the beat number (two a second: 120 bpm).

`hdl/sim/dev_smpte_tb.sv` (`tests/hdl/test_board.py test_dev_smpte`):
dev_smpte against SmpteReader for three seeds (~12,000 reads each): every
rate, minute 9→10 and 39→40 in drop frame, a day's wrap, jittered and very
short quarter-frame periods, full frames, other SysEx, `F1` cut short,
real-time bytes, pieces out of order, stops past the time-out, other
selects, a tick in the same clock as a byte. 8 seeded faults caught.

Board lockstep: see [`../hdl.md`](../hdl.md) (M20 row).

## 5. Open questions [UNK]

1. The real reader's bit numbering and data-available timing (the "bit 0,
   bit 79 firmware bug" suggests the counter's edges are special).
2. What the D71 opcodes do on the real board (frame mode, error
   correction), and the status bits "040"/"020"/"010" in practice.
3. Whether Synclavier³'s interpreter reports the reading the same way
   (one scan behind, the previous frame's time).
