# Project plan: an FPGA Synclavier

This is the working plan. [`roadmap.md`](roadmap.md) is the one-page
summary. The research behind it is in the other documents under `docs/`;
the history of how each milestone was reached is in
[`research-log.md`](research-log.md) and the per-target progress notes
([`release-5.3.md`](release-5.3.md) §4, [`hdl.md`](hdl.md)).

---

## 1. Goal and scope

**Goal:** a behavioural re-implementation of the New England Digital
Synclavier, first as a software simulator (`sim/`) and then as a MiSTer
FPGA core (`hdl/`, `mister/`), that runs original NED software and sounds
like the original voices.

The core has two targets, chosen at build/boot time:

| Target | CPU | Software | Storage | Voices |
|---|---|---|---|---|
| **Synclavier II, Release L** (1986) | ABLE Model B | `ORK-LM` (user-supplied `.simg`, no licence) | floppies F0/F1 + state image | 8 FM |
| **3200/6400/9600, Release 5.3.0** (2021/03/09) | ABLE Model D (Model C instructions + D11 paging) | `SYN-5.3` from Synclavier³'s W0 image (user-supplied); source is NED's MIT tree | SCSI W0 on the SD card + state image | 8 FM, 32 poly sampling (stereo/panning), 32 MB poly memory |

Release L runs on the original keyboard (ORK) model, Release 5.3 on the
velocity/pressure keyboard (VPK) model; both are driven from MIDI. A VT100
terminal is on the video output.

**In scope next** (section 4, M8–M12): the MIDI subsystem card, 32 FM
voices, larger poly memory, SCSI load timing, a second SCSI disk, the
graphics terminal and mouse.

**Out of scope:**
* **Direct-to-Disk:** driven through the D115 RS422 board to a separate
  68K machine whose firmware is not available.
* **Sample-to-memory (STM) recording:** needs an audio input the standard
  MiSTer does not have.
* **Mono sampling (D66/D67):** SYN-5.3 is compiled without it (`inc.mono = 0`).
* **Macintosh protocol / terminal:** the core stays on NED/Able-era
  hardware ([`release-5.3.md`](release-5.3.md) §5).
* Gate-level reproduction of the FPRM/FPSM boards.

## 2. Principles

1. **Behavioural, not gate-level.** The CPU matches the instruction set and
   roughly matches the timing. Microcode PROMs and schematics are
   references, not prerequisites.
2. **NED's own code is the reference.** Every behaviour is checked against
   NED documentation, NED source (MIT) or NED binaries, tagged [OBS] /
   [INF] / [UNK], with its source (see [`sources.md`](sources.md)).
3. **Simulator first, then HDL in lockstep.** Each device is modelled in
   Python, then in HDL, and the HDL is checked against the Python model
   instruction by instruction (`sim/lockstep.py`, `hdl/sim/`).
4. **Don't ship unlicensed binaries.** Users supply Release L and
   Synclavier³ images; only MIT material is in the repository.
5. **Write down every finding** in the relevant `docs/` file.

## 3. System architecture

```
   ABLE CPU (Model B / C / D, runtime switch)  ── code_cache (Model D pages)
        │ bus transaction (device code, RD/WR, data); no device = halt
   Device dispatcher
        ├─ 64K internal memory; D60–D63 external memory (DDR3)
        ├─ D1 PSW/PCW, D2, D3 clock, D4567 mul/div, D10/D11 (Model C/D), D57 options
        ├─ D50/D51 terminal ── term_display (VT100 subset) + PS/2 keyboard
        ├─ D100–D104 floppy (SD F0/F1)      D24–D27 SCSI host + W0 disk (SD S3)
        ├─ D130/D131 ORK keyboard + panel ◄─ midi_in (UART/MidiLink), panel mouse
        ├─ D160–D165 FM interface + voice engine (8–32) ─┐
        └─ D154–D157 poly ─► dev_poly (32) + poly memory (DDR3) ─┴─► audio (48 kHz)
```

The throttle keeps simulated time in step with real time; the status line
shows lag, audio underruns and MIDI activity. Details: [`hdl.md`](hdl.md),
[`simulator.md`](simulator.md).

## 4. Milestones

### Done

| # | Milestone | Acceptance | Where |
|---|---|---|---|
| M0 | Housekeeping: MIT licence, CI, branch/PR workflow | CI on every push | `LICENSE`, `CONTRIBUTING.md`, `.github/workflows/` |
| M1 | Simulator boots Release L `MONITOR` to `Ready >`; `CATALOG` | passes | `sim/`, [`simulator.md`](simulator.md) |
| M2 | Release L real-time program runs; register maps of every device it touches | passes | [`realtime-program.md`](realtime-program.md), [`devices/`](devices/) |
| M3 | FM voice model; pitch verified (A3 = 440.00 Hz); WAV rendering | done except tuning against recordings (M3.3) | [`fm-voice.md`](fm-voice.md), `sim/voice.py` |
| M4 | FPGA core: CPU, memory, terminal, SD floppies; boots Release L to `Ready >` on a MiSTer | passes on hardware (PR #21) | [`hdl.md`](hdl.md), `mister/` |
| M5 | FPGA FM voices, MIDI → keyboard and panel, audio, panel display and mouse; ORK-LM plays on MiSTer | passes on hardware (PR #20–#28) | `hdl/dev/fm_voices.sv`, `hdl/core/midi_in.sv` |
| M6 | Model C extensions (D10, R12 stack, ADC/SBB) | merged into M7.1 | [`model-c-runtime-analysis.md`](model-c-runtime-analysis.md) |
| M7 | Release 5.3: Model D, SCSI W0 boot, SYN-5.3 Main Menu, timbre banks, FM notes from MIDI; poly sampling (M7.7) | passes on hardware (.204, PR #30–#33) | [`release-5.3.md`](release-5.3.md), [`poly-synth.md`](poly-synth.md) |
| M8a | Velocity/pressure keyboard (VPK, D130/D131) for Release 5.3, MIDI-mapped (Launchkey keys, pads, pots, wheels); on-screen VPK panel | board lockstep; on hardware: boot, program change, pitch bend (PR #34). Open: Launchkey pad/pot numbers are assumed until a MIDI capture | [`devices/d130-velocity-keyboard.md`](devices/d130-velocity-keyboard.md), `hdl/dev/dev_vpk.sv`, `hdl/core/midi_vpk.sv` |
| M8b | MIDI subsystem card (D70–D73, one card at subsystem 16): SYN-5.3's own MIDI in, MIDI out on the UART | SYN-5.3 detects it and plays MIDI notes through it (sim); `dev_midi.sv` = model (3 random seeds); board lockstep 19.6M instructions (detection, note in, All Notes Off out). Hardware test pending | [`devices/d70-midi-subsystem.md`](devices/d70-midi-subsystem.md), `sim/devices/midi.py`, `hdl/dev/dev_midi.sv`, `hdl/core/midi_card_feed.sv` |

### Next

Each step: Python model, HDL, lockstep/board test, hardware test on the
MiSTer.

| # | Milestone | What it takes | Done when |
|---|---|---|---|
| **M9** | **32 FM voices** (9600) | Done in HDL (PR pending hardware): `dev_fm.sv` keeps channel state in RAMs and works one voice per clock (interpolator clock pass, sample pass, pitch-write catch-up); voice count from the state image (`--fm-voices 32`). SYN-5.3 with 32 voices plays 20 held keys on 40 channels (sim) | Board lockstep with audio: 19.6M instructions, 3,275,518 samples identical; MiSTer: fit, timing, no new underruns |
| **M10** | **Poly memory above 32 MB** | Done in HDL (PR pending hardware): size from the state image (device 3 index 8, 128 KB units; `w0_image.py --poly-mb 32..224`), `xr_addr` 27 bits (the core's 256 MB at `0x30000000`, poly from 32 MB), clear after reset in 128-beat DDR3 bursts | SYN-5.3 reports the size (sim: 224 MB → "228M"); board lockstep through the size probe of all 224 MB; MiSTer test |
| **M11** | **SCSI load time** | SD reads cost no simulated time, so the CPU waits in real time while sound files load (.204, PR #33: CLARA3 load 67 ms lag, 43 underruns, ~0.5 ms per SD request). Done in HDL (PR pending hardware): the SCSI disk is read 32 blocks (16 KB) per SD request (`sd_floppy.sv`, hps_io `sd_blk_cnt`); simulated behaviour unchanged. Board run: 575 SD requests instead of ~4,100 | no underruns while CLARA3 loads (MiSTer test) |
| **M12** | **Second SCSI disk** (W1:, target 4) | Done in HDL (PR pending hardware): `dev_scsi` second target, SD drive 4 (OSD S4, 32-block lines), `w0_image.py --w1` keeps W1 in the device table | board lockstep: MONITOR `CATALOG W1:` reads target 4 through drive 4; MiSTer test |
| M13 | **Graphics terminal + mouse** (VT640 graphics, D44/D45 mouse port) | bitmap plane in `term_display`; mouse protocol | music notation and timbre display screens draw |

Lower value on MiSTer (possible, not planned): SMPTE card (D70–D73,
subsystem 8), multichannel distributor (D32/D33, mixed to stereo),
guitar interface (D134/D135, `SYN-5.3G`), printer port (D40/D41).

## 5. Verification strategy

| Level | Method | Reference |
|---|---|---|
| Decode | Disassembler matches NED listings (541/541 words, 78/78 targets) | `tests/test_able_disasm.py` |
| CPU semantics | Unit tests per instruction class, flag rule and model | `tests/sim/` |
| Real code | Boot Release L and Release 5.3; run ORK-LM and SYN-5.3 | user images |
| Devices | Behaviour matches NED driver code | `docs/devices/`, `poly-synth.md` |
| HDL | Lockstep trace comparison with the simulator (CPU, system, board top) | `hdl/sim/`, `tests/hdl/` |
| Hardware | `scripts/mister/mister_run.sh`: load, keys, MIDI, screenshot + OCR on a MiSTer | [`hdl.md`](hdl.md) |
| Sound | A/B against real-hardware recordings of known patches | M3.3, help needed |

## 6. Risks and mitigations

| # | Risk | Mitigation |
|---|---|---|
| R1 | Exact FM and poly sound can't be confirmed without hardware | Build from the card analysis, patents and NED source; ask owners for recordings; keep parameters adjustable |
| R2 | Device behaviour differs between releases | Prefer evidence from the release's own binary and source; record differences per release |
| R3 | Real-time software sensitive to CPU throughput | Throttle + code cache; the status line's lag/underrun counters on hardware |
| R4 | FPGA resources (62 % ALMs) for 32 FM voices and new devices | Time-multiplex voices through block RAM |
| R5 | DDR3 bandwidth shared by external memory, code cache and poly fetches | Arbiter in `synclavier_core.sv`; measure underruns with more voices |
| R6 | Licensing of software images | Users supply images; only MIT material in the repo |

## 7. Help wanted from Synclavier owners

Details in [`bench-checklist.md`](bench-checklist.md):
1. **Audio recordings** of known timbres and notes (FM and poly).
2. **Dumps** of the PROMs (FPSM SMR/DDE/INITROM, FPRM U18/U28) and the
   MFC/D40Q boot ROM.
3. High-resolution board photos; edge-connector measurements.
4. MIDI subsystem card and poly voice card documentation.

## 8. Decisions

| # | Decision | Status |
|---|---|---|
| D1 | Project licence | **Decided:** MIT (`LICENSE`) |
| D2 | Workflow | **Decided:** feature branches + PRs with CI (`CONTRIBUTING.md`) |
| D3 | Simulator language | **Decided:** Python; the HDL (Verilator) runs long traces |
| D4 | FPGA framework | **Decided:** Template_MiSTer ([`hdl.md`](hdl.md)) |
| D5 | Keyboard | **Decided:** original keyboard (ORK) for Release L; velocity/pressure keyboard (VPK) for Release 5.3 (selected by the state image; SYN-5.3 takes either, `KEYBOARD.CHECK`) |
| D6 | Second target | **Decided:** Release 5.3 on Model D (3200 configuration), alongside Release L |
