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
| FM voices | 8 or 32 voices (a 9600); register semantics decoded, pitch verified; HDL = Python sample for sample | [`fm-voice.md`](fm-voice.md) |
| Poly sampling | 32 stereo voices per bin, 1 bin (a 3200) or 2 (a 6400, `--poly-bins 2`: 64 voices), 32 MB or more per bin in DDR3; sound files load over SCSI and play | [`poly-synth.md`](poly-synth.md) |
| Keyboard and panel | ORK (Release L) and velocity/pressure keyboard (Release 5.3); MIDI notes → keys with velocity, Launchkey pads/pots → panel buttons and knob, program change → timbre recall; on-screen panel with mouse | `hdl/core/midi_in.sv`, `hdl/core/midi_vpk.sv`, [`devices/`](devices/) |
| MIDI card | D70–D73 MIDI subsystem card: SYN-5.3 reads MIDI itself (routing, recording, sync) and sends MIDI out on the UART (state image `W0-53-MIDI.SST`) | [`devices/d70-midi-subsystem.md`](devices/d70-midi-subsystem.md) |
| Terminal | VT100 subset on the video output, PS/2 keyboard, PF keys | `hdl/core/term_display.sv` |

## Verified on hardware since the last summary

On a MiSTer (.62, 2026-11-09): MIDI card (M8b), 32 FM voices
(M9, `--fm-voices 32`), poly memory up to 224 MB (M10, `--poly-mb 224`),
SCSI load time (M11: sound files load with 0 underruns), W1: (M12, `--w1`),
VT640 graphics and mouse (M13, `--vt640`); FM and poly voices on real time
(M14, `hdl/voice_clock.sv`: a CPU wait no longer stops the audio). 2026-11-10: two
poly bins, a 6400 (M15, `--poly-bins 2`: 64 poly voices, CLARA3 played from bin 2).

## Next

| Item | Needs |
|---|---|
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
2. **FPGA resources:** about 50 % of ALMs and 79 % of RAM blocks used
   with 32 FM voices (a time-multiplexed engine), up to 4 poly bins and the
   50 MHz core clock.
3. **Distribution:** Release L and Synclavier³ images are not
   redistributable; users supply them.

Hardware owners can help: see [`bench-checklist.md`](bench-checklist.md),
especially recordings of known patches and PROM dumps.
