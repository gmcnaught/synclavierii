# Synclavier for MiSTer

A behavioural FPGA core of the New England Digital **Synclavier** for the
[MiSTer](https://github.com/MiSTer-devel) (DE10-Nano), with a Python
simulator it is checked against. It runs NED's original software,
unmodified:

* **Release L** (1986) on a **Synclavier II** (ABLE Model B CPU), booting
  from floppy images;
* **Release 5.3** (2021, the last release) on a **3200 / 6400 / 9600**
  (ABLE Model D CPU), booting from a SCSI hard-disk image.

The project started as reverse engineering of the Model C "Fast Processor"
CPU boards (FPRM-185 / FPSM-185); that material is kept below and in
[`boards/`](boards/). The core does not copy the boards gate for gate: it
implements the instruction set and the devices as NED's software uses
them.

You need your own NED disk images (Release L from
`Synclavier/Synclavier_Distributions`, Release 5.3 from a Synclavier³
download); none are included. See [Licence and provenance](#licence-and-provenance).

## Status (November 2026)

All of the following runs on a MiSTer:

| Part | Status | Docs |
|---|---|---|
| ABLE CPU, Models B, C, D | HDL and simulator agree instruction by instruction (random programs, MONITOR, ORK-LM, SYN-5.3) | [`instruction-set.md`](docs/instruction-set.md), [`hdl.md`](docs/hdl.md) |
| Release L | Boots from SD floppy images to `Ready >`; the real-time program ORK-LM plays FM timbres from MIDI | [`release-l-image.md`](docs/release-l-image.md) |
| Release 5.3 | Boots MONITOR 5.3 from a W0 image and starts SYN-5.3 (Main Menu in about 6 s); timbre banks, sound files | [`release-5.3.md`](docs/release-5.3.md) |
| FM synthesis | 8 voices, or 32 (a 9600); time-multiplexed engine; HDL output equals the simulator's sample for sample | [`fm-voice.md`](docs/fm-voice.md) |
| Poly sampling | 32 stereo voices per poly bin, 1 bin (a 3200) or 2 (a 6400); up to 224 MB of poly memory in DDR3; sound files load over SCSI and play | [`poly-synth.md`](docs/poly-synth.md) |
| Keyboards and panel | Original keyboard (ORK) for Release L, velocity/pressure keyboard (VPK) for 5.3; MIDI notes, velocity, pressure, wheels, pads and pots mapped to them; on-screen panel clicked with the mouse | [`devices/`](docs/devices/), [`mister/README.md`](mister/README.md) |
| MIDI subsystem card | D70–D73: SYN-5.3 handles MIDI in (routing, recording, sync) and MIDI out over MidiLink | [`d70-midi-subsystem.md`](docs/devices/d70-midi-subsystem.md) |
| Disks | Two floppies, SCSI W0: and W1: from SD card images, with modelled disk timing | [`hdl.md`](docs/hdl.md) |
| Terminal | VT100 subset on the video output with a PS/2 keyboard; VT640 (Tektronix 4010) graphics and the D44 mouse for SYN-5.3's graphic screens | [`vt640-graphics-terminal.md`](docs/devices/vt640-graphics-terminal.md) |

Not done yet:

* **Exact sound.** DAC, envelope and mix details are modelled from NED
  documentation and source; they have not been compared with recordings of
  a real instrument.
* **Launchkey defaults** for pads and pots are not checked against a
  captured device.
* No packaged release: build the RBF yourself or take it from a CI run.

Not planned: Direct-to-Disk, sample-to-memory recording (no audio input),
mono sampling, the Macintosh terminal.

The one-page summary is [`docs/roadmap.md`](docs/roadmap.md); milestones
M0–M15, with acceptance criteria and results, are in
[`docs/plan.md`](docs/plan.md).

## Using the core

[`mister/README.md`](mister/README.md) has the build, the image tools and
the MIDI mapping. In short, for Release 5.3:

```bash
python3 tools/w0_image.py "Synclavier³.app/Contents/Resources/W0 Disk Image.simg" out/w53
```

writes `W0-53.IMG` (the hard disk) and `W0-53.SST` (a state image that
sets up the machine). Copy both to `games/Synclavier/` and load them with
an MGL; options give 32 FM voices (`--fm-voices 32`), more poly memory
(`--poly-mb`), a second poly bin (`--poly-bins 2`), the MIDI card
(`--midi`), a VT640 (`--vt640`) or a second disk (`--w1`). Set the MiSTer
UART to MidiLink for MIDI.

Build the core with `mister/build.sh` (Quartus Lite 17.0) or take the
`synclavier-rbf` artifact from a **Build RBF** run on `main`.

## How it is checked

* **Simulator** (`sim/`, Python standard library only): CPU, devices, FM
  and poly voices. It is the reference model; see
  [`simulator.md`](docs/simulator.md).
* **Lockstep** (`sim/lockstep.py`, Verilator benches in `hdl/sim/`): the
  HDL runs the same program as the simulator and every instruction,
  device access and audio sample is compared, up to full SYN-5.3 boots of
  about 20 million instructions.
* **Tests** (`tests/`): run on every pull request by
  `.github/workflows/tests.yml`; `build-rbf.yml` compiles the core and
  fails on negative timing slack.
* **Hardware**: each milestone is then run on a MiSTer
  (`scripts/mister/`: load the core, type keys, send MIDI, read the screen
  back).

## Documentation

| Document | Contents |
|---|---|
| [`docs/roadmap.md`](docs/roadmap.md) | One-page summary: what works, what is next, open gaps |
| [`docs/plan.md`](docs/plan.md) | Project plan: architecture, milestones M0–M15, verification, risks, decisions |
| [`docs/hdl.md`](docs/hdl.md) | The FPGA core: CPU, devices, voice engine, MiSTer top level, lockstep |
| [`docs/simulator.md`](docs/simulator.md) | The Python simulator: use, behaviour, choices the manuals leave open |
| [`docs/instruction-set.md`](docs/instruction-set.md) | Full ABLE instruction set with NED mnemonics and the Model C/D extensions |
| [`docs/able-reference.md`](docs/able-reference.md) | Architecture, the 72-pin EZbuss pinout, processor models and slots |
| [`docs/boot-and-loaders.md`](docs/boot-and-loaders.md) | Boot chain (boot ROM → `.LD-7` → MONITOR) and loader protocols |
| [`docs/release-l-image.md`](docs/release-l-image.md), [`docs/release-5.3.md`](docs/release-5.3.md) | The two software releases: disk formats, what each needs from the hardware |
| [`docs/realtime-program.md`](docs/realtime-program.md) | The real-time program (ORK-LM, SYN-5.3) and the devices it drives |
| [`docs/fm-voice.md`](docs/fm-voice.md), [`docs/poly-synth.md`](docs/poly-synth.md) | FM voices and poly sampling: registers, timing, memory |
| [`docs/devices/`](docs/devices/) | Register maps: keyboards, FM interface, control voltages, MIDI card, VT640 |
| [`docs/timbre-libraries.md`](docs/timbre-libraries.md) | Timbre bank formats and how to load NED libraries |
| [`docs/model-c-runtime-analysis.md`](docs/model-c-runtime-analysis.md) | Disassembly of NED's Model B/C/D runtime packages |
| [`docs/sources.md`](docs/sources.md) | Every source, pinned by URL, commit and checksum |
| [`docs/research-log.md`](docs/research-log.md) | How the findings were reached, including corrections |
| [`docs/bench-checklist.md`](docs/bench-checklist.md) | What owners of real hardware could measure |
| [`tools/`](tools/README.md) | Disassembler, NED disk lister/extractor, image builders, table generators |

## Repository layout

```
docs/          specifications, plan, sources (above)
sim/           Python simulator: cpu.py, system.py, fm.py, voice.py, lockstep.py
  devices/     floppy, SCSI, external memory, keyboards, FM, poly, MIDI, mouse, ...
hdl/           the core: able_cpu.sv, able_system.sv, voice_clock.sv
  dev/         one module per device (dev_fm.sv, dev_poly.sv, dev_scsi.sv, ...)
  core/        MiSTer-side logic: boot loader, SD disks, terminal and panel
               display, MIDI input, mouse
  board/       DDR3 access
  sim/         Verilator lockstep benches and unit testbenches
mister/        Quartus project (Template_MiSTer; sys/ is GPL-2.0), build.sh, CI runner
tools/         able_disasm.py, ned_disk.py, w0_image.py, state_image.py, generators
scripts/mister/  hardware test driver for a MiSTer on the network
tests/         simulator, HDL lockstep and tool tests (stdlib only + Verilator)
data/          CSVs: EZbuss pinout, opcode map, board netlist
boards/        FPRM-185 and FPSM-185: BOMs, inferred netlists, block schematics
third_party/   8x8 font (public domain)
```

## The Model C CPU boards

The board-level reverse engineering the project began with. The core does
not depend on it.

| Board | Role | Folder |
|---|---|---|
| **FPRM-185** | Fast Processor **Register Module**. 16-bit ALU (4× 74F181 + 74S182), 16×16 register file (4× CY27S07), C/Z/M flags, memory-address and data-bus interface. Used in **Model C and Model D**. Bin slot 13. | [`boards/fprm-185/`](boards/fprm-185/README.md) |
| **FPSM-185** | Fast Processor **Sequencer Module**. ≈28-bit pipelined microcode (SMR00–03 PROMs), next-address sequencer, opcode-dispatch PROMs, interrupt priority, delay-line timing. **Model C** only (Model D uses the DSM instead). Bin slot 14. | [`boards/fpsm-185/`](boards/fpsm-185/README.md) |

> **Board status: first pass.** The BOMs and chip identities are solid. The
> block schematics and netlists are **inferred** from 822×622 photos plus
> NED documentation. Every connection is tagged **[STD]** (standard
> topology), **[OBS]** (seen in the photo) or **[HYP]** (hypothesis). No
> physical hardware has been measured, no PROMs have been read, and no
> public schematics exist as far as we could find.

### How the CPU works (short version)

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

### Processor models

| Model | Cards | Used in |
|---|---|---|
| B | D1 sequencer + D300 register module | Original Synclavier II |
| **C** | **FPSM + FPRM** ("Fast Processor") | PSMT, Direct-to-Disk, Poly systems, some Synclavier IIs |
| D | DSM + FPRM | 3200 / 6400 / 9600, PostPro, PostPro SD |

### Open questions

* **PROM contents:** FPRM U18 and U28; FPSM SMR00–03, DDE (U22/U23) and
  INITROM. These hold the microcode and decode tables. No public dumps exist.
* The **P1 edge pin-out** on these cards, compared with the documented ABLE
  EZbuss, starting with GND, +5 V and the Z/C/MIN pins (60, 62, 64).
* What the **J1 34-pin ribbons** connect to.
* Which FPSM chips drive ADR0–7: the '153 multiplexers or U2/U3. Are U32/U33 the Model C repeat counter?
* Whether relative or untaken transfers also update the D10 link (`ppc`). No NED software depends on it. Also the exact Model C interrupt-entry microsequence.
* The MFC/D40Q boot ROM image (not in any source found). Its function is
  known (load `MONITOR` from the F0 catalog and start it), and the core's
  boot loader (`hdl/core/boot_loader.sv`) does that instead.
* Exact identity of a few chips (FPRM U41 and U8; FPSM U4, U52 and U73) and of
  the PROMs under their labels.

### Help from hardware owners

| Item | Why |
|---|---|
| **Recordings** of known timbres and sound files on a real instrument | to match the core's FM and poly output to the original |
| **PROM reads** | the only route to a gate-accurate model of the boards |
| **High-resolution photos** (≥600 dpi, both sides, square-on) | most traces could then be followed |
| **Edge-finger and backplane continuity map** | procedure in [`docs/bench-checklist.md`](docs/bench-checklist.md) §3–4; results go in `data/ezbuss-pinout.csv` |

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

## Licence and provenance

Synclavier® is a registered trademark of Synclavier Digital. This is an
independent hobby project; it is not affiliated with, endorsed by or
supported by Synclavier Digital or New England Digital.

| Part | Licence |
|---|---|
| This project's own files (HDL, simulator, tools, tests, docs) | MIT, [`LICENSE`](LICENSE) |
| `mister/sys/` (MiSTer framework, unchanged) | GPL-2.0, [`mister/sys/LICENSE-GPL2`](mister/sys/LICENSE-GPL2) |
| `third_party/font8x8/` (Daniel Hepper) | Public domain (header of `font8x8_basic.h`) |
| `tests/fixtures/NED-SCSI.LST` (NED assembler listing) | MIT, [`tests/fixtures/LICENSE-NED-Software`](tests/fixtures/LICENSE-NED-Software) |

A built core (`.rbf`) contains `mister/sys/`, so a distributed RBF is a
combined work under **GPL-2.0**; the MIT files remain usable on their own
under MIT.

Where the information comes from:

* **NED documentation** that is published on archive.org and in the
  `Synclavier/Documentation` GitHub repository (MIT), summarised here, not
  copied.
* **NED software source** published by Synclavier Digital under the MIT
  licence (`jbemond/Software`), read to match the hardware behaviour the
  software expects.
* **Binary analysis for compatibility** of NED disk images (Release L from
  `Synclavier/Synclavier_Distributions`; Release 5.3 from a Synclavier³
  download), done on lawfully obtained copies. Only descriptions of formats
  and behaviour are in the repository.

[`docs/sources.md`](docs/sources.md) pins every source by URL, commit,
path and checksum, and says what each was used for.

**Not included**, and never committed: NED disk images (`*.simg`), timbre
and sound files (`*.stmb`, `*.ssnd`, `*.sprg`), images built from them
(`*.IMG`, `*.SST`), ROMs and board photos. Users supply their own disk
images; the docs say how to build the core's images from them.
`tests/test_repo_hygiene.py` fails if one of these file types is added.

Rights holders: if you believe something here should not be, please open
an issue on this repository and it will be dealt with promptly.

Contribution workflow: [`CONTRIBUTING.md`](CONTRIBUTING.md); see also
[`NOTICE`](NOTICE).
