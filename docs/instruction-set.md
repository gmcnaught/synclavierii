# ABLE instruction set (programmer's reference)

Transcribed from the **ABLE Series Hardware Reference Manual**, §II,
pp. 2-5 to 2-31 (PDF pp. 15–41), and Appendix IV (PDF p. 58), working from
page images rather than the OCR text. Page references are given as
`[p. 2-nn]`. The PDF is identified in [`sources.md`](sources.md).

The manual documents the **Model B** CPU (D1 + D300). The Model C (FPSM +
FPRM) runs the same instruction set plus the extensions in
[§9](#9-model-c-and-model-d-extensions). Those come from NED's own
assembler and XPL compiler sources (MIT-licensed, `jbemond/Software`; see
[`sources.md`](sources.md)). The NED assembler mnemonics are given
alongside the codes.

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
| `1 0 1 1 1 0 r r` | 270–273 | **Add with carry** `ADCr` (not in the manual; see §9) | NED asm |
| `1 0 1 1 1 1 r r` | 274–277 | **Subtract with borrow** `SBBr` (not in the manual; see §9) | NED asm |
| `1 1 0 0 R R R R` | 300–317 | **Load register** R (any register; flags unchanged) | 2-22 |
| `1 1 0 1 0 c c c` | 320–327 | **Conditional transfer, absolute**; c = condition (table 5) | 2-22 |
| `1 1 0 1 1 c c c` | 330–337 | **Conditional transfer, relative** | 2-24 |
| `1 1 1 I R R R R` | 340–357 / 360–377 | **Memory destination**: mem[R] ← operand (I = 1: then R ← R + 1) | 2-25 |

## 3. Arithmetic/logical destinations (`200 + 4·A + r`) `[pp. 2-14 to 2-18]`

`acc` is the accumulator R0–R3 selected by bits 9–8. `src` is the 16-bit
operand from the source cycle. The result is written back to `acc`.

| A | Octal | NED mnemonic | Name | Operation | Z | C | M |
|---|---|---|---|---|---|---|---|
| 000 | 200–203 | `LOA0–3` | **LOAD** (arithmetic load) | acc ← src | set | undefined | set |
| 001 | 204–207 | `AND0–3` | **AND** | acc ← acc ∧ src | set | undefined | set |
| 010 | 210–213 | `ADD0–3` | **ADD** | acc ← acc + src | set | carry out | set |
| 011 | 214–217 | `SUB0–3` | **SUBTRACT** | acc ← acc − src | set | **NOT borrow** | set |
| 100 | 220–223 | `XOR0–3` | **XOR** ("add without carry") | acc ← acc ⊕ src | set | undefined | set |
| 101 | 224–227 | `RTL0–3` | **LEFT ROTATE** | acc ← acc rotated left 1 (bit 15 → bit 0); src ignored | **unchanged** | old bit 15 | set |
| 110 | 230–233 | `OR0–3` | **OR** ("set bit") | acc ← acc ∨ src | set | undefined | set |
| 111 | 234–237 | `LCM0–3` | **LOAD COMPLEMENT** | acc ← ¬src (one's complement) | set | undefined | set |

"set" means the flag is updated from the result: Z = (result = 0), M = result
bit 15. Notes:
* No left-shift instruction exists: **`Rn → Rn ADD`** shifts left one place
  `[p. 2-16]`.
* LEFT ROTATE takes no operand. Use **immediate 0** (source 200) so the source
  read is skipped `[p. 2-17]`.

## 4. Test destinations (`240 + 4·T + r`) `[p. 2-19]`

These set Z, C and M exactly like the matching arithmetic destination, but
**do not change the accumulator**.

| T | Octal | NED mnemonic | Test as |
|---|---|---|---|
| 00 | 240–243 | `TLOA0–3` | LOAD |
| 01 | 244–247 | `TAND0–3` | AND |
| 10 | 250–253 | `TADD0–3` | ADD |
| 11 | 254–257 | `TSUB0–3` | SUBTRACT (compare) |

## 5. Byte-swap and right-shift `[pp. 2-20, 2-21]`

| Octal | NED mnemonic | Name | Operation | Z | C | M |
|---|---|---|---|---|---|---|
| 260–263 | `BSOR0–3` | **BYTE-SWAP with OR** | acc ← swap_bytes(acc) ∨ src | set | undefined | set |
| 264–267 | `SHRA0–3` | **RIGHT-SHIFT with ADD** | acc ← (acc >> 1, 0 into bit 15) + src | set | old bit 0 | set |

NED's interpreter header marks BSOR and SHRA as **Model B** additions; the
Model A lacked them.

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
| 000 | always (unconditional) | 320 `ATRA` | 330 `RTRA` |
| 001 | Z | 321 `ATZE` | 331 `RTZE` |
| 010 | C | 322 `ATRC` | 332 `RTRC` |
| 011 | M | 323 `ATMI` | 333 `RTMI` |
| 100 | never | 324 `ATNV` | 334 `RTNV` |
| 101 | not Z | 325 `ATNZ` | 335 `RTNZ` |
| 110 | not C | 326 `ATNC` | 336 `RTNC` |
| 111 | not M (plus) | 327 `ATPL` | 337 `RTPL` |

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
| 004–011 | Reserved (Synclavier: **004–007 D4567 multiply/divide**; **010 = Model C repeat/return, D10**) | 074–077 | Reserved |
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

## 9. Model C and Model D extensions

Not in the Hardware Reference Manual. These come from NED's **ABLE Series
Assembler v2.07** (1989, `configuration modelC`), the **XPL compiler**
sources, and the **ABLE interpreter** headers in `jbemond/Software` (MIT
licence; exact files and commit in [`sources.md`](sources.md)). The
processor model is stored in the system options word: `processor_type =
shr(options_word, 8) and 7`, where **0 = Model A, 1 = B, 2 = C, 3 = D**
(SYSLITS).

| Feature | Encoding | Evidence | Confidence |
|---|---|---|---|
| **Add with carry** | dest 270–273 (`ADC0–3`) | assembler symbol table; interpreter `b_adc 0xB8` | Encoding certain. Semantics inferred from the name: acc ← acc + src + C |
| **Subtract with borrow** | dest 274–277 (`SBB0–3`) | assembler; interpreter `b_sbb 0xBC` | Encoding certain. Semantics inferred: acc ← acc − src − (not C), C = not borrow |
| **Repeat (`RPT`)** | **write I/O device 010 (`D10`)** with *n − 1*; the **next instruction executes *n* times** in microcode, uninterruptibly | compiler: `im(shift-1) to d10 - load repeat counter`, `r3 to d10 [repeat up ((R3 + 1) mod 256) times]`; *Synclavier Internals* `RPT` | High. Count is 8 bits (1–256 executions). |
| **Interrupt return address in D10** | **read device 010** inside a WHEN handler | compiler: `on Model C and later, save return (D10)` → `d10 to mr12d` | Medium: the Model C interrupt entry saves the return PC where D10 can read it |
| **Hardware stack via R12** | memory destination **372 (`MR12I`/`MR12D`) = pre-decrement R12**; memory source 372 = post-increment (pop) | assembler built-in `MR12D` = same code as `MR12I`; compiler pushes with `mr12d`, pops in reverse with `mr12i`; "Model C needs to predecrement stack pointer" | Medium. Unknown whether the decrement applies only to R12. |
| Register conventions | stack pointer **R12** on Model C and later (R15 on A/B); R13 free for the programmer; R0–R3 for in-line assembly | compiler; XPL manual | Software convention |
| Flags after CALL | **Z/C/M are garbage after a procedure call on Model C** | compiler comment | High |
| Model D: code in external memory | compiler option `-f`, "force all code to external memory (e.g. model d)"; runtime "switch to page 0" / "exchange pages" vectors | compiler | Model D only (DSM + FPRM) |

**Implications for the boards:**
* **FPSM:** it must implement I/O device **010** (repeat counter and return
  register). The two **74ALS161** counters (U32/U33, 8 bits) are a strong
  candidate for the **repeat counter** rather than the micro-PC. Re-executing
  the next instruction without a new fetch is microcode behaviour (SMR PROMs).
* **FPRM:** ADC and SBB need the **C flag fed back into the '181 carry-in**.
  The R12 pre-decrement needs a decrement path, either the ALU or the U18/U28
  decode treating code 372 specially as a destination.

### Still unknown
* The exact ADC/SBB flag behaviour; whether other memory-destination codes
  also decrement on Model C.
* The exact Model C interrupt sequence (R16 versus D10) and any other
  devices the FPSM implements in the 002–011 range.
* The FPSM microcode, FPRM decode PROMs and DDE contents define the real
  behaviour. Dumping them would settle all of the above.

### Timing (Scientific XPL Reference Manual, 1987)
* A typical instruction takes **about 1 µs**. Shifts and rotates move one or
  eight bits per instruction in about 1 µs.
* **D4567 hardware multiply/divide** (devices 004–007, option bit `o#d4567`):
  multiply about 2 µs; divide and other operations about 10 µs, because of
  sign correction. Without it, a software routine takes 100–300 µs.
* **Reading or writing a device that doesn't exist halts the computer:** no
  SYN̅ comes back, so the asynchronous bus waits forever. NED used this as a
  diagnostic, with the HOP showing the stuck address.

## 10. Worked examples

NED assembler syntax is `SOURCE TO DESTINATION`. `IM(n)` is an immediate
and `RE(label)` a relative operand. In XPL the same thing is written
`write(dest) = read(source)`.

| NED assembler | Octal word (dest, src) | Effect |
|---|---|---|
| `IM(5) TO R1` | `301 205` | R1 = 5, flags unchanged |
| `R2 TO ADD0` | `210 302` | R0 += R2; Z/C/M updated |
| `R1 TO ADD1` | `211 301` | R1 <<= 1 |
| `IM(0) TO RTL2` | `226 200` | rotate R2 left |
| `PCI TO TSUB0` + `DATA n` | `254 377`, n | compare R0 with the in-line constant |
| `PCI TO ATZE` + `DATA addr` | `321 377`, addr | if Z, PC = addr |
| `IM(-3) TO RTRA` | `330 275` | PC += −3 |
| `R5 TO D1` | `001 305` | write PCW from R5 |
| `IM(7) TO D10` then `IM(0) TO SHRA1` | `010 207`, `265 200` | **Model C:** shift R1 right 8 times |
| `R4 TO MR12D` | `372 304` | **Model C:** push R4 (pre-decrement R12) |

*The words are written high byte (destination) first. The XPL manual's own
example (`r0 = "300"`, `r1 = "301"`, `add0 = "210"`) and NED's assembler
symbol table both agree with these codes.*
