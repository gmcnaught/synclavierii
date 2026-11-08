# Roadmap: toward an FPGA Synclavier II

*One-page summary. The detailed plan, with tasks, acceptance criteria, verification, risks and decisions, is in [`plan.md`](plan.md).*

Goal: a **behavioural** FPGA implementation (for example a MiSTer core) of a
Synclavier II: ABLE CPU, memory, terminal, disk, FM voices and keyboard,
running original NED software.

A gate-level copy of the FPRM/FPSM boards is **not** required. An
instruction-level CPU is enough, so the microcode PROMs, board schematics
and boot ROM image are useful references but not prerequisites.

## What we have

| Piece | Status | Where |
|---|---|---|
| CPU instruction set (Model B; Model C extensions) | Complete; disassembler matches NED listings | [`instruction-set.md`](instruction-set.md), [`model-c-runtime-analysis.md`](model-c-runtime-analysis.md) |
| Software | Release L disks (Model B binaries); MIT-licensed NED source and tools (later releases) | [`release-l-image.md`](release-l-image.md), [`sources.md`](sources.md) |
| Boot | High-level emulation: load `MONITOR`, synthesise the post-boot core state (as NED's Mac runtime does) | [`boot-and-loaders.md`](boot-and-loaders.md) |
| Bus and devices | EZbuss pinout; D4567, D24–D27, D60–D63, PSW/PCW protocols | [`able-reference.md`](able-reference.md), [`boot-and-loaders.md`](boot-and-loaders.md) |
| FM voice hardware | Card-level analysis (SS1–SS7): 8-bit paths, 256-point waveforms, multiplier and shifter, envelope generator, 8-bit MDACs; NED patents US 4,279,185 and 4,345,500 | `Synclavier/Documentation`: *Synclavier FM.docx* (community analysis) |

## Gaps (in order of risk)

1. **Exact FM voice behaviour:** sample rate and clock, envelope rate
   tables, modulation-index scaling, waveform-bank selection. Needs
   recordings from a real Synclavier II playing known patches.
2. **Device register maps** for the FM interface (D160 → SS4), the
   original keyboard and button panel, the D3/D16 timers, D50/D51 terminal
   and D100 floppy. Work these out from NED's MIT source plus disassembly of
   the Release L real-time program, checking for differences between releases.
3. **Timing:** the real-time software assumes about 1 µs per instruction,
   asynchronous SYN-handshaked transfers and 5 ms timer interrupts. The core
   needs approximately correct throughput, not just correct results.
4. **Keyboard and panel:** emulate the ORK keys, buttons, lights, knob and
   ribbon; map MIDI/USB input; show the panel state.
5. **Terminal and storage:** VT100-style terminal; SD-backed `.simg` disks
   (floppy-controller emulation or a disk-call trap).
6. **Validation reference:** no runnable emulator exists to compare
   against, hence milestone 1.
7. **Distribution:** Release L binaries carry no licence, so a core ships
   without software and users supply disk images. NED's later software is MIT.

## Milestones

| # | Milestone | Needs hardware? |
|---|---|---|
| 1 | **Software simulator** (instruction-level, stand-in devices): boot Release L `MONITOR` to `Ready >` | No |
| 2 | Run the Release L real-time program with stubbed devices; log the device accesses it makes, giving the register maps (gap 2) | No |
| 3 | Software FM voice model from the card analysis and patents; tune against recordings | Recordings help |
| 4 | FPGA core: CPU + memory + terminal + SD disk, booting to `Ready >` | No |
| 5 | FPGA FM voices, MIDI keyboard input, audio out | Recordings help |
| 6 | Optional: Model C extensions (D10 repeat/link, R12 stack, ADC/SBB) for later software | No |

Hardware owners can help at any point. See [`bench-checklist.md`](bench-checklist.md),
especially the PROM dumps and recordings of known patches.
