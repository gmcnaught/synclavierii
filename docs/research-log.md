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

## 17. Release L real-time program runs (M2.1)

Details in [`realtime-program.md`](realtime-program.md).

* **`PLAY` cannot run from the floppies alone:** it opens the SCRIPT
  compiler (`.SCOM-6`, `.SSYM-6`, `.SCON-6`), which exists only inside the
  6-floppy `.SYSTEM` install archive. Release L is a Winchester system.
* **Hand-off:** MONITOR's own `RUN` of a small program is stopped at the
  loader entry and redirected to ECOPY with the RTP staged in external
  memory, so the real loader places the object code and the 519-sector
  swap file.
* **Correction:** the Release L system configurations are **Model C**
  (options 141031/141011, processor type 2), not Model B as first written
  in [`release-l-image.md`](release-l-image.md) §3.3. The binaries are
  Model B code.
* **ORK-LM probes for a Model C** with `IM(5) TO ADC0` after clearing R0
  and C, and enables `D10` repeat loops if R0 changed. With the Model C
  configuration it ran Model C paths and wrote D10; configured as Model B
  it still runs the probe, so a Model B must leave R0 at 0 for 270–277.
* **D4567: writing D5 clears D4** (NED `XPL.h`). ORK-LM divides with only
  `R0 TO D5; IM(20) TO D7`; with a stale D4 the quotient was wrong, a
  bitmap routine wrote into code, and the program ran wild after ~2 s.
* **Result:** ORK-LM draws its VT100 welcome screen and runs its main loop
  for 10 simulated seconds without a halt. Devices touched: D3, D4–D7,
  D100–D104, D130/D131, D160, D161, D163, D164, D165.

## 18. Register maps of the synthesizer devices (M2.2)

Source: NED's later RTP source (`Able/SYNLITS`, `SYNRSOU`, `SYNCOMS`; MIT),
checked against the Release L ORK-LM log. Maps in [`devices/`](devices/).

* **D130/D131** follow `076-OLDI` ("release-M modules", 5/15/86) exactly:
  octave scan `20, 100…105` with negative key logic, panels `10+I/110+I`,
  display strobe `40`. MONITOR's "keyboard type" check is a read of
  octave 5 (idle 1). The M2.1 probe's 0 made every key read as held.
* **D160 read** carries three things: bit 0 channel-exists (voice
  detection, one probe per 16-channel card), bit 1 the external clock
  input (the main-loop poll), bits 2–7 the old panel's switches.
* **D163** is the old panel's A/D converter (write `2 + 4·ch`, read the
  value, `3` starts a conversion) and `1` toggles the external clock out;
  this explains ORK-LM's writes 2, 3, 6, 22.
* **D164/D165** are the CV board's DAC select/value.
* ORK-LM loads four 256-point wave memories at start (`TIM` 32–35, `ZMA`,
  256 × `MEM`). A key press is read but plays nothing yet (no timbre
  recalled).

## 19. Button map and the first note (M2.4)

* `075-OLDL` (5/15/86) is the physical-to-logical button table of the
  original panel: banks at PBN 96–103, timbre recall 104–111.
* At start-up ORK-LM lights bank 0 / timbre 0 but has read no bank; keys
  are silent. With `06-TIMBD` swapped into F0, `bank.0` reads 34 sectors
  of `.NEWDATA` and `timb.0` loads the timbre; C4 then starts 4 voices.
* ORK-LM writes whole channel words (`QUELITS` format: state, splice wave
  memory 8 + voice, channel) to D160. (The 16-bit `ONU`/`NNU`/`INC` values
  first reported here were a simulator fault; see §21.)

## 20. Later NED timbre libraries (M3 groundwork)

Details in [`timbre-libraries.md`](timbre-libraries.md).

* The user-supplied `Original-NED-Sample-Patch-Libraries` are 92 banks
  (2022 export): 462 of 471 timbres use sound files; 9 are FM-only, with
  parameters in physical units in per-entry text files.
* Release L's `.NEWDATA` is 8 banks × 49 sectors; a bank button reads 32.
* A later `.stmb` bank written over bank 0 loads in Release L ORK-LM: it
  reports a missing sound file for the sampled timbre, computes wave
  memories for the FM ones, and plays 3 of 7. Interpretation of the other
  parameters is unverified, so these are not calibration data yet.

## 21. Pitch registers decoded (M3.1a)

* **Correction:** the simulator's RTP hand-off (`RUN CONFIGUR`, redirected)
  never set MONITOR's `PLAY` file pointers, so ORK-LM read its tables file
  `.STAB-6` from sector 0 of F0 (catalog + MONITOR). The 16-bit, byte-
  swapped pitch words, the 4-partial timbre 0 and some timbre results in
  §19/§20 came from those wrong tables. Fixed: `sim.rtp` runs `SET RTP` +
  `PLAY` first; PLAY records `.STAB-6` at `MEM.SIZ` − 55…−53 (length,
  sector 297, device F0) and the RTP at −52…−50 before failing on the
  missing SCRIPT compiler.
* `.STAB-6` holds the frequency tables (sectors 0–3: 1,024 entries, 4–7:
  two 512-entry tables), `inc << 8 | divisor`.
* Release L's frequency routine (015322) matches NED's `COMPUTE.OSYN.FREQ`
  and patent US 4,345,500 (Do = 256 − Divisor + Increment − 1/16).
* f = 162.764 Hz × 2^ONU × (INC + 1) / (256 − NNU + INC >> 3); key 45 =
  440.00 Hz, middle C (36) = 261.64 Hz. Details in [`fm-voice.md`](fm-voice.md).

## 22. Envelope, index, pan and wave memory registers (M3.1a)

* NED `302-SUB2`/`138-PRE1`: interpolator divisor = 256 − DIV, adder =
  ADD + 1; `COMPUTE.INTERP.NUMBERS` turns a time into (DIV, ADD) assuming
  a clock of about 192 kHz. `382-EXP`: exponential decays are software,
  `EADD` × (1 − 12.5/T) every 10 ms.
* D160 bit 0 doubles as "limit reached" when function 12 is selected
  (`144-TIM3`). Release L polls it the same way (076614). Modelled in
  `FMInterface`; ORK-LM now detects the end of a final decay and clears
  the voice. The `ELIM` = 0 rewrites (345 a second) and the `EADD`
  exponential seen in earlier captures came from the old model never
  reporting the limit.
* `ISHC` = pan (bits 7–2) + index shift (1–0); `TIM` = 32 + wave memory;
  `ZMA`/`MEM` load 256 bytes with an auto-incrementing address.
* Observation: in `06-TIMBD`, bank 0 timbres 0–7 and timbre 0 of banks
  1–7 all load the same wave memory and the same envelope (attack 0,
  sustain = peak, no index envelope). Not investigated yet.

## 23. Integer voice model and audio (M3.2)

* NED `198-SYN2` `COMPUTE.WAVE`: wave memory samples are unsigned 8-bit,
  scaled to 0–255 symmetrically about the DC point; a flat wave is 128.
* Release L `06-TIMBD` bank 0 timbre 0 is a pure sine: wave memory 4
  (`TIM` 044) holds one cycle (127, 152, 176, … 255 at point 64); its
  harmonics 2–8 are below 0.1 % of the fundamental.
* `.STAB-6` increments exceed their divisors for half of each octave
  (A 440: 123/91). So the oscillator cannot be "one accumulator wrap per
  tick of 256 × 128 × K"; the real clock is faster or the structure
  differs. The model keeps the verified step rate and allows two pulses
  per tick.
* `sim/voice.py` renders the register log; `sim.rtp --wav`. Checked: pitch,
  FM sidebands vs index, the Release L chord. The sine ROM, DAC laws, pan
  law and analog reconstruction are choices (`fm-voice.md`).

## 24. HDL CPU in lockstep (M4.2, M4.3)

* `hdl/able_cpu.sv`: Model B CPU, FETCH/DECODE/SRC/EXEC/END, about 4.5
  clocks per instruction. Verilator replays traces recorded by
  `sim/lockstep.py` (device values, interrupt timing) and compares every
  instruction.
* Agreement: 300 random programs (all 256 source and 256 destination codes
  executed, 1,263 interrupt entries), MONITOR cold boot +
  `CATALOG` (1,363,060 instructions), ORK-LM start-up and main loop
  (6,000,000). Single-bit HDL mutations (carry rules, ION clearing, PC
  post-increment) are caught. [`hdl.md`](hdl.md).
* HDL devices D3, D4567, D50/D51, D60–D63 (`hdl/able_system.sv`) count the
  CPU's simulated time (333 ns per transfer, ticked before the interrupt
  check), so they agree with the Python devices exactly: MONITOR boot +
  `CATALOG` with input typed during a held D50 read, ORK-LM from a mid-run
  device state (6M instructions, 4.806 s), and a device test program.
* HDL D100 floppy controller (`dev_floppy.sv`): agrees on MONITOR's boot,
  ORK-LM with a timbre recall and a held note (35 sector reads), and a
  floppy program with a sector write and read-back. A sector copy to or
  from the media RAM stalls floppy accesses without simulated time, which
  keeps it identical to Python's instant copy.
* HDL D130/D131 and D160–D165: ORK-LM's timbre recall and note (attack
  and release polled through D160 bit 0) agree with no device left to the
  trace. One HDL bug found by lockstep: the 192 kHz clock remainder
  (`rem + 24 × ns`, up to 148,975) overflowed 17 bits and dropped
  interpolator clocks; the release then ended late.

## Searched without useful results

* archive.org full-text and metadata search for "synclavier", "new england
  digital" and "ABLE computer NED". The only relevant item is
  `Synclavier-docs`.
* GitHub code search for FPRM, FPSM, D300, "model c", "microcode" and SMR00
  across the Synclavier organisation and `jbemond/Software`. No hits, but
  that repo's files have no extensions and are not indexed; see §8.
* bitsavers.org: no NED directory.
