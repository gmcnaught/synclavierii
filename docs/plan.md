# Project plan: an FPGA Synclavier II

This is the working plan. [`roadmap.md`](roadmap.md) is the one-page
summary. The research behind it is in the other documents under `docs/`.

---

## 1. Goal and scope

**Goal:** a behavioural re-implementation of a **Synclavier II**, first as a
software simulator and then as an FPGA core (target: MiSTer), that runs
original NED software and sounds like the original FM voices.

**In scope (first target system):**

| Area | Target |
|---|---|
| CPU | ABLE **Model B** instruction set (what Release L is compiled for). The Model C extensions come later (milestone 6). |
| Software | **Release L** (June 1986, original keyboard), supplied by the user as a `.simg` |
| Memory | 64K-word internal memory; external memory D60–D63 |
| Devices | PSW/PCW (D1), real-time clock (D3), scientific timer (D16), D4567 multiply/divide, terminal (D50/D51), floppy (D100–D104), FM interface (D160) and voices, original keyboard / button panel |
| I/O on the core | VT100-style terminal, SD-card disk images, MIDI/USB keyboard input, stereo audio |

**Out of scope for now:** poly sampling (PSMT and later), Direct-to-Disk,
Model D (DSM + paging), SMPTE/MIDI subsystems, the Velocity Keyboard, and
gate-level reproduction of the FPRM/FPSM boards.

## 2. Principles

1. **Behavioural, not gate-level.** The CPU only has to match the
   instruction set and roughly match the timing. The microcode PROMs and
   board schematics are references, not prerequisites.
2. **NED's own code is the reference.** Every behaviour is checked against
   NED documentation, NED source (MIT) or NED binaries. Each claim records
   where it came from (see [`sources.md`](sources.md)).
3. **Software simulator first.** The FPGA design is checked against
   instruction traces from the simulator.
4. **Don't ship unlicensed binaries.** Release L has no licence, so users
   supply their own disk images. NED's MIT-licensed material may be
   included, with its notice.
5. **Write down every finding.** New facts go into the relevant `docs/`
   file and the research log.

## 3. System architecture (simulator and core share it)

```
        ┌──────────────────────────────────────────────────────────────┐
        │                        ABLE CPU (Model B)                     │
        │  R0–R17, PC=R17/R16, flags Z C M, PSW/PCW, IRQ/HALT handling  │
        │  micro-cycle: fetch → source READ → destination WRITE         │
        └───────────────┬──────────────────────────────────────────────┘
                        │ bus transaction: (IAB code, RD/WR, data) → SYN
        ┌───────────────┴──────────────────────────────────────────────┐
        │                  Bus / device dispatcher                     │
        │  codes 300–377 → register/memory unit (internal)              │
        │  codes 000–177 → device table; no device = halt (no SYN)      │
        └──┬──────────┬──────────┬───────────┬───────────┬─────────────┘
           │          │          │           │           │
      64K memory   D1 PSW/PCW   D3/D16     D50/D51     D100 floppy   D160 FM ─► voices ─► audio
      D60–63 ext   D4567 mul/div timers    terminal    (or HLE)      keyboard/panel (ORK)
```

* **CPU:** follows [`instruction-set.md`](instruction-set.md) exactly. Model
  C additions sit behind a model switch.
* **Device interface:** `read(dev) -> (value | NO_SYN)`, `write(dev, value)
  -> (ok | NO_SYN)`, and `tick(cycles)` for timers. An interrupt request
  sets a PSW bit (bit 4–15 assignments as documented). NO_SYN halts the CPU
  and reports the device number, as the real machine did.
* **Timing model:** each instruction costs fetch plus source plus
  destination transfers. Start at about 1 µs per instruction, with
  per-device delays where known; tune later (risk R3).

## 4. Milestones

Each milestone has tasks, deliverables and **acceptance criteria**.

### M0. Housekeeping (small)
* Pick the project licence (MIT-compatible).
* Add `.gitignore` and CI that runs `tests/` (GitHub Actions, Python only).
* Agree branch/PR workflow and coding conventions.

**Done when:** CI runs the disassembler tests on every push.

### M1. Software simulator boots Release L to `Ready >`

| # | Task | Reference |
|---|---|---|
| 1.1 | **Done** (`sim/cpu.py`, `docs/simulator.md`). CPU core: decode via the shared tables in `tools/able_disasm.py`; implement all Model B sources and destinations, flags, conditional/relative transfers, PCI literals, post-increment | `instruction-set.md` §2–7 |
| 1.2 | **Done.** PSW/PCW (D1), interrupt entry (R16 as PC, ION/ICS/PCS), INIT state | `instruction-set.md` §8 |
| 1.3 | **Done** (`sim/devices/`). Memory 64K words; external memory D60 (sector), D61 (word), D63 (data, auto-increment) | `boot-and-loaders.md` §3 |
| 1.4 | **Done** (`sim/devices/`), except the live host-console bridge, which comes with the M1.7 tooling (`feed()` and `output` hooks exist). Terminal D50 (data) and D51 (status), bridged to the host console; TTI/TTO interrupts | XPL manual §IX; loaders |
| 1.5 | **Done** (`sim/devices/`). D3 real-time clock (200 Hz interrupt) and D4567 multiply/divide (documented protocol) | `boot-and-loaders.md` §3 |
| 1.6 | Disk: **step A done** (`sim/boot.py`): `MONITOR` staged in external memory and started through the real `.LD-6` ECOPY entry; it prints its banner and halts at its first D100 access (F0 head restore). **Step B** register-level D100–D104 floppy emulation from the FLPLOAD/`.LD-6` code and MONITOR's disk driver | `boot-and-loaders.md` §4, `release-l-image.md` |
| 1.7 | **Done** (`sim/trace.py`) except a live console: instruction history (disassembled), breakpoints, device-access log and counts, HOP-like halt report and memory inspect; `python3 -m sim.boot IMAGE` | — |
| 1.8 | **Started** (`tests/sim/`: 42 CPU, 14 device, 4 trace and 3 boot tests). CPU unit tests: one per source/destination class, flag edge cases (SUB/SBB borrow, rotates, shifts), relative targets | `data/able-opcodes.csv` |

**Deliverables:** `sim/` package, `tests/sim/`, user doc `docs/simulator.md`.
**Done when:**
* Release L `MONITOR` starts from a user-supplied `.simg`, prints the
  `Ready >` prompt, and a `CATALOG` command lists the disk.
* The CPU unit tests pass.

### M2. Run the real-time program; recover the device register maps
| # | Task |
|---|---|
| 2.1 | Load and run `ORK-LM`/`ORK-LFM` (multi-disk executable) under the simulator, with devices stubbed to log every access |
| 2.2 | Reconstruct register maps for **D160 (FM interface)**, the **original keyboard / button panel** and the **D16 timer** from the logs, disassembly of the Release L binaries, and NED's MIT XPL source (later releases; check for differences) |
| 2.3 | Write `docs/devices/<device>.md` for each device: addresses, bit fields, sequences, evidence |
| 2.4 | Minimal behavioural models of the keyboard and panel so the program reaches its main loop |

**Done when:** the real-time program runs its main loop without halting, and
every device it touches has a documented register map.

### M3. FM voice model (software)
| # | Task |
|---|---|
| 3.1 | Turn the SS1–SS7 card analysis (*Synclavier FM.docx*) and NED patents US 4,279,185 and 4,345,500 into a voice spec, `docs/fm-voice.md`: phase accumulator, 256-point waveforms ×32, multiplier and shifter, envelope generator (prescaler + rate + up/down counter), 8-bit MDAC chain, pan law |
| 3.2 | Bit-accurate software model, driven by the D160 writes captured in M2 |
| 3.3 | Render audio from the simulator. Compare against reference recordings (risk R1), tuning the clock, envelope rates and modulation-index scaling |

**Done when:** known Release L timbres render recognisably. Comparison with
real-hardware recordings is the final acceptance step, once recordings exist.

### M4. FPGA core: CPU + memory + terminal + disk
| # | Task |
|---|---|
| 4.1 | Choose the framework: a plain MiSTer template or JTFRAME (see the MiSTer skill in `misterfpga-skill`) |
| 4.2 | ABLE CPU in HDL: three-step micro-cycle state machine, register file, ALU (a '181-style function set is enough), flags |
| 4.3 | **Lockstep verification:** run the same image in an HDL simulator (Verilator) and the software simulator; compare instruction traces |
| 4.4 | Memory in BRAM/SDRAM; external memory in SDRAM/DDR |
| 4.5 | Terminal: a character display on the video output plus PS/2/USB keyboard, or a UART |
| 4.6 | Disk images from the SD card (the M1 high-level boot first, D100 emulation later) |

**Done when:** the core on real MiSTer hardware boots Release L to `Ready >`
and lists the catalog.

### M5. FPGA FM voices, keyboard and audio
* Implement the M3 voice spec in HDL (number of voices configurable);
  audio out.
* MIDI/USB → original-keyboard and panel emulation; show panel state
  (on-screen or LEDs).

**Done when:** the real-time program plays FM timbres from a MIDI keyboard
on MiSTer.

### M6. Model C extensions (optional)
* Add D10 (`rpc` repeat counter, `ppc` link), R12 stack (`MR12D`) and
  ADC/SBB behind the model switch, using
  [`model-c-runtime-analysis.md`](model-c-runtime-analysis.md).
* Validate by running the MIT `*RTC-7` runtime code paths, and later Model
  C software if images turn up.

## 5. Verification strategy

| Level | Method | Reference |
|---|---|---|
| Decode | Disassembler matches NED listings (541/541 words, 78/78 targets) | `tests/test_able_disasm.py` |
| CPU semantics | Unit tests per instruction class and flag rule | `instruction-set.md`, `data/able-opcodes.csv` |
| Real code | Boot Release L; run the loaders and runtime routines | Release L image, `jbemond/Software` |
| Devices | Behaviour matches NED driver code (loaders, XPL libraries) | `boot-and-loaders.md`, `docs/devices/` |
| HDL | Lockstep trace comparison with the software simulator | M4.3 |
| Sound | A/B against real-hardware recordings of known patches | M3.3, help needed |

## 6. Planned repository layout

```
docs/            research + specs (existing), plus devices/, fm-voice.md, simulator.md
data/            CSV tables (existing)
tools/           disassembler, disk tool (existing)
sim/             software simulator (M1–M3)
  cpu.py  bus.py  devices/  boot.py  trace.py
hdl/             FPGA core (M4–M5)
tests/           disassembler tests (existing), sim/, hdl/
boards/          FPRM/FPSM reverse-engineering notes (existing)
```

Implementation language for `sim/`: **Python first**, for speed of
development and because it shares the decode tables with `tools/`. If the
real-time program needs more speed, hot paths can be ported to C or a
compiled extension (decision D3).

## 7. Risks and mitigations

| # | Risk | Mitigation |
|---|---|---|
| R1 | Exact FM sound (clock, envelope tables, scaling) can't be confirmed without hardware | Build from the card analysis and patents; ask owners for recordings of known patches; keep parameters adjustable |
| R2 | Release L device behaviour differs from what NED's later-release source shows | Prefer evidence from Release L binary disassembly and logs; record differences per release |
| R3 | Real-time software sensitive to CPU throughput or bus timing | Configurable timing model; measure timer-interrupt behaviour in the simulator; owner bus measurements if available |
| R4 | Python simulator too slow for real-time code | Profile; port the CPU loop to C; batch device ticks |
| R5 | Keyboard and panel protocol harder than expected | Start with the minimal model needed to reach the main loop; expand with M2 evidence |
| R6 | Licensing of software images | Users supply images; only MIT material in the repo |

## 8. Help wanted from Synclavier owners

In priority order (details in [`bench-checklist.md`](bench-checklist.md)):
1. **Audio recordings** of known Release L timbres and notes (for M3).
2. **Dumps** of the PROMs (FPSM SMR/DDE/INITROM, FPRM U18/U28) and the
   **MFC/D40Q boot ROM**.
3. High-resolution board photos; edge-connector measurements.
4. Later release disk images, especially ones compiled for Model C.

## 9. Decisions needed

| # | Decision | Recommendation | Status |
|---|---|---|---|
| D1 | Project licence | MIT (matches NED's released software) | **Decided:** MIT, see `LICENSE` |
| D2 | Workflow | Feature branches + PRs into `main`, with CI on PRs | **Decided:** see `CONTRIBUTING.md` and `.github/workflows/tests.yml` |
| D3 | Simulator language | Python first; C for hot paths if needed | Open |
| D4 | FPGA framework | Decide at M4: plain MiSTer template vs JTFRAME | Open |
| D5 | First keyboard target | ORK (original keyboard) as used by Release L | Open |

## 10. Next action

M0, M1.1–1.5, M1.6 step A and M1.7 are done. Next: **M1.6 step B**, the
D100–D104 floppy controller backed by the `.simg`, so MONITOR's cold boot
can restore the heads, read the catalog and reach `Ready >`.
