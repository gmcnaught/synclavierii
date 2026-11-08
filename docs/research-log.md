# Research log

A record of how the current understanding was reached, in order. It
includes the corrections, so the reasoning behind the board notes can be
followed and checked. Newest information wins where entries disagree.

## 1. First pass from photos: FPRM-185

* **Input:** component-side and solder-side photos of the FPRM-185 from
  studiorepair.com, 822×622 px.
* **Chips identified:** 4× 74F181, 74S182, 4× CY27S07 16×4 RAM, ten
  74F373, five 74F374, '245/'244/'139/'153/'112, glue logic, and two
  socketed, labelled PROMs (U18; U28 "FPRM 01 ©1986 N.E.D.").
* **Initial guess:** a microcoded arithmetic or floating-point co-processor.
  *Wrong.* "FP" was later found to mean **Fast Processor** (see §6).

## 2. Owner correction: FPRM = CPU Register Module, partner = FPSM

* The board was re-interpreted as the CPU data path: register file, ALU and
  memory-address/data interface. The control logic lives on the partner FPSM.

## 3. FPSM-185 photos

* **Chips identified:**
  * 4 microcode PROMs: SMR00–02 (24-pin) and SMR03 (16-pin), each above its
    pipeline register (2× Am29823, '374, '175), giving a ≈28-bit microword
  * 5× '153 and 2× 'ALS161, forming a next-address sequencer
  * '151 condition select
  * 2× 'LS348 interrupt priority encoders
  * DDE PROMs (U22/U23) and INITROM
  * a tapped delay line with a 40–80 ns tap jumper
  * 2× DIP resistor networks next to J1
* **Initial guess:** the J1 ribbon linked the FPSM and FPRM. *Wrong* (see §4).

## 4. Owner correction: the cards communicate through the backplane

* The J1 ribbons go to *other* external cards. The FPRM↔FPSM link is the
  P1 edge connector and backplane.
* Owner-supplied installation notes, source not cited:
  * both cards plug into the backplane (for example "IB25") in **strictly
    adjacent slots**
  * peripheral cards cable out of the rack

## 5. NED documentation (archive.org `Synclavier-docs`)

* **ABLE Series Hardware Reference Manual:**
  * the CPU is a Sequencer card plus a Register Module card
  * the instruction format
  * the asynchronous three-step micro-cycle
  * the full **72-pin EZbuss pinout** (Appendix II, Table 1), transcribed
    into `docs/able-reference.md` §3
* **Key result:** the flag lines Z̅/C̅/MIN̅ (pins 64/62/60) are wired only in
  the two CPU slots. That is the documented reason for the adjacent-slot rule.
  Everything else between the two CPU cards uses the shared ADR0–7, RD/WR,
  SYN, BDB and MA lines.
* **Synclavier Internals (1987):** refers to a microcoded "Model-C (or
  newer)" processor.

## 6. Wider search

* **GitHub `Synclavier/Documentation`:** has the same scans as archive.org,
  plus *Cards and Components – Description.docx* (M. Waluga, 2023). From it:
  * FPRM = "Fast Processor Card 2 (register module)"
  * FPSM + FPRM = **Model C**; DSM + FPRM = **Model D**; D1 + D300 = Model B
  * the processor sits in slots 13/14 of the 25-slot computer bin
* **Vintage Synth Explorer forum**
  ([thread](https://forum.vintagesynth.com/viewtopic.php?t=80036&start=15)):
  a repairer traced a dead Synclavier II to the FPRM-185 (registers and the
  74F181 ALU) and fixed it with a spare card.
* **macthenaief ABLE page**
  ([link](https://sites.google.com/site/macthenaief/Home/retro/able)): an
  ISA summary and a VHDL re-implementation ("FAB", GHDL). It is not a copy of
  the NED boards.
* **studiorepair.com:** also has backplane and card-cage photos (the cage
  slots are numbered up to 32), but no originals above 822×622.
* **Not found:** FPRM/FPSM schematics, a service manual, or PROM/microcode
  dumps. A secondary source (500sound.com, unreachable) reportedly says NED
  produced no service manuals.

## 7. Consolidation (no hardware available)

* **Instruction set:** transcribed in full from page images of the manual
  (pp. 2-5 to 2-31, App. IV) into `docs/instruction-set.md` and
  `data/able-opcodes.csv`.
* **Consistency pass:**
  * The FPRM is now described as controlled by IAB codes on the shared bus.
    The earlier idea of "control fields" sent from the FPSM was dropped.
  * The instruction register is placed on the FPSM, per the manual.
  * The slot numbers are reconciled: 9–10 in the ABLE bin, 13–14 in the
    Synclavier bin.
  * New point: the ABLE table limits MA0–15 to slots 1–12, so the
    Synclavier backplane must route MA differently.
* **New hypothesis:** FPRM U18 is a 32×8 PROM (82S123 class) that decodes
  the IAB class from ADR7–3.
* **Also added:** the bench checklist, the data CSVs and the pinned sources.

## 8. The two remaining NED manuals and NED's own source code

* **Creating Programs (1978):** an OS user guide. Only the boot procedure is
  of interest.
* **Scientific XPL Reference Manual (1987):**
  * its in-line assembly example independently confirms the codes
    (`r0 = "300"`, `add0 = "210"`)
  * timings (about 1 µs per instruction; D4567 multiply about 2 µs)
  * reading or writing a missing device halts the CPU (no SYN̅)
  * Model B/C compiled modules are incompatible
* **GitHub `jbemond/Software` (MIT):** NED's software tree, including the
  ABLE **assembler**, the **XPL compiler**, the SYSLITS and the interpreter
  headers. (GitHub code search had missed it because its files have no
  extensions.) It yields:
  * the official mnemonics
  * the two "undefined" destination ranges: **ADC 270–273** and **SBB
    274–277**
  * Model C's **`RPT` = writing I/O device 010 (D10)**, an 8-bit repeat
    count
  * reading D10 returns the interrupt return address on Model C
  * R12 as a hardware stack pointer (`MR12D` pre-decrement alias)
  * the processor-type codes A=0 … D=3
* **New board hypothesis:** FPSM U32/U33 ('ALS161 ×2, 8 bits) are the
  repeat counter.

## 9. Disassembly of NED's runtime and loaders

* Wrote `tools/able_disasm.py`. It matches NED's own assembler listing
  word-for-word (541/541) and on every relative-jump target (78/78).
  Correction made along the way: NED immediates are **octal**.
* Model C runtime (`*RTC-7`) findings:
  * **D10 is a link register.** A taken absolute jump, even with an
    immediate address, leaves the return address there; procedures push it
    with `D10 TO MR12D`.
  * **Only R12 pre-decrements.**
  * `RPT` (writing D10) is confirmed in a buffer-clear loop.
  * **ADC = acc + src + C**, confirmed by a 32-bit shift.
* Loaders:
  * the boot chain is Load → boot ROM on the MFC/D40Q (image not found) →
    the 768-word `.LD-7` loader near the top of core → MONITOR
  * the loader sources document the D4567 multiply/divide, D24–D27 SCSI
    and D60–D63 external-memory protocols

## 10. Closing the software-answerable ISA questions

* **SBB:** the Model C runtime's floating-point divide uses `SUB1` then
  `SBB0`. So SBB = acc − src − (1 − C), with C = NOT borrow like SUB. The
  FPRM needs only a carry-in multiplexer.
* **D10 and relative jumps:** the compiler makes every call an absolute
  transfer. NED's interpreter state names the two D10 registers: `rpc`
  (repeat counter) and `ppc` (prior program counter). Relative and untaken
  transfers can't be checked from software, and nothing depends on them.
* Every instruction-set question that software can answer is now closed.
  The rest need hardware (see `bench-checklist.md`).

## 11. Release L distribution image (owner pointer)

* `Synclavier_Distributions/Release_L` is one `.simg` holding 19 floppies.
  Wrote `tools/ned_disk.py` to list and extract it.
* **`.LD-6` = three 512-word position-independent loaders** (floppy at 0,
  IMI at 1000, SCSI at 2000). They match the FLPLOAD source, which is a
  second disassembler check on a real binary.
* `MONITOR` and `ORK-LM` are **compiled for Model B** (MR15I stack): useful
  as backward-compatibility test programs.
* **Not present:** the MFC/D40Q boot ROM and any CPU diagnostic.

## 12. Emulator software (Synclavier³) and the boot ROM

* NED's public source has **no boot ROM**. The host runtime builds the
  post-boot memory state in C, which amounts to high-level emulation of the
  boot. The Synclavier³ PCI product replaces the CPU, so it doesn't need the
  ROM either.
* `WINBOOT` documents the ROM's job: load `MONITOR` from the F0 catalog and
  start it.
* The compiled `.LD-7` (= HIGHLOAD, 3 × 768 words) is now available under
  MIT.
* Commercial Synclavier³ and other emulator binaries were deliberately not
  examined (proprietary). The CPU-interpreter core and any ROM images would
  have to come from Synclavier Digital.

## Searched without useful results

* archive.org full-text and metadata search for "synclavier", "new england
  digital" and "ABLE computer NED". The only relevant item is
  `Synclavier-docs`.
* GitHub code search for FPRM, FPSM, D300, "model c", "microcode" and SMR00
  across the Synclavier organisation and `jbemond/Software`. No hits, but
  that repo's files have no extensions and are not indexed; see §8.
* bitsavers.org: no NED directory.
