# Digital sample-to-memory (M18): native routines 64–76

Scope: what SYN-5.3 does with the Synclavier³ interpreter's "digital STM"
input, and how the simulator (`sim/devices/digstm.py`) and the core
(`hdl/core/dig_stm.sv`, `hdl/able_cpu.sv`) provide it with an audio file on
the SD card as the digital input. Source paths are relative to the NED
Release 5.3 tree (`out/ned53/`); `syn53.dis` is the SYN-5.3 disassembly made
with `tools/able_disasm.py`.

Tags: **[OBS]** seen in source or binary, **[INF]** inference with the
reasoning, **[CHOICE]** model choice where the source is silent.

## 1. Calling convention

* [OBS] `-XPL/INTRPRTR` declares the routines as `Native (n) name (args)`;
  the XPL compiler (`pass1.cpp`, `s_native_dcl`) makes them RTP-located
  procedures. In the binary a call is `PCI TO RTNV` followed by n as a data
  word (octal 100–114 for 64–76; routines below 32 use `IM(n) TO RTNV`),
  arguments loaded into R0, R1, R2 first, the result taken from R0 after:

  ```
  000540  PCI  TO R0 ; DATA 74517      R0 = 0
  000544  MR5  TO LOA1                  R1 = stm.record.stereo
  000545  IM(0) TO LOA2 ...             (psmwrite(base, sec#, 0) set up and called)
  000552  PCI  TO RTNV ; DATA 104       interp_dig_stm_do_import()
  000554  PCI  TO RTNV ; DATA 105       interp_dig_stm_lmax()
  000556  PCI  TO R4 ; DATA 74523
  000560  R0   TO MR4                   smax = R0
  ```
  (`syn53.dis` 524596–524664: the record loop, `STRECSOU:500-509`); the
  latch call loads R0 = 0, R1 = stereo, R2 = rate and tests R0 after
  (`syn53.dis` ~521895–521915, `STRECSOA:60`).
* [OBS] RTNV is a relative transfer *never* (`instruction-set.md`): on the
  instrument the call does nothing and the literal is skipped.
* The model traps RTNV with a literal of 64–76 only, when D57 bit 0x4000 is
  set (sim: `cpu.native`, set by `boot_from_w0(dig_stm=...)`; core: `nat_en`
  = D57 bit 14). Every other routine number stays a no-op. The call takes
  no simulated time (sim: inside the instruction; core: the CPU waits in
  EXEC with `nat_req` until the handler's `nat_ack`).
* [CHOICE] Routines with a result (65, 66, 69, 70, 72, 74, 76) write R0;
  the others leave every register as it was.

## 2. When SYN-5.3 uses it

* [OBS] `D57_DIG_STM_EXISTS = 0x4000`, `D51_D57_EXISTS = 0x8000`,
  `D57_INTERPRETER = 0x8000` (`Code/Includes/Able Interpreter/AbleInterpreter.h`).
* [OBS] The record panel offers the digital device only with D51 bit 0x8000
  and D57 bit 0x4000 (`STDRSOUD:337-353`, `STDRSOUE:566`, `STDRSOUF:207-209`);
  with no STM hardware in bin 0 (`polyadcs(0) = 0`) and the digital input
  present, selecting STM gives the digital device at once (`STDRSOUD:346-350`).
  Every Model D system here has D51 bit 0x8000 (`sim/system.py`); the model
  sets D57 bit 0x4000 only. D57 bit 0x8000 (interpreter) stays clear, so
  SYN-5.3 keeps its hardware paths everywhere else.
* [OBS] Mode cycles with SPACE on the Mode field: D66 → STM mono → STM
  stereo → digital mono → digital stereo (`STDRSOUD:313-378`). The record
  rate is kHz × 10 (`stm.record.rate`; typed digital rates must be
  400–505, `STDRSOUD:400`; displayed e.g. "44.1 kHz").

## 3. The routines

| n | Name | Args → result | Model |
|---|---|---|---|
| 64 | `start_dig_stm` | — | frames start arriving: each instruction's time adds ns × rate to an accumulator, one frame per 10 000 000 (rate in 100 Hz units) [INF from the record loop's polling]; [CHOICE] the source rewinds to its first frame, so RECORD captures the file from its start |
| 65 | `dig_stm_samples` | → frames arrived − frames taken, 0..32767 | [INF] frames, not words: compared with 256 for mono and stereo alike ("256 samples (512 if stereo)", `STRECSOU:483`) |
| 66 | `dig_stm_underflowed` | → 1 / 0 | [CHOICE] 1 if an import or toss since the last start found fewer than 256 frames; a file loses nothing, and SYN-5.3 imports only after 65 says 256 are there |
| 67 | `stop_dig_stm` | — | frames stop arriving |
| 68 | `dig_stm_do_import` | — | [OBS] called right after `psmwrite(base, sec#, 0)` (`STRECSOU:506-507`): 256 frames as D157 writes through the poly interface, exactly as the CPU's own writes (FC 18, address counter); 256 words mono, 512 stereo, left/right interleaved ([OBS] `sec# = sec# + 1 + stereo` per import, "always 1 sector per channel", `STRECSOU:547,632`) |
| 69, 70 | `dig_stm_lmax`, `rmax` | → max \|sample\| per channel of the last import/toss | [INF] unsigned magnitude (|−32768| = 32768): plotted as `shr(max, 9)` "0 to 64" (`STRECSOU:359`) and compared with `STM.THRESHOLD` using `ige`; rmax = 0 when mono |
| 71 | `dig_stm_toss_data` | — | as 68 without the writes (level check before recording) |
| 72 | `latch_dig_stm` | (0, stereo, rate) → 0 = ok | R0 = 1 without a source ("Digital STM is not installed or is in use by another application", `STRECSOA:61`); stereo = R1 bit 0; rate setting = R2 if 1–1023 |
| 73 | `release_dig_stm` | — | frames stop |
| 74 | `get_dig_stm_rate` | → rate setting (kHz × 10) | [OBS] copied into `stm.record.rate` (`STDRSOUD:372-375`, `STDRSOUF:179-185`); starts as the source's rate (480 without one) |
| 75 | `set_dig_stm_rate` | (rate) | [CHOICE] rate setting = R0 if 1–1023; frames then arrive at that rate (no resampling) |
| 76 | `get_dig_stm_chan` | → 0 | [CHOICE] no channel choice; SYN-5.3 only compares it for changes |

Channels [CHOICE]: a stereo source recorded mono gives its left channel; a
mono source recorded stereo the same word on both. Frames after the end of
the source are 0 (the input keeps running, as a digital input does when the
player stops); with Trigger on, SYN-5.3 trims trailing silence itself
(`STRECSOU:SIM3`).

Mounting another source (core: S5) takes effect at the next call: frames up
to then count at the old rate, then the rate setting becomes the new
source's (`DigitalStm.mount`; the core reads the header at the first call
after reset or a mount, while the CPU waits anyway).

## 4. Source file (`tools/stm_source.py`)

512-byte header block, big-endian words: 0–3 `SYNCSTM1`, 4 version 1,
5 channels (1, 2), 6 rate in 100 Hz units, 7–8 frames (high word first),
9–10 the WAV's rate in Hz. Samples from block 1 as big-endian 16-bit words,
interleaved when stereo, zero-padded to a whole block; at most 65535 data
blocks (16-bit block numbers in the core: 5.8 min mono, 2.9 min stereo at
48 kHz). WAV input: PCM 8/16/24/32-bit, 1 or 2 channels; deeper samples
keep their top 16 bits [CHOICE: no dither].

## 5. Core

* `able_cpu.sv`: `nat_req` = EXEC of destination 334 (RTNV) with a literal
  of 100–114 and `nat_en`; R0 ← `nat_result` with `nat_ack` + `nat_wr`.
* `dig_stm.sv` (in `synclavier_core.sv`): the routines above; the frame
  accumulator counts the CPU's `tick`/`tick_ns` (simulated time, not the
  voice clock), so it matches the Python model exactly; reads source words
  from SD drive 5 through `sd_floppy` (32-block lines with the next line
  read in the background, as for the SCSI disks; the port is shared with
  the SCSI host and the floppy controller, one word at a time when neither
  has a request open); writes D157 into `dev_poly`'s register port while
  the CPU waits, so the words take the CPU's write path (FC, address
  counter, DDR3).
* D57 bit 0x4000: from the state image (`tools/w0_image.py --dig-stm`) or
  the OSD (Hardware page, "Digital STM input (S5)", `status[21]`), taken at
  reset.
* Cost: a 24-bit accumulator, two 32-bit counters and a small state machine;
  no block RAM.

## 6. Checks

* `tests/sim/test_digstm.py`: the RTNV trap (64–76 only), frame timing,
  imports through D157 (mono/stereo, past the end, maxes, underflow, toss),
  channel mixing, no source, `stm_source.py` WAV conversion; with
  `SYNCLAVIER_W0`, SYN-5.3 (VT640) records a 0.8 s stereo 44.1 kHz source
  on its STM screen and the new sound file in poly memory holds every frame
  bit for bit, its header saying stereo, 44.1 kHz.
* `tests/hdl/test_board.py test_dig_stm`: `dig_stm.sv` against the model
  (3 seeds, ~16 000 calls each: results, every D157 write, frame timing
  with random rates, stereo flags, early imports, remounts, no source).
* Board lockstep: `sim/lockstep.py w0boot ... --poly --vpk --fm-voices 8
  --vt640 --mouse --dig-stm SRC.STM --instructions 22000000` (SYN-5.3: L, C,
  I, level check, Return records 1 s of mono 48 kHz, Return stops; sound
  file set up by 18.8 s) against `check --top board --state
  W0-53-FM8-VT640-DSTM.SST --w0 W0-53.IMG --dig-stm SRC.STM`.
