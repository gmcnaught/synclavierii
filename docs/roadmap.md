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
| Keyboard and panel | ORK model; MIDI notes → keys, channel 16 → panel buttons, program change → timbre recall; on-screen panel with mouse | `hdl/core/midi_in.sv`, [`devices/`](devices/) |
| Terminal | VT100 subset on the video output, PS/2 keyboard, PF keys | `hdl/core/term_display.sv` |

## What's next

| # | Item | Value |
|---|---|---|
| M8a | **Velocity/pressure keyboard** (VPK) for Release 5.3, played from MIDI; Launchkey pads and pots mapped to panel buttons and the control knob | velocity, pressure, wheels; the full 160-button panel |
| M8b | **MIDI subsystem card** (D70–D72): SYN-5.3's own MIDI in/out and routing | MIDI out, multi-channel MIDI |
| M9 | **32 FM voices** (9600): voice state in block RAM, one voice per clock | full 9600 FM polyphony |
| M10 | **Poly memory up to ~224 MB** (of the core's 256 MB DDR3 window) | larger sample libraries |
| M11 | **SCSI load timing**: SD reads take simulated time | no audio stall while sound files load |
| M12 | **Second SCSI disk** (target 4) | more storage |
| M13 | **Graphics terminal + mouse** (VT640, D44/D45) | notation and timbre display screens |

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
