# HDL (`hdl/`): the FPGA core

M4 builds the core in SystemVerilog. Status: the **ABLE Model B CPU**
(`hdl/able_cpu.sv`, M4.2) runs in **lockstep** with the Python simulator
(M4.3) on random programs and on Release L's MONITOR and ORK-LM. The
**system** (`hdl/able_system.sv`) adds every device Release L uses: D3,
D4567, D50/D51, D60–D63, the D100 floppy controller, the D130/D131
keyboard and panel, and the D160–D165 FM interface (registers,
interpolators, wave memory). They agree with the Python devices value for
value and nanosecond for nanosecond of simulated time, through MONITOR's
boot and ORK-LM recalling a timbre and playing a note. The **voice engine**
(`hdl/dev/fm_voices.sv`) produces the same integer audio samples as
`sim/voice.py`, sample for sample. The **MiSTer core**
(`hdl/core/`, `mister/`, Template_MiSTer: decision D4) boots Release L
from an F0 floppy image in simulation from power-on and matches the
Python run through `CATALOG`; the Quartus build runs in CI
(`.github/workflows/build-rbf.yml`).

## CPU (`hdl/able_cpu.sv`)

Behavioural, multi-cycle, one instruction per pass through:

| State | Does | Cycles |
|---|---|---|
| FETCH | memory address = PC | 1 |
| DECODE | instruction word from memory; PC + 1; immediate/register source (with post-increment); memory address for a memory source | 1 |
| SRCMEM / SRCIO | memory source data; or I/O read held until SYN (`io_ack`); or PSW read | 1 / 1 + wait |
| EXEC | destination: ALU, test, shift, register, transfer, memory write, I/O write (held until SYN), PCW | 1 + wait |
| TICK | `tick` strobe: devices advance by the instruction's time | 1 |
| END | `HALT` request; interrupt entry (ION and PCS set and any request bit: ION = 0, PCS = 0) | 1 |

About 5.5 clocks per instruction (ORK-LM: 5.62).

**Real time.** `hdl/throttle.sv` holds the CPU before each fetch (and
before retrying a held read) while simulated time is ahead of real time
(`rt_enable`; 50 MHz assumed, `CLK_HZ`). It only adds wait clocks, so
lockstep runs are unchanged with it on (`check --realtime`): the voice
test program ends 74 ns and MONITOR's boot (1.04 s) 551 ns from real
time. Credit when the CPU falls behind is capped at 10 µs.

**Time.** As `sim/cpu.py`: an instruction costs 333 ns per bus transfer
(fetch; source unless immediate; destination unless a transfer not
taken), and a read the device holds (`io_hold`, Python's `BUS_WAIT`)
costs 333 ns per clock held. Devices count this simulated time, not
clocks, so they behave exactly as the Python devices. TICK comes before
END so that the interrupt check sees the devices after the instruction's
time, as Python ticks the bus before its check. On the board a throttle
holds the CPU to real time at this rate (risk R3; see Real time).

Interfaces:

* Memory: 16-bit address, synchronous read (data the cycle after the
  address), synchronous write. Fits block RAM.
* I/O bus: `io_rd`/`io_wr` with `io_dev` (000–177) are held until the
  device answers `io_ack` (SYN), `io_nosyn` (no device: the CPU halts,
  `halt_reason` 1/2, as the real machine hangs) or keeps `io_hold` (not
  ready; simulated time runs). Waiting without `io_hold` (a RAM or the
  divider being slow) costs no simulated time. Device 001 (PSW/PCW) is
  inside the CPU; `irq[15:4]` are the device request bits.
* `halt_req`: stop after the current instruction (`halt_reason` 3).
* Debug: register/flag load during reset; `regs_flat`, `flags`,
  `instr_done`/`instr_pc`/`instr_word`.
* `MODEL_C` parameter: ADC/SBB (270–277) work when 1, are no-ops when 0
  (Model B, the default, as `sim/cpu.py`). D10 and `MR12D` are M6.

The semantics are exactly `sim/cpu.py`, including its choices
([`simulator.md`](simulator.md#behaviour-choices)): C unchanged where the
manual says "undefined", `PCI` through R17 at interrupt level, IRQ sampled
at the end of the PCW-writing instruction.

## Lockstep check (`sim/lockstep.py`, `hdl/sim/`)

The Python simulator records a trace; Verilator runs the HDL CPU from the
same state and compares, instruction by instruction:

1. `record` saves the registers, flags and 64K words of memory, then for
   every completed instruction its device reads (with the value), device
   writes, PSW reads, end-of-instruction interrupt checks, and (pc, word);
   every 256 instructions a register snapshot.
2. `hdl/sim/lockstep.cpp` (with `hdl/sim/able_sim_top.sv`: CPU + memory)
   answers each HDL device read with the recorded value, requires each
   write to match, drives `irq` from the recorded PSW reads and interrupt
   checks, and compares every (pc, word) and snapshot. It stops at the
   first difference with the last 16 instructions and the HDL registers.

So the HDL CPU runs real code without HDL devices.

## System (`hdl/able_system.sv`, `hdl/dev/`)

CPU, 64K words of block RAM, and the devices ported so far; every other
device number goes out on a `dev_*` port.

| Device | Module | Notes |
|---|---|---|
| D3 real-time clock | `dev_rtc.sv` | 5 ms in simulated time; PSW bit 8 |
| D4–D7 multiply/divide | `dev_muldiv.sv` | multiply in one clock; 32/16 divide in 32 clocks (CPU waits, no simulated time); D6/D7 reads: no SYN |
| D50/D51 terminal | `dev_terminal.sv` | character time from the baud rate in simulated time; input FIFO from the host, received as eagerly as Python does; D50 read held until a character; PSW bit 6 |
| D60–D63 external memory | `dev_extmem.sv` | words in an external RAM (`xm_*` request/ack port: SDRAM on the board, an array in simulation); beyond the installed size reads 177777 |
| D130/D131 keyboard and panel | `dev_keyboard.sv` | clavier octaves (negative logic) and panel words from the host; lights; display latch on the strobe edge; unknown reads 0 or no SYN (`strict`, as the Python device) |
| D160–D163 FM interface | `dev_fm.sv` | channel/function/data registers per channel (pitch, `TIM`, function 13), 16 interpolators clocked at 192 kHz of simulated time with the closed form of `sim/fm.py` (including a prescaler left above a new divisor), D160 bit 0 = channel present / limit reached, 32 × 256-byte wave memory with per-channel address, switches, A/D, external clock. Register and wave outputs for the voice engine |
| D164/D165 control voltages | in `able_system.sv` | write-only (reads: no SYN) |
| D100–D104 floppy | `dev_floppy.sv` | FD1771-style: restore/seek/step with stepping time, index pulse from a 360 rpm phase, single-sector read/write after 50 µs, force interrupt, record not found, write protect; other commands and D104 reads: no SYN. Two floppies' words in a RAM (`fd_*` port; on the board loaded into SDRAM, about 200 KB each). A sector copy between that RAM and the 512-byte buffer makes floppy accesses wait, at no simulated time |

The system lockstep top (`hdl/sim/able_sys_top.sv`, `--top system`)
compares these devices' read values, interrupt bits, held-read lengths
and the simulated time at every snapshot. Host actions (typed input, key
and button changes) are in the trace at the point Python made them. The trace carries the
external memory contents, the devices' state at the start (so a trace can
start in the middle of a run, as ORK-LM's does) and terminal input with
the held-read step at which it arrived.

```bash
python3 -m sim.lockstep random out/r.trace --instructions 3000 --seed 5
python3 -m sim.lockstep monitor IMAGE.simg out/mon.trace     # boot + CATALOG
python3 -m sim.lockstep ork-lm IMAGE.simg out/ork.trace --instructions 6000000
python3 -m sim.lockstep ork-lm-note IMAGE.simg out/note.trace --instructions 5000000 --audio
python3 -m sim.lockstep check out/mon.trace                  # CPU top (builds out/hdl-lockstep/)
python3 -m sim.lockstep check out/mon.trace --top system     # CPU + HDL devices
```

Results:

| Run | Instructions | Result |
|---|---:|---|
| 300 random programs (3,000 instructions each; random device data, half edge values; random interrupt requests) | 900,000 | agree; all 256 source and 256 destination codes executed; 1,263 interrupt entries |
| MONITOR: cold boot from `03-SYSTD`, `CATALOG` of `18-UTILS` | 1,363,060 | agree |
| ORK-LM: loader, start-up, welcome screen, main loop with RTC interrupts | 6,000,000 | agree |
| System top: MONITOR boot + `CATALOG` (typed while D50 is held) | 1,363,060 | agree, 1.043 s simulated |
| System top: ORK-LM, device state loaded mid-run | 6,000,000 | agree, 4.806 s simulated |
| System top: device test program (multiply, divide with quotients over 16 bits, external memory across sectors and past the end, terminal output, held D50 read with input, RTC and terminal interrupts, D6 read halts) | 36,934 | agree |
| System top: floppy test program (restore, seek, write a sector, read it back, record not found, write-protected drive, step in/out, index pulses, D104 read halts) | 57,577 | agree |
| System top: ORK-LM, recall `06-TIMBD` bank 0 timbre 0, hold C4 for 0.5 s: 35 sector reads, panel buttons, key, interpolator attack and release polled through D160 bit 0. No device answered from the trace | 5,000,000 | agree, 4.190 s simulated |
| System top: keyboard/FM test program (interpolator ramps polled through D160 bit 0, wave memory loads, absent channel, A/D, keys and buttons from the host, lights, display, D161 read halts) | 28,511 | agree |

The check is sensitive: each of these single changes to the HDL makes
random runs fail (8–27 of 40 seeds): SUB carry with `>` instead of `≥`,
RTL carry from bit 14, SHRA carry from the result, PCS = 0 not clearing
ION; and post-increment of the PC register without the fetch increment
(36 of 40). (Reading ION instead of ION ∧ PCS in the PSW is equivalent:
PCS = 0 always clears ION.) Device faults are caught the same way: RTC
period + 333 ns, D5 write not clearing D4, quotient high word dropped,
no sector carry on D63, no 177777 past the end, XMIT_IRQ never set,
9600-baud character time 1.000 ms instead of 1.042 ms; floppy: buffer
bytes swapped on write, index pulse 3 ms, stepping 5 ms, sector range
check off, write protect ignored, sector start 49 µs; FM: no limit
status, interpolator divisor off by one, prescaler counting 2 per clock;
panel buttons not taken from the host. (Clearing bit 0 of a written limit
survives: Release L's limits 250 and 0 are even.) Faults of 1 ns in
the character time survive: they change nothing at 333 ns resolution.

`tests/hdl/test_lockstep.py` runs 60 random programs and the device,
floppy, keyboard/FM and voice-engine (with audio) test programs on the
system top, and MONITOR's boot on both tops when
`SYNCLAVIER_RELEASE_L` is set; it is skipped without Verilator. CI
installs Verilator.

## Voice engine (`hdl/dev/fm_voices.sv`, M5)

The integer voice model of `sim/voice.py` ([`fm-voice.md`](fm-voice.md#voice-model-m32)),
driven by the D160 registers, interpolators and wave memory of `dev_fm.sv`:

* 16 oscillators at 656015360/123 Hz (5.3335 MHz) of simulated time,
  advanced in closed form at every system tick (≤ 6 oscillator ticks per
  instruction), so they are always at the current time. A pitch write
  takes effect from the write's time; the accumulator is reduced modulo
  the new divisor at its next use (Python: `acc %= divisor` on a write).
* Samples at Python's render instants, start + ⌊k × 10⁹ / 192000⌋ ns.
  When one falls inside an instruction's tick, the oscillators are
  advanced to it first, a snapshot is taken, then they go on. Envelope and
  index are the interpolators' values before or after their clock in that
  tick, by whether the clock falls at or before the sample instant.
* The 8 voices are summed from the snapshot, one wave-memory read per
  clock: s = (w − 128) × envelope × `VOL`; left += s × (256 − pan),
  right += s × pan. Output: two 40-bit sums per sample
  (`FMSynth.sample_int`). FM interface accesses wait while it mixes, so a
  wave-memory write cannot land mid-sample.
* The sine ROM is generated from `voice.SINE_ROM` (`tools/gen_sine_rom.py`
  → `hdl/dev/sine_rom.svh`), a choice until the SS2 ROMs are dumped.

`hdl/dev/audio_out.sv` turns the 192 kHz sums into 48 kHz 16-bit PCM
with the arithmetic of `render()` + `write_wav()`: mean of 4, gain ¼,
round half to even, clip; pcm = round(sum of 4 × 32767 / 2³⁵). Every
step of Python's float path is exact at these magnitudes, so the WAV
files are byte-identical.

Audio traces (`record(..., audio=True)`, `--audio`) carry the samples
Python computes at each instant (a live `FMSynth` fed from the FM log);
the bench compares every HDL sample with them.

| Run | Samples | Result |
|---|---:|---|
| ORK-LM `ork-lm-note` (timbre 0, C4 for 0.5 s: 96,238 nonzero samples) | 804,572 | identical |
| Voice test program (FM index ramp with shift 2, pan, `VOL`, loaded wave memory, pitch and octave change while sounding, release) | 21,032 (20,954 nonzero) | identical |
| 48 kHz WAV from `audio_out.sv` vs `render()` + `write_wav()`: ORK-LM C4 (201,143 frames), voice test program | — | byte-identical |

Each of these engine faults is caught: no reduction after a pitch write,
envelope taken after a clock that lands exactly on the sample instant,
shifter off by one, pan without masking the shift bits, points added
without pulses, sample period 5208 ns throughout, envelope always before
the clock.

## MiSTer core (`hdl/core/`, `hdl/board/`, `mister/`)

Framework: **Template_MiSTer** (decision D4). JTFRAME was considered and
not used: its MiSTer target ties off the HPS UART (MidiLink, needed for
MIDI input), uses the SD block interface only for one cartridge-save slot
(not two writable floppy drives), decodes the PS/2 keyboard into joystick
and coin bits (the terminal needs characters), and its video, audio-mixer
and CPU modules do not apply to a text terminal, one stereo PCM source and
the ABLE CPU. No JTFRAME module is used.

`hdl/core/synclavier_core.sv` is the board-independent core; the MiSTer
top (`mister/Synclavier.sv`, module `emu`) adds hps_io, the PLL (50 MHz),
DDR3 and the video/audio outputs.

| Part | File | What it does |
|---|---|---|
| Boot loader | `hdl/core/boot_loader.sv` | Stands in for the boot ROM (not available), doing what `sim/boot.py` does: writes a fresh Python system's state to the load ports (`boot_defaults.svh`, generated by `tools/gen_boot_defaults.py`), clears wave, internal and external memory, reads F0's catalog, stages MONITOR in external memory (processor type set to Model B), puts `.LD-6`'s floppy slot at LOC.LOAD = MEM.SIZ − 1024 and starts its ECOPY entry. Messages go to the screen. |
| Floppies | `hdl/core/sd_floppy.sv` | F0/F1 images on hps_io's SD block interface (`S0`/`S1`): logical sector n = block n, words big-endian (`tools/ned_disk.py --floppy`). One sector buffered; a miss reads it; writing a sector's last word writes it back. Waiting costs no simulated time. |
| External memory | `hdl/board/ddram_word.sv` | D60–D63's 1024 sectors (512 KB) in DDR3 from 0x30000000, one 16-bit word per Avalon transfer. |
| Terminal display | `hdl/core/term_display.sv` | D50 output as 80 × 24 text in a 640 × 480 picture (25 MHz pixels from 50 MHz, 59.5 Hz), public-domain 8 × 8 font (`third_party/font8x8`, rows doubled), CR/LF/BS/HT/FF, VT100-style pending wrap, scrolling, blinking cursor; green, amber or white. |
| Keyboard | `hdl/core/ps2_ascii.sv` | hps_io `ps2_key` → ASCII (US layout, Shift, Caps Lock, Ctrl); Backspace sends BS, which MONITOR takes as delete (`MONCAT/04-IOMOD`). |
| MIDI | `hdl/core/midi_in.sv` | MIDI in on the UART (MidiLink, `UART31250,MIDI`) to the D130/D131 host port. Channels 1–15: notes 36–96 are the ORK's 61 keys (others moved by octaves). Channel 16: note n presses panel button n (physical button number, `ORK_BUTTONS`). Program change p: `bank.(p/8)` for 100 ms, then 1.5 s later `timb.(p%8)` for 100 ms. CC 120/123: all keys up. |
| Audio | core | `audio_out.sv`'s 48 kHz samples held on `AUDIO_L/R` (signed). |

OSD: F0 and F1 image slots, text colour, aspect ratio, real-time pacing
(the throttle; off runs as fast as the clock allows), reset. LED: disk
activity; slow blink when the boot failed or the CPU halted (no SYN).
Unknown devices answer no SYN and halt the CPU, as on the real machine.

### Board simulation (`hdl/sim/board_top.sv`, lockstep `--top board`)

The bench runs the core from power-on with **random contents in every
register and memory** (Verilator `--x-initial unique`, `randReset(2)`),
plays the HPS (mounts the trace's floppies, serves SD block reads and
writes with delays) and DDR3 (BUSY on some clocks, 12-clock read
latency). When the boot loader releases the CPU, internal memory,
external memory, wave memory and the registers must equal the trace's
start state (`sim/boot.py`); then the run is compared as for the system
top. At the end it prints the screen (text RAM) and captures a video
frame; `tests/hdl/test_board.py` reads the frame back with the font and
requires the same text.

| Run | Result |
|---|---|
| Power-on → boot loader (89 SD block reads, 1.5M clocks) → state equals `boot_from_image` | match |
| MONITOR boot + `CATALOG` of F1 (18-UTILS): 1,363,060 instructions, 1.043 s simulated | identical |
| Frame (640 × 480) read back with the font | same text as the screen: banner, `Ready > CATALOG`, the 7 entries, `Ready >` |
| `ps2_ascii_tb.sv`: Shift, Caps Lock, Ctrl, Backspace, keypad Enter, Delete | as expected |
| `midi_in_tb.sv`: running status, note-on velocity 0, real-time byte inside a message, octave folding, all notes off, channel-16 panel buttons, SysEx skipped, program-change timing | as expected (4 seeded faults caught) |

Each of these faults is caught: processor type left as Model C, wrong
loader entry, internal memory not fully cleared, wave memory partly
cleared, defaults cut short, SD bytes swapped, DDR3 word lane ignored,
glyph pixel off by one, LF ignored.

### Quartus build

`mister/build.sh` compiles `mister/Synclavier.qpf` with Quartus Lite 17.0
and fails on a failed compile or negative slack;
`.github/workflows/build-rbf.yml` runs it on `ubuntu-latest` in the
`raetro/quartus:17.0` image on pull requests that touch `hdl/` or
`mister/`, and uploads the RBF and reports. `mister/sys/` is Template_MiSTer's
framework (GPL-2.0, `mister/sys/LICENSE-GPL2`), copied unchanged; the
bitstream combines it with this project's MIT code.

## Next (M4)

| # | Task | Status |
|---|---|---|
| 4.1 | Framework (decision D4) | **Template_MiSTer** (`mister/`) |
| 4.4 | Memory: internal in BRAM; external (D60–D63) | done: BRAM; DDR3 (`ddram_word.sv`), checked in board simulation |
| 4.5 | Terminal (D50/D51) | done: 80 × 24 display and PS/2 keyboard, checked in board simulation |
| — | D3, D4567 | done, lockstep-checked |
| — | Real-time throttle | done (`hdl/throttle.sv`), checked in lockstep |
| 4.6 | Disk images from SD (D100 floppy) | done: F0/F1 images over hps_io (`sd_floppy.sv`), boot loader; checked in board simulation |
| — | Synthesis and timing (Quartus) | CI (`build-rbf.yml`); results in the PR |
| — | On MiSTer hardware: boot to `Ready >`, `CATALOG` | needs a board |
| M5 | D130/D131, D160–D165 devices; voice engine | done, lockstep-checked (audio sample for sample) |
| M5 | MIDI → clavier and panel | done (`midi_in.sv`, testbench); on hardware with MidiLink: not yet run |
| M5 | DAC/pan law, output filtering | open (needs reference recordings, M3.3) |
