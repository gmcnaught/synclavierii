# NED Synclavier "Fast Processor" (ABLE Model C) — reverse engineering

This project documents the CPU of the New England Digital Synclavier: the
**ABLE Model C "Fast Processor"**. It is built from two cards:

| Board | Role | Folder |
|---|---|---|
| **FPRM-185** | Fast Processor **Register Module**. 16-bit ALU (4× 74F181 + 74S182), 16×16 register file (4× CY27S07), C/Z/M flags, memory-address and data-bus interface. Used in **Model C and Model D**. Bin slot 13. | [`boards/fprm-185/`](boards/fprm-185/README.md) |
| **FPSM-185** | Fast Processor **Sequencer Module**. ≈28-bit pipelined microcode (SMR00–03 PROMs), next-address sequencer, opcode-dispatch PROMs, interrupt priority, delay-line timing. **Model C** only (Model D uses the DSM instead). Bin slot 14. | [`boards/fpsm-185/`](boards/fpsm-185/README.md) |

Where to start:

| Document | Contents |
|---|---|
| [`docs/able-reference.md`](docs/able-reference.md) | Architecture, the 72-pin EZbuss pinout, processor models and slots |
| [`docs/instruction-set.md`](docs/instruction-set.md) | **Full ABLE instruction set** with NED mnemonics, plus the **Model C extensions** (ADC/SBB, `RPT` via D10, R12 stack) from NED's own assembler and compiler sources |
| [`docs/model-c-runtime-analysis.md`](docs/model-c-runtime-analysis.md) | Disassembly of NED's Model B/C/D runtime packages: **D10 link register**, R12-only stack, RPT and ADC confirmed |
| [`docs/release-l-image.md`](docs/release-l-image.md) | The Release L (1986) disk image: catalog format, `.LD-6` = three position-independent boot loaders, OS and real-time binaries compiled for Model B |
| [`docs/boot-and-loaders.md`](docs/boot-and-loaders.md) | Boot chain (Load → boot ROM → `.LD-7` loader → MONITOR), loader entry vector, the D4567/SCSI/external-memory device protocols |
| [`tools/`](tools/README.md) | `able_disasm.py`: ABLE disassembler, validated 541/541 against an NED assembler listing (`tests/`); `ned_disk.py`: NED disk-image lister/extractor |
| [`docs/bench-checklist.md`](docs/bench-checklist.md) | What to do when someone has a board or bin: PROM reads, measurements, photos |
| [`docs/sources.md`](docs/sources.md) | Pinned sources: checksums, commit IDs, page map |
| [`docs/research-log.md`](docs/research-log.md) | How we got here, including corrections and dead ends |
| [`data/`](data/README.md) | CSVs: EZbuss pinout, opcode map, netlist (STD/OBS/HYP) |

> **Status: first pass.** The BOMs and chip identities are solid. The block
> schematics and netlists are **inferred** from 822×622 photos plus NED
> documentation. Every connection is tagged **[STD]** (standard topology),
> **[OBS]** (seen in the photo) or **[HYP]** (hypothesis). No physical
> hardware has been measured, no PROMs have been read, and no public
> schematics exist as far as we could find.

---

## Repository layout

```
README.md                    this file: overview, status, next steps
docs/
  able-reference.md          architecture, 72-pin EZbuss pinout, processor models/slots
  instruction-set.md         full ABLE instruction set (from page images of the manual)
  bench-checklist.md         hardware tasks: PROM reads, edge/backplane maps, photos
  sources.md                 pinned sources: checksums, commits, page map
  model-c-runtime-analysis.md  disassembly findings (D10 link, R12 stack, RPT, ADC)
  boot-and-loaders.md        boot chain, loader vector, D4567 / SCSI / ext-memory protocols
  release-l-image.md         Release L disk image: format, loaders, Model B binaries
  research-log.md            chronology of findings, corrections and sources
tools/
  able_disasm.py             ABLE disassembler (NED syntax, Model C aware)
  ned_disk.py                NED .simg catalog lister / extractor
tests/
  test_able_disasm.py        validation against NED's SCSI.LST listing (fixture, MIT)
data/
  ezbuss-pinout.csv          72-pin pinout + expected chips + columns to fill in
  able-opcodes.csv           source/destination code map with flag effects
  netlist.csv                board connections tagged STD / OBS / HYP
boards/
  fprm-185/
    README.md                layout, inferred netlist, doc cross-check, verification plan
    bom.csv                  BOM with a confidence rating per line
    schematic-block.svg      block-level schematic
  fpsm-185/
    README.md
    bom.csv
    schematic-block.svg
```

## How the CPU works (short version)

```
                 72-pin EZbuss backplane (P1 on both cards)
   ══════╤══════════════════════════════════════════════════╤══════
         │  ADR0-7 (8-bit Instruction/Address bus), RD, WR,  │
         │  SYN handshake, BDB0-15 data  ◄─── shared bus ───►│
         │  MA0-15 memory address ◄── driven by the FPRM     │
         │  Z, C, MIN flags ──── private: the two CPU slots ─►│
 ┌───────┴────────┐                                  ┌───────┴────────┐
 │   FPRM-185     │                                  │   FPSM-185     │
 │ 16 regs · ALU  │                                  │ IR · data reg  │
 │ flags · MAR    │                                  │ microcode ·    │
 │ IAB decode     │                                  │ dispatch · IRQ │
 └───────┬────────┘                                  └───────┬────────┘
         │ J1 34-pin ribbon                                  │ J1 34-pin ribbon
         ▼ to other external cards (TBD)                     ▼ to other external cards (TBD)
```

* The ABLE has a **single MOVE instruction**: an 8-bit SOURCE address and an
  8-bit DESTINATION address (transport-triggered). Arithmetic, tests and
  jumps are special destinations.
* Each instruction runs as a three-step micro-cycle: **fetch → source READ →
  destination WRITE**. Each step is an **asynchronous** bus transfer: the
  sequencer puts an address on ADR0–7, asserts RD or WR, and waits for the
  addressed module to answer on SYN. There is no system clock.
* The sequencer drives the Register Module **over the shared bus**, using
  register/ALU codes on ADR0–7, the same way it addresses any I/O device.
  Only the three flag lines are private to the CPU slots, which is why the
  two cards must sit in adjacent slots.

## Processor models

| Model | Cards | Used in |
|---|---|---|
| B | D1 sequencer + D300 register module | Original Synclavier II |
| **C** | **FPSM + FPRM** ("Fast Processor") | PSMT, Direct-to-Disk, Poly systems, some Synclavier IIs |
| D | DSM + FPRM | 3200 / 6400 / 9600, PostPro, PostPro SD |

## Open questions

* **PROM contents:** FPRM U18 and U28; FPSM SMR00–03, DDE (U22/U23) and
  INITROM. These hold the microcode and decode tables. No public dumps exist.
* The **P1 edge pin-out** on these cards, compared with the documented ABLE
  EZbuss, starting with GND, +5 V and the Z/C/MIN pins (60, 62, 64).
* What the **J1 34-pin ribbons** connect to.
* Which FPSM chips drive ADR0–7: the '153 multiplexers or U2/U3. Are U32/U33 the Model C repeat counter?
* Whether relative or untaken transfers also update the D10 link (`ppc`). No NED software depends on it. Also the exact Model C interrupt-entry microsequence.
* The MFC/D40Q boot ROM image (not in any source found; its *function* is known: load `MONITOR` from the F0 catalog and start it, so a re-implementation can emulate it at a high level, as NED's own Mac runtime does).
* Exact identity of a few chips (FPRM U41 and U8; FPSM U4, U52 and U73) and of
  the PROMs under their labels.

## Next steps

| Option | Needs hardware? | Notes |
|---|---|---|
| **Behavioural / instruction-level model** of the ABLE CPU (spec + test vectors, then HDL, e.g. as an FPGA core) | No | `docs/instruction-set.md` gives the full ISA including the Model C extensions; `data/able-opcodes.csv` is a ready decode table. NED's MIT-licensed assembler and XPL compiler (`jbemond/Software`) can generate test programs. |
| **KiCad capture** of what's confirmed | No | Parts, the '181/'182 carry chain, the register file, and the EZbuss nets; guessed nets left as labelled stubs. |
| **Read the PROMs** | Yes | The single most valuable step. Without them, a gate-accurate model of the boards isn't possible. |
| **High-resolution photos** (≥600 dpi, both sides, square-on) | Yes | Most traces could then be followed from overlaid images. |
| **Edge-finger and backplane continuity map** | Yes | The procedure is in `docs/bench-checklist.md` §3–4; record results in `data/ezbuss-pinout.csv`. |
| **Community outreach** | — | Synclavier owners and repairers (see the forum thread in `docs/research-log.md`) may have spare cards, dumps or photos. |

## Sources and credits

* Board photos: [STUDIO REPAIR gallery, NED Synclavier II](http://studiorepair.com/gallery/misc/NED_Synclavier_II/index.html).
  These photos are © studiorepair.com and are **not included** in this repo;
  link to them instead.
* NED documentation (ABLE Series Hardware Reference Manual, Synclavier
  Internals): [archive.org `Synclavier-docs`](https://archive.org/details/Synclavier-docs)
  and [GitHub `Synclavier/Documentation`](https://github.com/Synclavier/Documentation),
  including *Cards and Components – Description* (M. Waluga, 2023). They are
  summarised here, not copied.
* Board roles and installation notes supplied by the project owner.

## Creating the standalone repository

This branch has the project files at its root, and the commit history was
carried over from where the work began. To publish it as its own repo:

```bash
# create an empty repo on GitHub first (no README/licence), then:
git clone --branch synclavier-able-cpu --single-branch \
    https://github.com/gmcnaught/misterfpga-skill.git synclavier-able-cpu
cd synclavier-able-cpu
git remote set-url origin https://github.com/<owner>/<new-repo>.git
git branch -m main
git push -u origin main
```

No licence has been chosen yet. Add one when the repo is created.
