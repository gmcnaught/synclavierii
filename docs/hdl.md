# HDL (`hdl/`): the FPGA core

M4 builds the core in SystemVerilog. Status: the **ABLE Model B CPU**
(`hdl/able_cpu.sv`, M4.2) runs in **lockstep** with the Python simulator
(M4.3) on random programs and on Release L's MONITOR and ORK-LM.

## CPU (`hdl/able_cpu.sv`)

Behavioural, multi-cycle, one instruction per pass through:

| State | Does | Cycles |
|---|---|---|
| FETCH | memory address = PC | 1 |
| DECODE | instruction word from memory; PC + 1; immediate/register source (with post-increment); memory address for a memory source | 1 |
| SRCMEM / SRCIO | memory source data; or I/O read held until SYN (`io_ack`); or PSW read | 1 / 1 + wait |
| EXEC | destination: ALU, test, shift, register, transfer, memory write, I/O write (held until SYN), PCW | 1 + wait |
| END | `HALT` request; interrupt entry (ION and PCS set and any request bit: ION = 0, PCS = 0) | 1 |

About 4.5 clocks per instruction (random code: 4.50, ORK-LM: 4.46). The
real Model B takes about 1 µs (plan §3); the core will need a throttle to
keep real-time code on time (risk R3).

Interfaces:

* Memory: 16-bit address, synchronous read (data the cycle after the
  address), synchronous write. Fits block RAM.
* I/O bus: `io_rd`/`io_wr` with `io_dev` (000–177) are held until the
  device answers `io_ack` (SYN) or `io_nosyn` (no device: the CPU halts,
  `halt_reason` 1/2, as the real machine hangs). Device 001 (PSW/PCW) is
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

So the HDL CPU runs real code without HDL devices; the devices come later
and get their own checks.

```bash
python3 -m sim.lockstep random out/r.trace --instructions 3000 --seed 5
python3 -m sim.lockstep monitor IMAGE.simg out/mon.trace     # boot + CATALOG
python3 -m sim.lockstep ork-lm IMAGE.simg out/ork.trace --instructions 6000000
python3 -m sim.lockstep check out/mon.trace                  # builds out/hdl-lockstep/ first
```

Results:

| Run | Instructions | Result |
|---|---:|---|
| 300 random programs (3,000 instructions each; random device data, half edge values; random interrupt requests) | 900,000 | agree; all 256 source and 256 destination codes executed; 1,263 interrupt entries |
| MONITOR: cold boot from `03-SYSTD`, `CATALOG` of `18-UTILS` | 1,363,060 | agree |
| ORK-LM: loader, start-up, welcome screen, main loop with RTC interrupts | 6,000,000 | agree |

The check is sensitive: each of these single changes to the HDL makes
random runs fail (8–27 of 40 seeds): SUB carry with `>` instead of `≥`,
RTL carry from bit 14, SHRA carry from the result, PCS = 0 not clearing
ION; and post-increment of the PC register without the fetch increment
(36 of 40). (Reading ION instead of ION ∧ PCS in the PSW is equivalent:
PCS = 0 always clears ION.)

`tests/hdl/test_lockstep.py` runs 60 random programs, and MONITOR's boot
when `SYNCLAVIER_RELEASE_L` is set; it is skipped without Verilator. CI
installs Verilator.

## Next (M4)

| # | Task | Status |
|---|---|---|
| 4.1 | Framework: plain MiSTer template vs JTFRAME (decision D4) | open |
| 4.4 | Memory: internal in BRAM; external (D60–D63) in SDRAM/DDR | open |
| 4.5 | Terminal (D50/D51) | open |
| 4.6 | Disk images from SD (D100 floppy) | open |
| — | Synthesis and timing (Quartus) | needs Quartus (not installed here) |
