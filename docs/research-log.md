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

## 13. Simulator CPU (M1.1–1.2)

* `sim/` runs the Model B instruction set at about 1.6 MIPS in Python, close
  to the real machine's speed. Choices the manual leaves open are listed in
  [`simulator.md`](simulator.md).
* Writing the tests showed why NED code writes the PCW with **negative
  immediates** (`IM(-20) TO D1`): PCS is bit 5, and a positive 6-bit
  immediate only reaches bit 4. `IM(-20)` = 177760 selects R17 with
  ICS = 1 and ION = 0, which matches the "interrupts off" comment in the
  runtime.
* The manual does not say whether `PCI` follows R16 at interrupt level. The
  simulator reads through R17; interrupt handlers in Release L will show
  which is right.

## 14. Devices for the simulator (M1.3–1.5)

Sources: NED's loaders (FLPLOAD, WINLOAD, SCSILOAD), the interpreter header
`Code/Includes/Able Interpreter/AbleInterpreter.h`, the XPL-to-C translator,
`AbleCatRtns.cpp`, and a disassembly of the Model B runtime `*RTB-7.sdat`
(all MIT, `jbemond/Software` @ `a237bf2`). Register details are in
[`simulator.md`](simulator.md#devices-m13-15).

* **Terminal D50/D51:** the interpreter header gives the D51 status bits
  (XMIT_IRQ 1, CHAR_RDY 2, XMIT_MT 4) and card-present bits 8–15. The
  loaders use the latter to detect a D100A (10000) and a SCSI card (40000).
* **Interrupt dispatch in the Model B runtime** (`*RTB-7` addresses
  705–735) is a table of handlers that also shows how each device is
  acknowledged: `IM(0) TO D3` for the clock; `D16 TO …` (a read) for the
  D16 timer; for the terminal, `D51` is read and either `D50` is read
  (TTIINT) or `IM(0) TO D51` clears the transmit interrupt (TTOINT).
* **At interrupt level the runtime reads in-line constants with `MR16I`
  (376), not `PCI` (377).** That supports the simulator's choice that
  register codes are not remapped when R16 is the PC.
* **External memory:** D63 auto-increments across sector boundaries
  (whole tracks and swap files are copied after a single D60 write), D60
  and D61 are readable (the loaders read them to find where a copy ended),
  and SCSILOAD parks an unrelated 16-bit value in D60 and reads it back.
* **D62 exists** (the XPL-to-C translator knows `_read_62`/`_write_62`)
  but its function is unknown. **D4567:** only D4 and D5 are readable.
* **PCW bit layout, open question.** The interpreter header names bit 3
  `D1_ION` (read/write) and bit 4 `D1_PC17` ("pc select flag", write only),
  and has no ICS bit. The hardware manual has ION = bit 3, ICS = bit 4,
  PCS = bit 5. Every PCW value found in NED code (`IM(-20)`, `IM(0)`, saved
  `IM(-20)` images) means the same under both layouts, so nothing seen so
  far tells them apart. The simulator follows the manual. The header may
  describe the later Model D, or simplify for the interpreter.
* **Open:** the runtime writes `IM(0) TO D3` 32 or 62 times in a row
  (`*RTB-7` 4353), which only makes sense as a delay if a D3 write waits for
  the next clock tick. The simulator treats the write as an acknowledgement
  only.

## 15. First boot of Release L MONITOR (M1.6 step A, M1.7)

Sources: Release L image (user-supplied, SHA-256 checked against
[`sources.md`](sources.md)); NED `Able/LOADER/FLPLOAD`, `Able/MONCAT/*`,
`Able/-XPL/SYSLITS` and `XPLRunTimeOSX.cpp` (MIT, `jbemond/Software` @
`a237bf2`). Details in [`boot-and-loaders.md`](boot-and-loaders.md) §4.

* NED's `set_up_able_core` builds high core for **host-native** XPL
  programs on the Mac. Booting the real MONITOR binary does not need it:
  MONITOR's own `COLD.BOOT` initialises high core when the magic number is
  absent.
* FLPLOAD's entry 4 (ECOPY, external memory → core) runs the same end of
  load (first-sector configuration check, configuration copy, jump to the
  program) as a floppy boot. Staging MONITOR in external memory and entering
  ECOPY runs the real `.LD-6` code with no floppy emulation.
* **Result:** MONITOR prints `N.E.D. ABLE Series System Monitor - 1
  December 1985`, then reads D100 (F0 head restore) after about 216,000
  instructions. Its catalog reads use MONITOR's own disk driver, so the
  next step is D100 emulation (step B), not a trap of the loader.
* The Release L high-core layout differs from SYSLITS `-7` (prompt at
  `MEM.SIZ` − 136, configuration copy at −189). The `.LD-6` offsets for the
  head positions and magic number fit that layout if the loader sits at
  `MEM.SIZ − 1024`, as `-7` documents.
* Correction to [`roadmap.md`](roadmap.md) "Boot": synthesising the
  post-boot state the way the Mac runtime does is not needed; the loader +
  MONITOR cold boot do it.

## 16. MONITOR to `Ready >` (M1.6 step B)

Sources: Release L image; NED `Able/RTP/DISKREAD`, `DISKSEEK`,
`Able/XPL/DEVUTIL`, `Able/MONCAT/MON`, `Able/-XPL/SYSLITS` (MIT,
`jbemond/Software` @ `a237bf2`). Device details in
[`simulator.md`](simulator.md#devices).

* **D100 is programmed like an FD1771/179x** (command/status, track,
  sector, data; D104 drive select). The command bytes and status masks in
  FLPLOAD and DISKREAD match the WD command set (restore 0–3, seek 20,
  step in 100, read 210/214, force interrupt 320; not ready 200, RNF 20,
  CRC/lost data/not ready 214).
* **No floppy detection uses the index pulse:** `d100_disk_check` forces
  an interrupt and counts index edges in status bit 1 against D3 ticks, so
  the model needs a rotating index and a readable D3 (pending tick → 1).
* **D62 is the non-incrementing external-memory data port**, used by
  MONITOR's `POLL` to size the memory (store 0, read it back, per half
  card).
* **D50 reads wait for a character.** MONITOR's input routine reads D50
  with no CHAR_RDY test; returning the previous character made every key
  repeat about 11 times. Holding the read until a character arrives fixes
  it. **[HYP]** for the hardware mechanism (SYN withheld).
* **Correction** (to §15 and an earlier note in
  [`release-l-image.md`](release-l-image.md)): the boot disks' `MONITOR`
  files do not differ only in the options word. `01-BOOTD`/`02-BOOTF` are
  configured for a SCSI Winchester system device (they stop in a bell loop
  without a SCSI card); `03-SYSTD` is the floppy-system disk.
* **Result:** `03-SYSTD` boots to `Ready >` in about 883,000 instructions;
  `CATALOG` of `18-UTILS` in F1 lists 7 entries, 375 sectors used, 25
  remaining, matching `tools/ned_disk.py`. `OLD CONFIGUR` / `RUN` loads a
  program through the `.LD-6` floppy loader and returns to MONITOR.

## Searched without useful results

* archive.org full-text and metadata search for "synclavier", "new england
  digital" and "ABLE computer NED". The only relevant item is
  `Synclavier-docs`.
* GitHub code search for FPRM, FPSM, D300, "model c", "microcode" and SMR00
  across the Synclavier organisation and `jbemond/Software`. No hits, but
  that repo's files have no extensions and are not indexed; see §8.
* bitsavers.org: no NED directory.
