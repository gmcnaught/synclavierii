# ABLE CPU reference notes (from NED documentation)

Notes taken from the New England Digital documentation archived at
<https://archive.org/download/Synclavier-docs/Documentation/Technical%20Documentation/>.
They are summarised and transcribed here so the FPRM-185 and FPSM-185
reverse-engineering can be checked against them. The scans themselves are
not copied into this repo.

| Document | Archive path | Used for |
|---|---|---|
| **ABLE Series Hardware Reference Manual** (60 pp.) | `ABLE Series Hardware Reference Manual/` | CPU architecture, instruction format, **EZbuss 72-pin pinout** (Appendix II, Table 1, PDF p. 45), timing |
| **Synclavier Internals** (NED internal, 19-Jun-1987) | `Synclavier Internals Documentation/` | Synclavier device list; confirms a **microcoded "Model C (or newer)"** processor |
| Creating Programs for ABLE Series Computers | `Creating Programs for ABLE Series Computers/` | Programming (not yet reviewed) |
| Scientific XPL Reference Manual | `Scientific XPL Reference Manual/` | XPL language (not yet reviewed) |

> **Caveat:** the Hardware Reference Manual describes the original ABLE CPU,
> built from the **D1 Sequencer** and the **D300 Register Module** cards. The
> FPSM-185 and FPRM-185 (1985–86) are a later, microcoded implementation of
> the same architecture: *Synclavier Internals* refers to the "Model-C (or
> newer) processor" executing `RPT` "in micro-code". The bus and the
> programmer-visible architecture should be the same. Board-level details
> (which chip does what) can differ.

### Other sources found (search of 2026-11)

| Source | What it adds |
|---|---|
| **GitHub [`Synclavier/Documentation`](https://github.com/Synclavier/Documentation)**, file `Technical Documentation/Synclavier Internals Documentation/Cards and Components - Description.docx` (community compilation, Manfred Waluga, 04/2023; not in the archive.org copy) | **Names the boards and the processor models** (see §5). Also has the same folder's rack and power-supply drawings (`.dwg`). |
| [Vintage Synth Explorer forum: "1982 Synclavier II HxC Retrofit!"](https://forum.vintagesynth.com/viewtopic.php?t=80036&start=15) | A repairer traced a dead system to the **FPRM-185**, "which implements the discrete 16-bit processor's registers and ALU functions", using four 74F181s. It was fixed by swapping in a spare card. |
| [macthenaief: ABLE page](https://sites.google.com/site/macthenaief/Home/retro/able) | Summary of the ABLE ISA (a single MOVE instruction, transport-triggered; 16×16-bit registers; asynchronous bus) and a **VHDL re-implementation ("FAB")** that runs under GHDL. It is an ISA-level re-implementation, not a copy of the NED boards. |
| [studiorepair.com gallery](http://studiorepair.com/gallery/misc/NED_Synclavier_II/index.html) | The board photos we used, plus the main frame, backplane and other cards (D4567, D16, D24, D100, D160, D164, M32K, M512K, MFC1, SK2). Only 822×622 copies are online. |

**No board schematics, service manual or PROM dumps for the FPRM/FPSM were
found in public sources.** One secondary source (500sound.com) reportedly
says NED never produced service manuals; that site was unreachable, so the
claim is unconfirmed.

---

## 1. Architecture (HW Ref. Manual §II, Fig. 1 and Fig. 2)

* 16-bit word, **16 registers** R0–R17 (octal). R0–R3 are accumulators.
  Every register can serve as an index register with auto-increment. R17 is
  the program counter; R16 is the program counter during interrupts and
  subroutine calls.
* **Three status flags: C (carry), Z (zero), M (minus).**
* **The CPU is split across two cards:**
  * **Sequencer** (D1 → **FPSM**): an *Instruction Register* and a *Data
    Register* (both loaded from the data bus), decode and state register, a
    *Selector* that drives the 8-bit Instruction/Address bus, and the IRQ,
    HALT, SYNC, READ and WRITE lines. It receives the 3 flags from the
    Register Module.
  * **Register Module** (D300 → **FPRM**): a **16-register stack**, a
    **16-bit ALU** (A = register side, B = data bus), a **flag register
    (C, Z, M)**, a **shift/swap/latch** stage, its own decode driven from the
    8-bit IAB, and gates onto the data bus and the 16-bit Memory Address Bus.
* **Asynchronous machine. There is no system clock.** For each transfer the
  sequencer:
  1. puts an address on the IAB;
  2. waits about 180 ns, then asserts **RD** or **WR**;
  3. waits for the addressed module to assert **SYN**;
  4. drops the command and waits for SYN to go away.

  A Register Module operation takes about **250 ns**.
* Each instruction is a basic **three-step micro-cycle**:
  1. fetch the instruction (READ via the PC, then auto-increment the PC);
     the word is loaded into both the Instruction Register and the Data
     Register;
  2. **source READ**, using IR bits 0–7 as the IAB address;
  3. **destination WRITE**, using IR bits 8–15 as the IAB address.

  At the end, the sequencer samples HALT and IRQ. IRQ switches the PC to R16.

### How this lines up with the boards

| Fig. 2 block | FPRM-185 / FPSM-185 parts (inferred) |
|---|---|
| Register Module: 16-register stack | **FPRM U31/U33/U37/U38**, 4× CY27S07 16×4. Confirmed as the architectural R0–R17. |
| Register Module: ALU | **FPRM U43/U44/U46/U48** 74F181 + **U41** 74S182 |
| Register Module: flag register C, Z, M | FPRM U8 74F112 and nearby. Drives **EZbuss pins 64/62/60** to the sequencer. |
| Register Module: shift / swap / latch | FPRM '373 groups (U25–U27, U34–U36). Three-state latches, each wired straight, shifted by one bit, or byte-swapped, so that enabling one of them selects the operation *(hypothesis)*. |
| Register Module: gate to MAB | **FPRM U5/U6** '373 → MA0–MA15 (pins 46…16). This matches the "16 traces straight to the fingers" seen in the photo. |
| Register Module: decode from IAB | FPRM **U7** 74ALS244 (receives ADR0–7) → **U18/U28** PROMs and **U2** '139 |
| Register Module: data-bus interface | FPRM U3/U4 74F245 ↔ BDB0–15 |
| Sequencer: Instruction Register and Data Register | FPSM U12/U13 74F374, U24 Am29823, U14 74F245 (exact split TBD) |
| Sequencer: decode / state register | FPSM microcode **SMR00–03** + pipeline registers; **DDE** PROMs (U22/U23) for opcode decode; INITROM for reset |
| Sequencer: Selector → IAB (8 bits) | Two candidates: FPSM U43–U47 '153 (choosing the S field, the D field, R17 for fetch, or a device code), or U2/U3 'LS374 → edge |
| Sequencer: IRQ / HALT / SYNC / READ / WRITE | FPSM U1 74LS240 and U4 74F240 (inverting receivers for the negative-logic bus); U38 74F38 and U54 7438 open-collector drivers (the manual recommends 7438-type drivers for this bus) |
| Sequencer: interrupt handling | FPSM U34/U35 'LS348, U36 'LS174 |
| Sequencer timing (no system clock) | FPSM **U93 delay line + JP1** sets the address-to-command delay and the strobe widths |

---

## 2. Instruction format

The full transcription (every source and destination code, flag effects,
conditional transfers, PSW/PCW, device map and worked examples) is in
**[`instruction-set.md`](instruction-set.md)**.

**Why this matters for the FPRM:** every Register Module operation is
selected by the 8-bit code on ADR0–7, plus RD̅ or WR̅. The FPRM's decode
PROMs (U18/U28) are therefore most likely an **IAB-code → control** lookup:
an address for the register stack, the ALU function, latch enables, gating
onto the data bus and MAB, and the flag write. See
[`boards/fprm-185/README.md`](../boards/fprm-185/README.md).

---

## 3. EZbuss: 72-pin, two-sided edge connector (Appendix II, Table 1)

Card-edge pins 1–72. On the original card this is a Cinch-Jones 50-72C-30-style
connector; the card edge has 36 contacts per side, and the photos match that.
All buses are **negative logic** (logical 1 = 0 V). "Slots" gives the
backplane positions where the line is present.

| Pin | Signal | Slots | Pull-up | | Pin | Signal | Slots | Pull-up |
|---:|---|---|---|---|---:|---|---|---|
| 72 | +5 V | 1–32 | | | 71 | +5 V | 1–32 | |
| 70 | PDS̅ | 1–32 | 390 Ω | | 69 | 1 MHz | 1–32 | on card |
| 68 | WRC̅ | 1–32 | 390 Ω | | 67 | MAIS̅ | 1–32 | 390 Ω |
| 66 | DAISY (with 65) | | | | 65 | DAISY (with 66) | | |
| **64** | **Z̅** | **9–10** | 390 Ω | | 63 | BDB0̅ | 1–32 | 330 Ω |
| **62** | **C̅** | **9–10** | 390 Ω | | 61 | BDB1̅ | 1–32 | 330 Ω |
| **60** | **MIN̅** | **9–10** | 390 Ω | | 59 | BDB2̅ | 1–32 | 330 Ω |
| 58 | MAE | 1–32 | 390 Ω | | 57 | BDB3̅ | 1–32 | 330 Ω |
| 56 | special TTY | | | | 55 | BDB4̅ | 1–32 | 330 Ω |
| 54 | special TTY | | | | 53 | BDB5̅ | 1–32 | 330 Ω |
| 52 | RST̅ | 1–32 | 390 Ω | | 51 | BDB6̅ | 1–32 | 330 Ω |
| 50 | LD̅ | 1–32 | 390 Ω | | 49 | BDB7̅ | 1–32 | 330 Ω |
| 48 | GROUND | 1–32 | | | 47 | BDB8̅ | 1–32 | 330 Ω |
| 46 | MA0̅ | 1–12 | 330 Ω | | 45 | BDB9̅ | 1–32 | 330 Ω |
| 44 | MA1̅ | 1–12 | 330 Ω | | 43 | BDB10̅ | 1–32 | 330 Ω |
| 42 | MA2̅ | 1–12 | 330 Ω | | 41 | BDB11̅ | 1–32 | 330 Ω |
| 40 | MA3̅ | 1–12 | 330 Ω | | 39 | BDB12̅ | 1–32 | 330 Ω |
| 38 | MA4̅ | 1–12 | 330 Ω | | 37 | BDB13̅ | 1–32 | 330 Ω |
| 36 | MA5̅ | 1–12 | 330 Ω | | 35 | BDB14̅ | 1–32 | 330 Ω |
| 34 | MA6̅ | 1–12 | 330 Ω | | 33 | BDB15̅ | 1–32 | 330 Ω |
| 32 | MA7̅ | 1–12 | 330 Ω | | 31 | GROUND | 1–32 | |
| 30 | MA8̅ | 1–12 | 330 Ω | | 29 | ADR7̅ | 1–32 | 3× 1 k |
| 28 | MA9̅ | 1–12 | 330 Ω | | 27 | ADR6̅ | 1–32 | 3× 1 k |
| 26 | MA10̅ | 1–12 | 330 Ω | | 25 | ADR5̅ | 1–32 | 3× 1 k |
| 24 | MA11̅ | 1–12 | 330 Ω | | 23 | ADR4̅ | 1–32 | 3× 1 k |
| 22 | MA12̅ | 1–12 | 330 Ω | | 21 | ADR3̅ | 1–32 | 3× 1 k |
| 20 | MA13̅ | 1–12 | 330 Ω | | 19 | ADR2̅ | 1–32 | 3× 1 k |
| 18 | MA14̅ | 1–12 | 330 Ω | | 17 | ADR1̅ | 1–32 | 3× 1 k |
| 16 | MA15̅ | 1–12 | 330 Ω | | 15 | ADR0̅ | 1–32 | 3× 1 k |
| 14 | GROUND | 1–32 | | | 13 | ACK̅ | 1–32 | 330 Ω |
| 12 | MEM̅ | 1–12 | 390 Ω | | 11 | RD̅ | 1–32 | 2× 270 |
| 10 | RES̅ | 1–32 | 390 Ω | | 9 | WR̅ | 1–32 | 2× 270 |
| 8 | INIT̅ (tied to 7) | | | | 7 | IORST̅ (tied to 8) | | 390 Ω |
| 6 | HALT̅ | 1–32 | 390 Ω | | 5 | SYN̅ | 1–32 | 3× 390 |
| 4 | HAK̅ | 1–32 | 390 Ω | | 3 | IRQ̅ | 1–32 | 390 Ω |
| 2 | GROUND | 1–32 | | | 1 | GROUND | 1–32 | |

*Transcribed from the scan. Overbars on the original show active-low
signals. MAE, MAIS, WRC, PDS, LD and MEM are not explained on this page.*

### What the table tells us
* **The flags Z, C and MIN (pins 64/62/60) exist only in slots 9–10, the two
  CPU slots of the original ABLE bin** (slots 13–14 in the Synclavier
  25-slot bin; see §5). These are the private Register Module → Sequencer lines. This
  is why the FPRM and FPSM must sit in adjacent slots.
* Everything else between the two cards uses the **shared** buses:
  ADR0–7 (IAB), RD, WR, SYN, BDB0–15 and MA0–15. So the FPRM is controlled
  by the same 8-bit address/RD/WR cycles that address any I/O device.
* MA0–15 and MEM are present only in slots 1–12 in this table. In the
  Synclavier bin the CPU sits in slots 13–14 and the core memory in 11–12,
  so **the Synclavier backplane must route MA differently**. This is direct
  evidence that the slot columns of this table do not carry over to the
  Synclavier bin unchanged.
* Pin numbering: even pins on one side, odd on the other; pins 1/2 are GND and
  71/72 are +5 V. Check which physical end is pin 1 on the real card.

**Caveat:** this table is for the documented ABLE bin. Check a Synclavier
bin (and the "185"-series cards) against it before relying on it,
starting with GND, +5 V and the CPU-slot flag pins (60/62/64).

---

## 5. Processor models and slot placement (Cards and Components, 2023)

| Model | Sequencer card | Register card | Used in |
|---|---|---|---|
| B | D1 (instruction sequencer) | D300 (registers) | Original Synclavier II |
| **C ("Fast processor")** | **FPSM** | **FPRM** | PSMT, all Direct-to-Disk and Poly systems, some Synclavier IIs |
| D | **DSM** ("command sequencer module") | **FPRM** | 3200 / 6400 / 9600, PostPro, PostPro SD |

* **"FP" = Fast Processor.** FPRM is "Fast Processor Card 2 (register
  module)". The **same FPRM is used in both Model C and Model D**; only the
  sequencer card changes.
* **Slots:** in the 25-slot computer bin the processor sits in **slots 13
  and 14** (FPRM in 13; FPSM or DSM in 14). Slots 11–12 hold core memory
  (M32K ×2 or M64K). The ABLE manual's EZbuss table puts the private Z/C/MIN
  lines in slots 9–10 of the original ABLE bin, so the CPU slot pair is
  bin-specific. On any bin, the flag lines should link only the two CPU
  slots.
* M64K core memory works only with the Model C processor. M32Ks have
  OLD/NEW jumpers that select Model B or Model C timing.
* The processor's timing reference is the **D3 clock**, generated by one of
  these card pairs: D100 + MFC, D100A + MFC, D100A + D40Q, or M64K + D40Q.
* Certain code written for the C processor does not run on a B processor.
  The XPL catalog keeps processor-specific routines separate, and `RPT n` is
  a Model C microcode feature.

---

## 4. Synclavier device list (Synclavier Internals §5)

For reference, these are the I/O devices on the ABLE bus in a full
Synclavier system:

* D4567 multiply/divide (really D4, D5, D6, D7)
* D3 real-time clock (5 ms interrupts)
* scientific timer (1 ms interrupts)
* SCSI host adaptor
* D30 cartridge tape
* D32X bus extender (multichannel distributor and poly synth interfaces)
* guitar/button panel
* D40Q combined serial card (printer, modem, mouse, D50 terminal)
* D60 external memory
* D70 combined SMPTE/MIDI
* floppies
* clavier/button panel (velocity keyboard)
* FM synth interface
* original-keyboard analog I/O

Device numbers are left out where the OCR is unreadable; check them against the PDF.
