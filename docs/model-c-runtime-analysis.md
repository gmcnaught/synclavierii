# Model C runtime analysis (disassembly of NED's own code)

**Goal:** settle the Model C open questions using real NED machine code
instead of the compiler's comments.

**Material:** the compiled XPL runtime packages for each processor model, from
`jbemond/Software` (MIT). Exact files and IDs are in [`sources.md`](sources.md).

| File | Model | Words |
|---|---|---|
| `Able/*SYSTEM/*RTB-7.sdat` | B (D1 + D300) | 4794 |
| `Able/*SYSTEM/*RTC-7.sdat` | **C (FPSM + FPRM)** | 4537 |
| `Able/*SYSTEM/*RTD-7.sdat` | D (DSM + FPRM) | 4568 |

**Tool:** [`tools/able_disasm.py`](../tools/README.md). The files are
big-endian 16-bit words, and the file offset is the load address.

## 1. Decoder validation

The disassembler was checked against **NED's own assembler listing** of the
SCSI loader (`Able/LOADER/SCSI.LST`, kept as a test fixture):

* **541 / 541** instruction words decode to the same source and destination
  NED's assembler printed. This includes the **107 numeric immediates**
  (octal) and every builtin operand (Rn, RnI, MRn, MRnI, PCI, Dn).
* **78 / 78** relative transfers (`RE(label) TO RTxx`) land exactly on their
  label. This confirms that **target = address of the next word + the
  6-bit immediate**.

Run it with `python3 tests/test_able_disasm.py`.

## 2. Feature counts per model

Counts are over the whole file, so data words decoded as code add a little
noise (for example the stray ADC/D10 hits in Model B).

| Pattern | Model B | **Model C** | Model D |
|---|---:|---:|---:|
| `… TO MR12D` (stack push) | 0 | **73** | 77 |
| `MR12I TO …` (stack pop) | 11 | 29 | 31 |
| `… TO MR15I` (Model A/B stack push) | 38 | 0 | — |
| `… TO D10` (repeat count) | 20 (noise) | **48** | 45 |
| `D10 TO …` (read link) | 1 | **63** | 66 |
| `… TO ADC/SBB` | 2 (noise) | **32** | 32 |
| `… TO D1` (PCW writes) | 142 | 24 | 23 |

The Model C runtime clearly uses the new features, and Model B does not.

## 3. Findings

### 3.1 D10 is a hardware link register (high confidence)

On Model C a **call is a plain absolute jump** (`PCI TO ATRA` + address; the
compiler's `create_object_emit_page_0_call`). The callee then saves the
return address from **D10**. The save-registers routine shows the whole
pattern:

```
000132  000660  IM(-20)  TO D1       ; PCW: interrupts off (ICS=1, ION=0, PCS=1)
000133  175304  R4       TO MR12D    ; push R4 … R11
 …
000140  175311  R11      TO MR12D
000141  000714  R14      TO D1       ; restore PCW
000142  150010  D10      TO ATRA     ; return to caller: D10 holds the return address
```

This routine is itself entered by `IM(sreg) TO ATRA`. So **a taken
absolute transfer, including one with an immediate address, leaves the
return address (the address after the transfer instruction and its in-line
operand) in D10.** Procedure prologues push it with `D10 TO MR12D` (or
`D10 TO MR12`). WHEN (interrupt) handlers do the same, so an interrupt
entry must also load D10 with the interrupted PC.

Still unknown: whether *relative* transfers also load D10, and whether a
transfer that isn't taken (condition false) changes D10.

### 3.2 R12 is a hardware stack pointer; only R12 decrements (high confidence)

* Push = destination **372** (`MR12D`): pre-decrement R12, then store.
* Pop = source 372 (`MR12I`): load, then post-increment.
* Return = `R12I TO ATNV` (an increment using the "transfer never" trick)
  plus `MR12 TO ATRA`.
* **Other memory destinations with I = 1 still post-increment on Model C.**
  For example, the runtime builds a jump trampoline in RAM with
  `R0 TO MR1I`, `PCI TO MR1I` + `DATA 150303` (`R3 TO ATRA`), and it clears
  buffers upward with `IM(0) TO MR2I`. Both only work if R1/R2 count up.

### 3.3 RPT via D10 (high confidence)

```
000163  106601  IM(1)    TO SUB1     ; R1 = n - 1
000164  004301  R1       TO D10      ; Model C RPT: repeat next instruction
000165  171200  IM(0)    TO MR2I     ; clear n words at R2 (upward)
```

Writing D10 sets the repeat count, and reading D10 returns the link, so
the two are separate registers behind one device address.

### 3.4 ADC/SBB semantics (high confidence for ADC)

The runtime's 32-bit shift-left:

```
001050  104701  R1       TO ADD1     ; low word  <<= 1, carry out → C
001051  134300  R0       TO ADC0     ; high word = high + high + C
```

and `IM(0) TO ADC0` propagates a carry into a high word. This confirms
**ADC: acc ← acc + src + C**, with C as the carry out. SBB is assumed to be
the mirror (acc − src − not C, with C = not borrow), by analogy with SUB.
That is not yet checked against code.

### 3.5 Interrupts and the PCW

The runtime disables interrupts with `IM(-20) TO D1` (PCW = 177760:
ICS = 1, ION = 0, PCS = 1, flags cleared) and restores a saved PCW from
R14. The interrupt routine pushes R0–R3 and the **PSW** (`D1 TO MR12D`) onto
the R12 stack, then dispatches through a table of device tests. Model C
keeps the PSW/PCW mechanism; D10 adds the return address.

## 4. What this means for the boards

* **FPSM:**
  * implements device **010**: a write loads an 8-bit **repeat counter**
    (U32/U33 'ALS161 ×2 is the likely part); a read returns the **link
    register**
  * on every taken absolute transfer (and on interrupt entry), the
    microcode copies the current PC into the link register
  * the IR/PC path must support re-executing one instruction n times
* **FPRM:**
  * code 372 as a **destination** pre-decrements R12, and only R12, so its
    IAB decode (U18/U28) must single out that code
  * ADC/SBB route the **C flag into the '181 carry-in**

## 5. Reproduce

```bash
git clone https://github.com/jbemond/Software
python3 tools/able_disasm.py "Software/Able/*SYSTEM/*RTC-7.sdat" --model C > rtC.dis
python3 tools/able_disasm.py "Software/Able/*SYSTEM/*RTC-7.sdat" --model C --start 132 --count 21
```
