# Roadmap: an FPGA Synclavier

*One-page summary. The detailed plan, with acceptance criteria,
verification, risks and decisions, is in [`plan.md`](plan.md).*

A **behavioural** MiSTer core of the New England Digital Synclavier,
running original NED software: Release L on a Synclavier II (Model B), and
Release 5.3 on a 3200/6400/9600 (Model D). A gate-level copy of the
FPRM/FPSM boards is not required.

## What works

| Piece | Status | Where |
|---|---|---|
| ABLE CPU, Models B, C, D | Simulator and HDL agree instruction by instruction (random programs, MONITOR, ORK-LM, SYN-5.3) | [`instruction-set.md`](instruction-set.md), [`hdl.md`](hdl.md) |
| Release L | Boots from SD floppies to `Ready >`; ORK-LM plays FM timbres from MIDI on a MiSTer | [`release-l-image.md`](release-l-image.md) |
| Release 5.3 | Boots from a SCSI W0 image; SYN-5.3 Main Menu, timbre banks (`.NEWDATA`), FM notes from MIDI on a MiSTer | [`release-5.3.md`](release-5.3.md) |
| FM voices | 8 voices; register semantics decoded, pitch verified; HDL = Python sample for sample | [`fm-voice.md`](fm-voice.md) |
| Poly sampling | 32 stereo voices, 32 MB poly memory in DDR3 (a 3200); sound files load over SCSI and play | [`poly-synth.md`](poly-synth.md) |
| Keyboard and panel | ORK (Release L) and velocity/pressure keyboard (Release 5.3); MIDI notes → keys with velocity, Launchkey pads/pots → panel buttons and knob, program change → timbre recall; on-screen panel with mouse | `hdl/core/midi_in.sv`, `hdl/core/midi_vpk.sv`, [`devices/`](devices/) |
| MIDI card | D70–D73 MIDI subsystem card: SYN-5.3 reads MIDI itself (routing, recording, sync) and sends MIDI out on the UART (state image `W0-53-MIDI.SST`) | [`devices/d70-midi-subsystem.md`](devices/d70-midi-subsystem.md) |
| Terminal | VT100 subset on the video output, PS/2 keyboard, PF keys | `hdl/core/term_display.sv` |

## Done in HDL, waiting for a hardware test

Each verified in the simulator and by board lockstep (the whole core
against the Python model); PRs #35-#40, stacked.

| # | Item | State image option (`tools/w0_image.py`) |
|---|---|---|
| M8b | MIDI subsystem card (D70-D73): SYN-5.3's own MIDI in, MIDI out | `--midi` |
| M9 | Up to 32 FM voices (9600), serial voice engine | `--fm-voices 32` |
| M10 | Poly memory up to 224 MB | `--poly-mb 224` |
| M11 | SCSI disk read 32 blocks per SD request (sound files load without audio gaps) | (always) |
| M12 | Second SCSI disk, W1: | `--w1` (OSD S4) |
| M13 | VT640 graphics terminal and D44 mouse | `--vt640` |

## Next

| Item | Needs |
|---|---|
| Hardware tests of the above on a MiSTer | the MiSTer on the network |
| Launchkey pad and pot numbers (M8a) | a MIDI capture from the user's Launchkey |
| FM and poly sound against a real instrument (M3.3) | recordings |

Possible but low value on MiSTer: SMPTE, multichannel outputs, guitar
interface, printer port.

Not planned: Direct-to-Disk (separate 68K system, no firmware),
sample-to-memory recording (no audio input), mono sampling, the Macintosh
terminal.

## Open gaps

1. **Exact sound:** FM and poly DAC, envelope and mix details are model
   choices until recordings of a real machine are available.
2. **FPGA resources:** 62 % of ALMs used; 32 FM voices need a
   time-multiplexed voice engine.
3. **Distribution:** Release L and Synclavier³ images are not
   redistributable; users supply them.

Hardware owners can help: see [`bench-checklist.md`](bench-checklist.md),
especially recordings of known patches and PROM dumps.
