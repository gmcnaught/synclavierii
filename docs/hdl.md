# HDL (`hdl/`): the FPGA core

M4 builds the core in SystemVerilog. Status: the **ABLE Model B CPU**
(`hdl/able_cpu.sv`, M4.2) runs in **lockstep** with the Python simulator
(M4.3) on random programs and on Release L's MONITOR and ORK-LM. The
**system** (`hdl/able_system.sv`) adds every device Release L uses: D3,
D4567, D50/D51, D60–D63, the D100 floppy controller, the D130/D131
keyboard and panel, and the D160–D165 FM interface (registers,
interpolators, wave memory). They agree with the Python devices value for
value and nanosecond for nanosecond of simulated time, through MONITOR's
boot and ORK-LM recalling a timbre and playing a note. The voice engine
(audio) is next.

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

**Time.** As `sim/cpu.py`: an instruction costs 333 ns per bus transfer
(fetch; source unless immediate; destination unless a transfer not
taken), and a read the device holds (`io_hold`, Python's `BUS_WAIT`)
costs 333 ns per clock held. Devices count this simulated time, not
clocks, so they behave exactly as the Python devices. TICK comes before
END so that the interrupt check sees the devices after the instruction's
time, as Python ticks the bus before its check. On the board a throttle
will hold the CPU to real time at this rate (risk R3).

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
python3 -m sim.lockstep ork-lm-note IMAGE.simg out/note.trace --instructions 5000000
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
floppy and keyboard/FM test programs on the system top, and MONITOR's boot on both tops when
`SYNCLAVIER_RELEASE_L` is set; it is skipped without Verilator. CI
installs Verilator.

## Next (M4)

| # | Task | Status |
|---|---|---|
| 4.1 | Framework: plain MiSTer template vs JTFRAME (decision D4) | open |
| 4.4 | Memory: internal in BRAM; external (D60–D63) in SDRAM/DDR | HDL done, lockstep-checked; SDRAM controller open |
| 4.5 | Terminal (D50/D51) | device done, lockstep-checked; host side (character display or UART) open |
| — | D3, D4567 | done, lockstep-checked |
| 4.6 | Disk images from SD (D100 floppy) | controller done, lockstep-checked; loading images from SD into the floppy RAM open |
| — | Synthesis and timing (Quartus) | needs Quartus (not installed here) |
| M5 | D130/D131, D160–D165 devices | done, lockstep-checked; voice engine (audio) next |
