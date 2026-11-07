# ABLE instruction set (programmer's reference)

Transcribed from the **ABLE Series Hardware Reference Manual**, §II,
pp. 2-5 to 2-31 (PDF pp. 15–41), and Appendix IV (PDF p. 58), working from
page images rather than the OCR text. Page references are given as
`[p. 2-nn]`. The PDF is identified in [`sources.md`](sources.md).

This describes the architecture as documented for the original ABLE CPU
(D1 + D300, Model B). The Model C (FPSM + FPRM) runs the same instruction
set and adds extensions, for example `RPT n`, which are not documented here.
See [§9](#9-model-c-extensions-and-unknowns).

Numbers are **octal** unless marked otherwise, as in all NED documentation.

---

## 1. Programmer's model

| Item | Description | Ref |
|---|---|---|
| Word | 16 bits; memory is word-addressed, 64K words (16-bit MA bus) | 2-1 |
| Registers | **R0–R17** (16 × 16 bits). All can be used as pointers or index registers with post-increment. | 2-1, 2-13 |
| Accumulators | **R0–R3**: the only targets of arithmetic, logic, test and shift destinations | 2-1, 2-14 |
| Program counter | **R17** normally; **R16** while handling interrupts (selected by PCW.PCS) | 2-1, 2-31 |
| Flags | **Z** (zero), **C** (carry; NOT-borrow after subtract), **M** (minus = bit 15) | 2-3, 2-16 |
| Interrupt control flip-flop | **ION**, written via the PCW (needs ICS = 1) | 2-30 |
| Reset (INIT) | PC = R17 (PCS = 1); interrupts disabled | 2-31 |

## 2. Instruction format `[p. 2-5]`

Each instruction is one 16-bit word with two independent 8-bit addresses.
There is no opcode field. Every instruction is "move SOURCE → DESTINATION",
and operations are encoded as special destination addresses
(a transport-triggered architecture).

```
 15 14 13 12 11 10  9  8 | 7  6  5  4  3  2  1  0
 D7 D6 D5 D4 D3 D2 D1 D0 | S7 S6 S5 S4 S3 S2 S1 S0
      DESTINATION        |        SOURCE
```

### 2.1 Source codes

| Bits 7–0 | Octal | Class | Operand delivered | Ref |
|---|---|---|---|---|
| `0 d d d d d d d` | 000–177 | **I/O source**, device `d` | data read from I/O device `d` | 2-12 |
| `1 0 S n n n n n` | 200–277 | **Immediate** (6-bit two's complement) | `S` sign-extended from bit 5 to bit 15: 200–237 = 0…+31, 240–277 = −32…−1. **The source READ cycle is skipped.** | 2-12 |
| `1 1 0 I R R R R` | 300–317 | **Register** R | contents of R | 2-13 |
| | 320–337 | Register R, post-increment | contents of R, then R ← R + 1 | 2-13 |
| `1 1 1 I R R R R` | 340–357 | **Memory** (indirect via R) | mem[R] | 2-13 |
| | 360–377 | Memory, post-increment | mem[R], then R ← R + 1. **`R17` with I = 1 (377) reads the next word in line: a 16-bit literal.** | 2-13 |

### 2.2 Destination codes

| Bits 15–8 | Octal | Class / operation | Ref |
|---|---|---|---|
| `0 d d d d d d d` | 000–177 | **I/O destination**, device `d` | 2-14 |
| `1 0 0 A A A r r` | 200–237 | **Arithmetic/logical** on accumulator `r` (R0–R3); A = operation (table 3) | 2-14 |
| `1 0 1 0 T T r r` | 240–257 | **Test** on accumulator `r`; T = operation (table 4) | 2-19 |
| `1 0 1 1 0 0 r r` | 260–263 | **Byte-swap with OR** | 2-20 |
| `1 0 1 1 0 1 r r` | 264–267 | **Right-shift with ADD** | 2-20 |
| `1 0 1 1 1 x r r` | 270–277 | *not defined in the manual* | — |
| `1 1 0 0 R R R R` | 300–317 | **Load register** R (any register; flags unchanged) | 2-22 |
| `1 1 0 1 0 c c c` | 320–327 | **Conditional transfer, absolute**; c = condition (table 5) | 2-22 |
| `1 1 0 1 1 c c c` | 330–337 | **Conditional transfer, relative** | 2-24 |
| `1 1 1 I R R R R` | 340–357 / 360–377 | **Memory destination**: mem[R] ← operand (I = 1: then R ← R + 1) | 2-25 |

## 3. Arithmetic/logical destinations (`200 + 4·A + r`) `[pp. 2-14 to 2-18]`

`acc` is the accumulator R0–R3 selected by bits 9–8. `src` is the 16-bit
operand from the source cycle. The result is written back to `acc`.

| A | Octal | Name | Operation | Z | C | M |
|---|---|---|---|---|---|---|
| 000 | 200–203 | **LOAD** (arithmetic load) | acc ← src | set | undefined | set |
| 001 | 204–207 | **AND** | acc ← acc ∧ src | set | undefined | set |
| 010 | 210–213 | **ADD** | acc ← acc + src | set | carry out | set |
| 011 | 214–217 | **SUBTRACT** | acc ← acc − src | set | **NOT borrow** | set |
| 100 | 220–223 | **XOR** ("add without carry") | acc ← acc ⊕ src | set | undefined | set |
| 101 | 224–227 | **LEFT ROTATE** | acc ← acc rotated left 1 (bit 15 → bit 0); src ignored | **unchanged** | old bit 15 | set |
| 110 | 230–233 | **OR** ("set bit") | acc ← acc ∨ src | set | undefined | set |
| 111 | 234–237 | **LOAD COMPLEMENT** | acc ← ¬src (one's complement) | set | undefined | set |

"set" means the flag is updated from the result: Z = (result = 0), M = result
bit 15. Notes:
* No left-shift instruction exists: **`Rn → Rn ADD`** shifts left one place
  `[p. 2-16]`.
* LEFT ROTATE takes no operand. Use **immediate 0** (source 200) so the source
  read is skipped `[p. 2-17]`.

## 4. Test destinations (`240 + 4·T + r`) `[p. 2-19]`

These set Z, C and M exactly like the matching arithmetic destination, but
**do not change the accumulator**.

| T | Octal | Test as |
|---|---|---|
| 00 | 240–243 | LOAD |
| 01 | 244–247 | AND |
| 10 | 250–253 | ADD |
| 11 | 254–257 | SUBTRACT (compare) |

## 5. Byte-swap and right-shift `[pp. 2-20, 2-21]`

| Octal | Name | Operation | Z | C | M |
|---|---|---|---|---|---|
| 260–263 | **BYTE-SWAP with OR** | acc ← swap_bytes(acc) ∨ src | set | undefined | set |
| 264–267 | **RIGHT-SHIFT with ADD** | acc ← (acc >> 1, 0 into bit 15) + src | set | old bit 0 | set |

With immediate 0 as the source, these become plain BYTE-SWAP and SHIFT
RIGHT. A right *rotate* is done by shifting, then branching on C and adding
100000 back in.

## 6. Register and control-transfer destinations

### 6.1 Load register (300–317) `[p. 2-22]`
Rn ← src, for any register R0–R17. **Flags are not changed.** Loading the PC
in use (R17, or R16 during interrupts) is an **unconditional absolute jump**.

### 6.2 Conditional transfers `[pp. 2-22 to 2-24]`

| c | Condition | Absolute | Relative |
|---|---|---|---|
| 000 | always (unconditional) | 320 | 330 |
| 001 | Z | 321 | 331 |
| 010 | C | 322 | 332 |
| 011 | M | 323 | 333 |
| 100 | never | 324 | 334 |
| 101 | not Z | 325 | 335 |
| 110 | not C | 326 | 336 |
| 111 | not M (plus) | 327 | 337 |

* **Absolute:** if the condition holds, PC (whichever of R17/R16 is in use)
  ← src.
* **Relative:** if the condition holds, PC ← PC + src (two's complement). The
  PC has **already been incremented past the instruction**, and past the
  in-line operand word too when the source is `R17` post-increment (377)
  `[p. 2-24]`.
* **If the condition fails,** the source READ still happens but the
  destination WRITE is skipped. Execution continues with the next
  instruction `[pp. 2-10, 2-23]`.

### 6.3 Memory destination (340–377) `[p. 2-25]`
mem[Rn] ← src; with I = 1 (360–377), Rn ← Rn + 1 afterwards.

## 7. Execution model `[pp. 2-6, 2-9 to 2-11]`

Each instruction is one **micro-cycle** of up to three bus transfers:

1. **Fetch:** READ mem[PC], then PC ← PC + 1. The word is latched into both
   the sequencer's **Instruction Register** and its **Data Register**.
2. **Source READ:** put S7–S0 on the IAB and assert RD. The operand goes into
   the Data Register. *Skipped* for immediate sources: the sign-extended
   bits are already in the Data Register.
3. **Destination WRITE:** put D7–D0 on the IAB, drive the Data Register onto
   the data bus, and assert WR. *Skipped* for a conditional transfer whose
   condition fails.
4. **End of instruction:** if HALT is asserted, raise HAK and stop. If IRQ is
   asserted and interrupts are enabled, take the interrupt (§8).

Every transfer is **asynchronous**. The sequencer asserts the address, waits
(about 180 ns on the ABLE/80), asserts RD or WR, and waits for **SYN** from
the addressed module. Busy devices hold off SYN, which stalls the CPU. A
Register Module operation takes about **250 ns** `[App. II/III]`. See
[`able-reference.md` §1](able-reference.md#1-architecture-hw-ref-manual-ii-fig-1-and-fig-2).

## 8. Special I/O devices and interrupts `[pp. 2-26 to 2-31]`

| Device | Source (read) | Destination (write) |
|---|---|---|
| **000 HOP** (Hand Operated Processor, front panel) | read panel switches; stalls until the operator sends SYN | display on the data lights; stalls until SYN |
| **001 PSW / PCW** | **PSW**; the read also asserts **ACK̅**, and interrupting devices drive their ID bits onto the data bus | **PCW** |

**PSW** (read device 001):

| Bit | 15 … 4 | 3 | 2 | 1 | 0 |
|---|---|---|---|---|---|
| | device interrupt bits | ION | M | C | Z |

Standard interrupt bit assignments: 4 = D43 real-time clock, 5 = D40 modem
controller, 6 = D50 control terminal, 7 = D16 scientific timer, 8 = D03
real-time clock, 9 undefined, 10–15 user-definable.

**PCW** (write device 001):

| Bit | 15 … 6 | 5 | 4 | 3 | 2 | 1 | 0 |
|---|---|---|---|---|---|---|---|
| | undefined | PCS | ICS | ION | M | C | Z |

* Z, C and M are copied into the flag register.
* ION sets or clears the interrupt flip-flop **only when ICS = 1**.
* **PCS = 1 selects R17** as the PC; **PCS = 0 selects R16**.
* Switching to R16 automatically disables interrupts. Reading the PSW while
  R16 is in use returns ION = 0.

**Interrupt entry:** IRQ̅ is sampled at the end of each instruction. If it
is asserted and ION = 1, interrupts are disabled and the next fetch uses
**R16** as the PC `[pp. 2-3, 2-10]`. R16 must point at the handler before
interrupts are enabled. The handler returns by writing the PCW with PCS = 1
(and ION/ICS as needed).

### Standard device addresses (Appendix IV, PDF p. 58)

| Octal | Function | Octal | Function |
|---|---|---|---|
| 000 | HOP | 060, 061 | Dual D/A converter |
| 001 | PSW, PCW | 062–067 | Aux. D/A converters |
| 002 | Reserved | 070, 071 | Scope interface |
| 003 | Real-time clock | 072, 073 | Aux. scope interfaces |
| 004–011 | Reserved | 074–077 | Reserved |
| 012, 013 | A/D converter | 100–104 | Floppy disk controller |
| 014, 015 | Aux. A/D converter | 105–107 | Tape drive |
| 016–033 | Reserved | 110–117 | Disk drive |
| 034, 035 | Digital I/O module | 120–127 | **Free user space** |
| 036, 037 | Aux. digital I/O | 130–133 | Reserved |
| 040, 041 | Modem controller, status | 134–137 | Digital I/O |
| 042–047 | Aux. serial devices | 140–157 | Aux. serial devices |
| 050, 051 | System control terminal, status | 160–167 | Reserved |
| 052–057 | Aux. serial devices | 170–177 | PROM programmers, system test modules, etc. |

Synclavier systems add many more devices (D16 timer, D24 SCSI, D57 poly,
D160 FM, …). See *Synclavier Internals* §5.

## 9. Model C extensions and unknowns

* *Synclavier Internals* documents an XPL construct **`RPT n`** that works on
  "Model-C (or newer)" processors only. It executes the next single-word
  instruction *n* times "in micro-code" as one uninterruptible instruction
  cycle (usually limited to `RPT 64`). How it is encoded is not documented
  here; it is probably one of the undefined codes, or an I/O address
  decoded by the FPSM.
* Undefined destination codes **270–277**: possible Model C/D extensions.
* Not documented: whether the Register Module flags or the Sequencer
  latches C/Z/M; the exact carry behaviour of SUBTRACT with the 74F181;
  and what happens with a register source of the current PC (which value of
  R17 is read).
* The Model C microcode (FPSM SMR00–03) and decode PROMs (FPRM U18/U28,
  FPSM DDE) define the real behaviour. Dumping them would settle all of
  the above.

## 10. Worked examples

| Instruction (dest ← source) | Octal word | Effect |
|---|---|---|
| R1 ← immediate 5 (load register) | `301 205` | R1 = 5, flags unchanged |
| R0 ADD ← R2 | `210 302` | R0 += R2; Z/C/M updated |
| R1 ADD ← R1 | `211 301` | R1 <<= 1 |
| R2 LEFT ROTATE ← immediate 0 | `226 200` | rotate R2 left |
| R0 TEST-SUB ← mem[R17++] | `254 377` + literal | compare R0 with the in-line constant |
| jump-if-zero absolute ← mem[R17++] | `321 377` + address | if Z, PC = address |
| jump relative always ← immediate −3 | `330 275` | PC += −3 |
| PCW ← R5 | `001 305` | set flags, PC select and interrupt state from R5 |

*The octal words are written high byte first, then low byte, as NED
printed 8-bit fields. They are worked out from the tables above; no
assembler listing has been checked.*
