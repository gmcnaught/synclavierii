# Software simulator (`sim/`)

Milestone M1 in [`plan.md`](plan.md). This page covers what exists so far:
**M1.1** (CPU core), **M1.2** (PSW/PCW, interrupts, INIT) and **M1.3–1.5**
(external memory, terminal, real-time clock, multiply/divide). Boot and
debug tooling (M1.6 and M1.7) come next.

## Layout

| File | Contents |
|---|---|
| `sim/cpu.py` | `CPU`: Model B instruction execution, flags, PSW/PCW, interrupt entry, HALT, timing counters |
| `sim/decode.py` | 256-entry source and destination decode tables (checked against `tools/able_disasm.py`) |
| `sim/bus.py` | `Bus` and the `Device` base class for I/O devices 000–177 |
| `sim/devices/` | Device models: `extmem.py` (D60–D63), `terminal.py` (D50/D51), `rtc.py` (D3), `muldiv.py` (D4567). Each file starts with its evidence. |
| `sim/system.py` | `make_system()`: a CPU with all of the above attached |
| `sim/asm.py` | Small assembler in NED syntax (`SRC TO DST`, `DATA`, `IM()`, `RE(label)`), for tests and experiments |
| `tests/sim/` | `test_decode.py` (tables, assembler round trip over all 65,536 words), `test_cpu.py` (42 instruction-level tests) and `test_devices.py` (14 device tests, mostly small programs written like NED's loaders and runtime) |

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

## Devices (M1.3–1.5)

| Device | Registers | Interrupt | Evidence |
|---|---|---|---|
| **D60–D63 external memory** | D60 sector (R/W, 16 bits; writing it starts at word 0); D61 word in the 256-word sector (R/W); D63 data (R/W), each access moves to the next word and carries into D60 | — | FLPLOAD, WINLOAD, SCSILOAD copy loops |
| **D50/D51 terminal** | D50 read = received character, write = send character. D51 read = status: 1 XMIT_IRQ, 2 CHAR_RDY, 4 XMIT_MT, plus card-present bits 8–15 (1000 = D60, 10000 = D100A, 40000 = SCSI…). D51 write clears XMIT_IRQ; with bit 15 set, bits 8–10 choose the baud rate | PSW bit 6 (100) while CHAR_RDY or XMIT_IRQ | NED interpreter header `AbleInterpreter.h`; Model B runtime polling and interrupt code; SYSLITS baud codes |
| **D3 real-time clock** | Write = acknowledge the interrupt | PSW bit 8 (400) every 5 ms (200 Hz) | *Synclavier Internals* §5; SYSLITS `d03_speed`; runtime dispatch `IM(0) TO D3` |
| **D4567 multiply/divide** | Multiply-add: a → D5, addend → D4, b → D6 starts; D5 = low, D4 = high of a·b + addend. Divide: lo → D5, hi → D4, divisor → D7 starts; D5 = quotient, D4 = remainder. Unsigned. Only D4/D5 readable | — | SCSILOAD; NED's C runtime (`AbleCatRtns.cpp`) |

**Unknown registers halt on purpose.** Reading D3, D6 or D7, and any access
to D62 (which exists, but whose function is unknown), returns no SYN, so the
CPU halts and names the device. If Release L touches one of them, the halt
shows where to look.

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
| ADC/SBB destinations (270–277) on Model B | Halt with "unimplemented instruction" | Model B hardware behaviour is unknown; Model C support is M6. |
| `MR12I` destination (372) | Ordinary post-increment | The Model C pre-decrement (`MR12D`) is M6. |
| PSW read side effects (ACK̅) | None | The runtime acknowledges each device explicitly (D3 write, D50 read, D51 write), so no device needs ACK̅ so far. |
| Terminal interrupt enable | Always enabled at the card; software masks with ION | NED code shows no enable bits. |
| Reading D50 with no character waiting | Returns the last character | Unknown. |
| Writing D50 while the transmitter is busy | Character is still sent | A real UART might drop it. |
| External memory beyond the installed size | Reads 0, writes ignored | Unknown; NED sizes memory before using it. |
| D4567 divide by zero, or quotient over 16 bits | ÷0: D5 = 177777, D4 = dividend low word. Overflow: low 16 bits | Unknown. |
| D3 read, D6/D7 read, D62 | Halt (no SYN) | No NED code found that uses them. |
| Device timing (multiply about 2 µs, divide up to 10 µs) | Not modelled: every transfer costs the same | Add if real-time code turns out to depend on it (risk R3). |
