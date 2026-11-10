# Software simulator (`sim/`)

Milestone M1 in [`plan.md`](plan.md). This page covers what exists so far:
**M1.1** (CPU core), **M1.2** (PSW/PCW, interrupts, INIT) and **M1.3–1.5**
(external memory, terminal, real-time clock, multiply/divide), **M1.6**
(boot of Release L `MONITOR` with the D100 floppy controller) and **M1.7**
(debug tooling and console). Release L `MONITOR` reaches `Ready >` and runs
`CATALOG`, which is milestone M1's acceptance test.

## Layout

| File | Contents |
|---|---|
| `sim/cpu.py` | `CPU`: Model B instruction execution, flags, PSW/PCW, interrupt entry, HALT, timing counters |
| `sim/decode.py` | 256-entry source and destination decode tables (checked against `tools/able_disasm.py`) |
| `sim/bus.py` | `Bus` and the `Device` base class for I/O devices 000–177 |
| `sim/devices/` | Device models: `extmem.py` (D60–D63), `terminal.py` (D50/D51), `rtc.py` (D3), `muldiv.py` (D4567), `floppy.py` (D100–D104), `synth.py` (D130/D131 original keyboard, D160–D163 FM interface and old-panel inputs, D164/D165 control voltages; see [`devices/`](devices/)), `stubs.py` (`ProbeDevice` for M2 exploration). Each file starts with its evidence. |
| `sim/system.py` | `make_system()`: a CPU with the devices attached (`floppy=True`, `synth=True` add the floppy controller and the stubs) |
| `sim/boot.py` | Boot: `MONITOR` staged in external memory, started through the `.LD-6` loader's ECOPY entry; floppies from the `.simg` in F0/F1; console CLI `python3 -m sim.boot IMAGE` |
| `sim/rtp.py` | Starts a Release L real-time program (`ORK-LM`, `ORK-LFM`) through MONITOR's RUN hand-off and the loader; logs device accesses (`python3 -m sim.rtp IMAGE --log out.csv`) (M2.1) |
| `sim/fm.py` | FM register semantics: pitch, envelope/index interpolators, `ISHC`, wave memory ([`fm-voice.md`](fm-voice.md)) |
| `sim/lockstep.py` | Records traces for checking the HDL CPU against this simulator, and runs the Verilator check ([`hdl.md`](hdl.md)) (M4.3) |
| `sim/voice.py` | Integer FM voice model: replays the D162 write log and renders stereo audio (`render`, `write_wav`; `python3 -m sim.voice LOG.csv OUT.wav`) (M3.2) |
| `sim/trace.py` | `Debugger`: instruction history, device-access log, breakpoints, stop on input wait, halt report, memory inspect (M1.7) |
| `sim/asm.py` | Small assembler in NED syntax (`SRC TO DST`, `DATA`, `IM()`, `RE(label)`), for tests and experiments |
| `tests/sim/` | `test_decode.py` (tables, assembler round trip over all 65,536 words), `test_cpu.py` (42 instruction-level tests), `test_devices.py` (17 device tests, mostly small programs written like NED's loaders and runtime), `test_floppy.py` (7), `test_synth.py` (8), `test_fm.py` (7), `test_voice.py` (8), `test_trace.py` (5), `test_boot.py` (3; boots the real MONITOR to `Ready >` and runs `CATALOG` when `SYNCLAVIER_RELEASE_L` names the image) and `test_rtp.py` (5; with the image: runs ORK-LM, checks the `.STAB-6` pointer, recalls a timbre, checks C4's pitch, renders it and checks the note's end) |

## Use

```python
from sim import CPU
from sim.asm import assemble

words, labels = assemble("""
        IM(12) TO R1        ; numbers are octal: 12 = 10
        IM(0) TO LOA0
LOOP:   R1 TO ADD0
        IM(1) TO SUB1
        RE(LOOP) TO RTNZ
DONE:   RE(DONE) TO RTRA
""")
cpu = CPU()
cpu.load(words, 0)        # PC (R17) is 0 after INIT
cpu.run(200)
print(cpu.r[0])           # 55
```

`cpu.step()` runs one instruction and returns `False` once the CPU has
halted. `cpu.halted` then holds a `Halt(reason, pc, word, device)`.
`cpu.trace`, if set, is called as `trace(cpu, pc, word)` before each
instruction.

### Devices

Subclass `sim.Device`, list its device numbers in `numbers`, and attach it
with `cpu.bus.attach(dev)`. A device implements `read(dev)`,
`write(dev, value)`, `tick(ns)` and `irq_bits()` (its PSW bits 4–15, or 0).
Returning `NO_SYN` from `read`, or `False` from `write`, means no SYN: the
CPU halts and reports the device, as the real machine hangs. Device 001
belongs to the CPU and cannot be attached.

### A full system

```python
from sim import make_system

cpu = make_system()            # D3, D4567, D50/D51, D60-D63 (256K words)
cpu.terminal.feed("CATALOG\r") # host keyboard input
...
print(cpu.terminal.text())     # everything the program printed
```

### Booting Release L

The image is not in the repository; download it yourself (see
[`release-l-image.md`](release-l-image.md)) and keep it out of git
(`*.simg` is ignored).

```bash
python3 -m sim.boot IMAGE.simg --f1 18-UTILS                       # interactive console
python3 -m sim.boot IMAGE.simg --f1 18-UTILS --input 'CATALOG\r'   # scripted
```

```
boot: MEM.SIZ=160000 LOC.LOAD=156000 config=000074 length=052512

N.E.D. ABLE Series System Monitor - 1 December 1985

Ready > CATALOG

--Name--  Type  --Name--  Type  --Name--  Type  --Name--  Type
CONFIGUR  Exec  FIND      Exec  FORMCOPY  Exec  LISTING   Exec
RECOVER   Exec  SHUFFLE   Exec  TAPECAT   Exec

Catalog contains 7 entries, 375 sectors used, 25 sectors remaining

Ready >
```

About 1.5 s from cold start to that point. The boot floppy (`--floppy`,
default `03-SYSTD`, the floppy-system disk) goes in F0; `--f1` puts another
floppy of the image in F1. Release L's configuration makes F1 the user
catalog, so without `--f1` `CATALOG` answers "No floppy disk in drive", as
the real machine would. Floppy writes stay in memory; the image file is
never changed.

At a terminal, each line you type is sent followed by Return whenever the
program waits for input; end with Ctrl-D. `--input` types the given lines
the same way (`\r` separates lines) and exits when they are used up. Other
options: `--max N` (step budget per segment), `--break OCT` (repeatable).
If the run halts, a report shows the registers, the last 32 instructions
(disassembled), the last 16 device transfers and per-device counts.

How the boot works: [`boot-and-loaders.md`](boot-and-loaders.md) §4.

### Playing notes and rendering audio

`sim.rtp` runs ORK-LM, puts the timbre floppy in F0, presses panel buttons,
holds keys, and renders what the FM voices play (M3.2):

```bash
python3 -m sim.rtp IMAGE.simg --swap-f0 06-TIMBD --buttons bank.0,timb.0 \
    --keys 36,40,43 --hold 1 --wav chord.wav --fm-log chord.csv
```

`--wav` replays every D162 write since the RTP started (so wave memory
loads are included) through `sim/voice.py` and writes 48 kHz 16-bit stereo
from the key press to the end of the run (0.5 s after release). Rendering
takes about 1 s of host time per voice-second. The CSV holds only the
writes during the panel actions, so `python3 -m sim.voice chord.csv
out.wav` renders it correctly only if the wave memories were loaded in that
window (a timbre recall does load them). What the model fixes and what it
chooses: [`fm-voice.md`](fm-voice.md#voice-model-m32).

### Debugger

```python
from sim.trace import Debugger

dbg = Debugger(cpu)                 # history_len=64, io_len=64
dbg.breakpoints.add(0o11571)
stop = dbg.run(1_000_000)           # "breakpoint", "halted" or None (budget)
stop = dbg.run(10_000_000, until_input=True)   # also "input": waiting on D50
print(dbg.report())                 # HOP-like view
print(dbg.memory(0o11556, 12, disasm=True))
dbg.detach()                        # restore full speed
```

Breakpoints are checked before the instruction is fetched; `run()` steps
over a breakpoint at the starting PC so it can resume. Each device transfer
is logged with the PC of the instruction that made it; a failed transfer is
logged as `NO SYN`. A Debugger costs about 15% of the speed (1.45 vs 1.25
million instructions per second booting MONITOR).

## Devices

| Device | Registers | Interrupt | Evidence |
|---|---|---|---|
| **D60–D63 external memory** | D60 sector (R/W, 16 bits; writing it starts at word 0); D61 word in the 256-word sector (R/W); D63 data (R/W), each access moves to the next word and carries into D60; D62 data (R/W) without the increment | — | FLPLOAD, WINLOAD, SCSILOAD copy loops; MONITOR `POLL` (D62) |
| **D50/D51 terminal** | D50 read = received character (held until one arrives), write = send character. D51 read = status: 1 XMIT_IRQ, 2 CHAR_RDY, 4 XMIT_MT, plus card-present bits 8–15 (1000 = D60, 10000 = D100A, 40000 = SCSI…). D51 write clears XMIT_IRQ; with bit 15 set, bits 8–10 choose the baud rate | PSW bit 6 (100) while CHAR_RDY or XMIT_IRQ | NED interpreter header `AbleInterpreter.h`; Model B runtime polling and interrupt code; SYSLITS baud codes |
| **D3 real-time clock** | Write = acknowledge the interrupt; read = 1 while a tick is pending, else 0 | PSW bit 8 (400) every 5 ms (200 Hz) | *Synclavier Internals* §5; SYSLITS `d03_speed`; runtime dispatch `IM(0) TO D3` |
| **D4567 multiply/divide** | Writing D5 loads D5 **and clears D4**; writing D4 loads D4. Multiply-add: D6 write → D4:D5 = D5·D6 + D4. Divide: D7 write → D4:D5 / D7, quotient to D5, remainder to D4 (a quotient over 16 bits adds its high bits into D4). Unsigned. Only D4/D5 readable | — | SCSILOAD; NED's C emulation `XPL.h` ("write to d5 cleared d4"); ORK-LM divides with only D5 and D7 |
| **D100–D104 floppy (D100)** | FD1771-style. D100 write = command (restore 0–3, seek 20+rate, step/in/out 40–77, read sector 210/214, write sector 250, force interrupt 320), read = status (1 busy, 2 DRQ or index, 4 track 0 or lost data, 20 RNF/seek error, 100 protect, 200 not ready). D101 track, D102 sector, D103 data (first byte = low half of the word). D104 write = drive + 2·side + … | — | FLPLOAD; RTP `DISKREAD`/`DISKSEEK`; DEVUTIL `d100_disk_check` |
| **D130/D131 original keyboard** | Clavier scan, panel buttons/lights, display; host `press_key(12–72)`, `press_button(0–127)`. Map: [`devices/d130-original-keyboard.md`](devices/d130-original-keyboard.md) | — | NED `076-OLDI`; MONITOR; ORK-LM traffic |
| **D160–D163 FM interface** | Channel / function / 8-bit data writes (logged per channel and function); D160 read = channel-exists, external clock, switches; D163 = A/D and clock out. `voices` (default 8). Map: [`devices/d160-fm-interface.md`](devices/d160-fm-interface.md) | — | NED `FCODLITS`, `076-OLDI`, `600-INIT`; ORK-LM traffic |
| **D164/D165 control voltages** | DAC select / value, recorded. [`devices/d164-control-voltages.md`](devices/d164-control-voltages.md) | — | NED `390-VOLT`, `144-TIM3` |
| Anything else (probe mode) | `sim.rtp` sets `strict=False`: the stubs' unknown reads return 0, and a `ProbeDevice` on `bus.fallback` answers every unclaimed device number (reads 0) and counts accesses | — | M2.1 logging |

**Unknown registers halt on purpose.** Reading D6, D7 or D104, an
unmodelled floppy command (read address, read/write track, multi-sector),
or any FM/keyboard access beyond the stubs returns no SYN, so the CPU halts
and names the device. The halt report shows where to look.

**Floppy geometry.** Each Release L floppy in the image is 404 logical
sectors. Physical addresses follow NED's `DISKSEEK`: cylinder = sector ÷
sectors-per-cylinder, side 1 if the remainder ≥ sectors-per-track, sector
numbers from 1. The media default is 5 sectors/track, single-sided, as
Release L's F0/F1 configuration says (cylinders 0–80).

Terminal characters take 10 bit times each way (1.04 ms at 9600 baud), so
programs that poll XMIT_MT or CHAR_RDY run at the real speed. With all
devices attached the simulator runs at about 1 million instructions per
second, roughly real time.

## Behaviour

Everything follows [`instruction-set.md`](instruction-set.md). In short:

* **Micro-cycle:** fetch (PC++), source READ (with any post-increment), then
  destination WRITE. Because the source side effects happen first,
  `R1I TO R1` leaves R1 unchanged, and a relative transfer with a `PCI`
  operand is relative to the word after the literal.
* **PC** is R17 when PCW.PCS = 1 and R16 when PCS = 0. Loading the active PC
  register is a jump. Register codes always name the physical register:
  `PCI` (377) reads through R17 even at interrupt level.
* **Interrupts:** IRQ is the OR of all devices' `irq_bits()`. At the end of
  an instruction, if IRQ and ION, the CPU clears ION and switches to R16. A
  handler returns by writing the PCW with PCS = 1. If the device still
  requests an interrupt, it is taken again straight after that write, so
  handlers are laid out as `RETURN: <PCW write>` followed directly by
  `ENTRY:`, and end with a jump back to `RETURN`.
* **PCW writes in NED code use negative immediates**, because PCS is bit 5
  and a positive immediate only reaches bit 4. For example `IM(-20) TO D1`
  (177760) means R17, ICS = 1, ION = 0: interrupts off.
* **Timing:** each bus transfer costs `ns_per_transfer` (default 333 ns,
  so about 1 µs for a three-transfer instruction). Immediate sources skip
  the read; failed conditional transfers skip the write. Devices are ticked
  with the elapsed time after each instruction.
* **Held reads (`BUS_WAIT`)** model the bus's asynchronous handshake. NED's
  EZBUSS documentation (read operation): the address is valid at least
  50 ns before RD; the device gates its data onto BDB0-15 when it is able
  to, waits at least 150 ns, then signals SYN and holds data and SYN until
  RD goes false. So a device may hold a read as long as it needs (the D50
  terminal for a character, the D24 SCSI host for a byte the disk has not
  delivered, `sim/devices/scsi.py` disk time), and 333 ns per transfer
  is consistent with the minimum. The model counts a held read in 333 ns
  steps (the real bus waits continuously); interrupts are taken only
  between instructions in both.
* **Disk time and seek time** (`scsi_block_ns`, `scsi_seek_ns`; state image
  device 3 indices 11 and 12; `tools/w0_image.py --disk-us 500 --seek-us
  25000`): a READ's block i arrives (i + 1) × block_ns after the command,
  plus seek_ns first when the READ does not start where the target's last
  READ or WRITE ended. SYN-5.3's driver polls D25 for REQ meanwhile, with
  interrupts running, as NED's `SCSICODE` does on the instrument. In the
  core the seek is when the SD card delivers the READ's first 16 KB line
  (`dev_scsi` asks `sd_floppy` for it at the command), so a load no
  longer stops simulated time while the SD card answers.
* **Speed:** about 1.6 million instructions per second on a current PC, so
  roughly real time for the original machine (risk R4).

### Behaviour choices

The manual leaves these open. Each choice is marked `CHOICE` in the code.

| Question | Choice | Why / how to settle |
|---|---|---|
| C after LOAD, AND, XOR, OR, LCM, BSOR (manual: "undefined") | Unchanged | Simplest. Software that relies on it is a bug; a trace check could flag reads of an undefined C later. |
| Registers and flags after INIT | Cleared | The manual only gives PC = R17 and interrupts off. |
| When an ION enable takes effect | Immediately: IRQ is sampled at the end of the PCW-writing instruction | The manual describes no delay. |
| `PCI` (377) at interrupt level | Reads through R17, not R16 | Codes name physical registers; nothing in the manual remaps them. |
| ADC/SBB destinations (270–277) on Model B | No operation (accumulator and flags unchanged); ADC/SBB work when `cpu.model = "C"` | [HYP] ORK-LM's Model C test (`IM(5) TO ADC0` must leave R0 = 0 on a Model B); see [`instruction-set.md`](instruction-set.md) §9. |
| `MR12I` destination (372) | Ordinary post-increment on Model B | Model C/D (`cpu.model`): `MR12D`, store then decrement R12. |
| PSW read side effects (ACK̅) | None | The runtime acknowledges each device explicitly (D3 write, D50 read, D51 write), so no device needs ACK̅ so far. |
| Terminal interrupt enable | Always enabled at the card; software masks with ION | NED code shows no enable bits. |
| Reading D50 with no character waiting | The read is held (the CPU repeats the instruction, no interrupts) until a character arrives | [HYP] MONITOR's input routine reads D50 without testing CHAR_RDY. |
| Writing D50 while the transmitter is busy | Character is still sent | A real UART might drop it. |
| External memory beyond the installed size | Reads 177777, writes ignored | MONITOR's `POLL` needs the D62 read-back to differ from the 0 it stored. |
| D4567 divide by zero | D5 = 177777, D4 = dividend low word | Unknown (NED's C emulation divides by zero too). |
| Processor type in MONITOR's configuration | Set to Model B at boot (`processor="B"`); the disks say Model C | Matches the simulated CPU; the loader passes it to every program. |
| D3 read value | 1 while a tick is pending, else 0 | DEVUTIL tests it as an XPL condition (bit 0). Other bits unknown. |
| D6/D7 read | Halt (no SYN) | No NED code found that reads them. |
| Floppy timing | Steps at the FD1771 rates (6/6/10/20 ms); 360 rpm with a 4 ms index pulse; 50 µs to the first DRQ; no lost data (the controller waits for the CPU) | Data rate and rotation of the real drives unknown. |
| Device timing (multiply about 2 µs, divide up to 10 µs) | Not modelled: every transfer costs the same | Add if real-time code turns out to depend on it (risk R3). |
