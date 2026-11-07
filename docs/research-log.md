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

## Searched without useful results

* archive.org full-text and metadata search for "synclavier", "new england
  digital" and "ABLE computer NED". The only relevant item is
  `Synclavier-docs`.
* GitHub code search for FPRM, FPSM, D300, "model c", "microcode" and SMR00
  across the Synclavier organisation and `jbemond/Software`. No hits.
* bitsavers.org: no NED directory.
