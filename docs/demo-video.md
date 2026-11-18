# Demo videos

One demo script drives two recordings of the same performance:

1. **Simulator** (`tools/demo.py render`): SYN-5.3 boots in the Python
   simulator from the W0:/W1: images, the script's events play, and the
   result is an MP4 of the VT640 picture and the core's 48 kHz audio. No
   capture hardware, the same result every run, and the audio is what the
   core computes (lockstep: the HDL voice engine and `pcm_out.sv` match the
   Python model bit for bit, `docs/hdl.md`).
2. **MiSTer** (`tools/demo.py hw`): the same events go to the core's MIDI
   in (`/dev/ttyS1`, MidiLink) and its keyboard (`mister_keys.py`) while
   the HDMI output is recorded with a capture card.

## Script

```
# comment
title: Bach - Chorale BWV 269 (SYNCLAV-ORGAN 2.)
w0: W0-53.IMG               # images: --images DIR, the script's directory, out/images
w1: W1-TIMBRES.IMG
fps: 30                     # video frame rate (default 30)

type D                      # terminal characters (0.1 s apart)
type W1:RESYNTH5
key ENTER                   # ENTER ESC UP DOWN LEFT RIGHT TAB BACKSPACE F1-F4
wait 4                      # seconds
program 21                  # MIDI program change: BANK 3, ENTRY 6 (as midi_vpk.sv)
type F
wait 8
record                      # the video starts here; the steps above are setup
button seqb                 # tap a VPK panel button (name or PBN): held 0.1 s, then 0.3 s
button start 0.2            # held 0.2 s
press trrout                # hold a button / let it go (e.g. TRACK ROUTING + a timbre button)
release trrout
note C4 1.5 100             # one key: 1.5 s, velocity 100
play ../sequences/bach-bwv269-chorale.txt [tempo=BPM] [transpose=N] [parts=1,2]
                            [velocity=V] [from=BEAT] [to=BEAT]
end                         # the video ends here (default: after the last step)
```

Steps run one after another; `wait`, `type`, `key`, `button`, `program`,
`note` and `play` take time, `press`/`release`/`record`/`end` do not.
Button names are `sim/devices/synth.py` `VPK_BUTTONS` (`seqb`, `bankb`,
`entryb`, `timb.0`-`timb.7`, `start`, `stop`, `trrout`, ...).

`play` takes a score: MusicXML (`.mxl`, `.musicxml`; e.g. from
[musetrainer/library](https://github.com/musetrainer/library), public
domain compositions), a Standard MIDI File or a `tools/seq_record.py` note
list. Every staff/track is played live on the keys (MIDI channel 1, the
score's velocities, notes folded into the VPK's MIDI 33-108). Repeats are
played once. Scores are not committed (`tests/test_repo_hygiene.py`); keep
downloads in `out/scores/`, which `play` also searches.

Events: a panel button is MIDI channel 16 note PBN (PBN 128-159: channel
15 note PBN - 128), a key is a channel 1 note, `program` is a program
change, which `midi_vpk.sv` turns into BANK, a timbre button, ENTRY, a
timbre button (held 100 ms, 200 ms apart, 1.5 s after the bank number);
terminal keys are the bytes `ps2_ascii.sv` sends (arrows ^K ^J ^H ^L,
F1-F4 ESC O P-S). `demo.py events SCRIPT` lists them.

## Simulator render

```bash
python3 tools/demo.py render data/demos/chorale-synclav-organ.demo out/chorale.mp4 --wav out/chorale.wav
```

* Boot: `sim.boot.boot_from_w0` with the VPK, a VT640, the mouse, 32 FM
  voices and one 32 MB poly bin (`--fm-voices`, `--poly-bins`), run for
  `--boot` (12) simulated seconds; then the script's setup steps, then the
  recording.
* Picture: `tools/vt100.py` `render640()` (the model `term_display.sv`
  is checked against), colour 0 (green, `#33ff66`), redrawn whenever the
  terminal output changed, scaled by whole pixels to `--height` (1080:
  1440 x 1080), H.264.
* Audio: `sim/pcm.py` `render_frames()` of the FM register writes from
  the recording's start (`pcm_out.sv` bit for bit: 768 kHz instants,
  512-tap FIR to 48 kHz, gain 1/16 per voice, clipped to 16 bits) plus
  `devices/poly.py`'s mix at the same 48 kHz instants, clipped again
  (`dev_poly.sv` adds them the same way); AAC 256k in the MP4, PCM with
  `--wav`. The FM pass runs in one-second chunks on all CPUs (`--jobs`);
  each chunk warms the FIR up over the 512 instants before it, so the
  chunks join to exactly one `render_frames()` call (`tests/test_demo.py`).
* Level: by default the WAV is the core's output, bit for bit, including
  any clipping (counted in the log). Since M23 (PR #66) `pcm_out.sv` puts
  one voice at full level, hard-panned, at 1/16 of full scale, with an
  equal-power pan: the PIPE ORGAN #1 chorale (8 voices a note, 32 voices)
  that clipped about 2 % of samples at the old 1/4 no longer clips.
  `--gain DB` scales the whole mix before the clip; that file is no longer
  the core's output.
* Terminal rate: `--baud N` or a `baud:` header (default 9600, the
  factory rate). SYN-5.3 never sets the D50/D51 rate (the only writes in
  the NED source are in `UTILCAT/LISTING`), so the rate is the card's;
  38400 is the fastest a real system ran (a faster serial card). Music
  Notation's redraws then take about a quarter of the time. The board
  needs a state image made with `tools/w0_image.py --baud N` (the state
  image carries the rate: D50 baud index 4 = 9600, 6 = 38400).
* Speed (Apple silicon, 8 cores): boot 28 s; SYN-5.3 with the script
  about 1.8-2.3 x real time; the FM audio pass, single-process, about 10 x
  real time for 32 sounding organ voices (53.7 s of chorale: 9 min), so
  divide by the core count. Under PyPy (`pypy3 tools/demo.py render ...`,
  no changes needed) boot takes 6.8 s and SYN-5.3 runs at 0.35 x real
  time (CPython: 28.9 s, 2.26 x); `smoke.demo` renders in 13 s instead of
  71 s with a byte-identical WAV and identical frames (2026-11-17).

## On the MiSTer

```bash
python3 tools/demo.py hw data/demos/chorale-synclav-organ.demo [--host root@192.168.20.62] [--dry-run]
```

Load the MGL that matches the script's images first (e.g.
`Synclavier-Demos-Glass.mgl`: W0-53.IMG, W1-TIMBRES.IMG and the VT640
state image; `Synclavier-Samples.mgl` for W1-SAMPLES.IMG) and stop
Zaparoo so MidiLink holds 31250 baud (`mister/README.md`). The command
copies the events, a player and `mister_keys.py` to `/tmp` on the MiSTer,
runs the setup steps, waits for Return (start the capture then), and
plays the rest with MIDI bytes timed on the MiSTer itself. Terminal keys
less than 0.15 s apart go in one `mister_keys.py` call (it creates a
uinput keyboard each time, so a call takes a moment); MIDI is written to
`/dev/ttyS1` at its script time. The board
starts from its state image rather than a fresh boot, so the setup steps
must leave it where the simulator is (they do for the scripts here: both
start at the Main Menu).

Capture settings that matter (`MiSTer.ini`): `hdmi_audio_96k=0` (48 kHz,
which capture cards take), `vsync_adjust=0` with a standard `video_mode`
(the core's picture is 59.5 Hz, which some cards drop).

## Scripts

| Script | Images | What |
|---|---|---|
| `data/demos/smoke.demo` | W0-53, W1-TIMBRES | three keys and START/STOP on SIMPLE FM SINE; FM Timbre display (6 s) |
| `data/demos/chorale-synclav-organ.demo` | W0-53, W1-TIMBRES | Bach BWV 269 (`data/sequences/`), live on SYNCLAV-ORGAN 2. (W1:RESYNTH5 3-6), FM Timbre display. Also tried: SYNCLAV-ORGAN 1. (3-1), STRINGS 5. (1-7), PIPE ORGAN #1 (W1:TIMBDSK3 1-2: 8 voices a note, clips 2.25 % at the 1/4 FM gain) |
| `data/demos/gymnopedie-piano.demo` | W0-53, W1-SAMPLES | Satie, Gymnopedie No. 1 (musetrainer MusicXML), live at 69 BPM on FULL PIANO (W1:PIANO1 2-1, sampled), Patch display |
| `data/demos/gymnopedie-notation.demo` | W0-53-GYMNO, W1-SAMPLES | the same piece played by the sequencer (W0:.SQ5DATA) on CONCERT GRAND-16, melody/bass/chords at velocity 17/13/9, while Music Notation follows it |

## Notes

* `SIMPLE FM SINE` (W0:.NEWDATA bank 1 entry 2) sounds a semitone sharp:
  SYN-5.3 writes C#4 (INC 125, NNU 123: 277.14 Hz) for middle C, A#3
  (466 Hz) for A3 [OBS, simulator FM writes, 2026-11-17]. Other timbres
  (FM HARMONICS, SIMPLE BELL, PIPE ORGAN #1, B3 Pedal) give A3 = 440.0 Hz,
  so the offset is the timbre's tuning, not the pitch path. The W1:DEMOS
  sequences were recorded on this timbre (`seq_record.py record` default
  `--timbre 1-2`).

## Music Notation during playback

Music Notation (Main Menu K) draws the memory recorder's sequence, not
keys played live, so a notation demo plays a recorded sequence:

1. `seq_record.py record SCORE.mxl --w0 W0-53.IMG --w1 W1-SAMPLES.IMG
   --catalog W1:PIANO1 --timbre 2-1 --slot 5 --beat-ms 870 --sseq OUT.sseq`
   records it in the simulator on FULL PIANO with the click at the beat
   (Music Notation's grid); the save goes to W0:.SQ5DATA even with
   W1:PIANO1 current (`WRITTEN TO DISK`).
2. `seq_record.py install OUT.sseq --w0 W0-53.IMG --slot 5 --out
   W0-53-GYMNO.IMG` puts it in a copy of W0 (on the MiSTer: that image in
   the MGL in place of W0-53.IMG).
3. The script: SEQUENCE + 5 (the tracks bring FULL PIANO; its sound files
   load from W1: through the sound-file cache, with W0: the current
   catalog), K, Staves 2, Measures 4, TimeSig 3/4, Key D on both staves,
   Clf F on staff 2, then START.

During playback the screen follows the sequence itself: a cursor line at
the play position and a new page every Measures bars (simulator,
2026-11-17: W1:DEMOS minuet, Measure# 0 -> 4 after about 6 s; Gymnopedie,
Measure# 4 at 20 s) [OBS]. No scripted page turns are needed.

Recording Gymnopedie No. 1 (2026-11-17) [OBS]: all note starts within
5 ms; two differences from the score, both from playing it on one
keyboard / SYN-5.3's key range:
* The right hand holds F#4 in a chord while the melody strikes F#4 again
  (beats 24-36); the restrike ends the held note (one key per pitch), so
  that note is 4.35 s shorter.
* The three lowest bass notes (B1, A1, B1: NED keys 9-11, the VPK's lowest
  keys) were saved an octave up (B2, A2) [UNK: whether SYN-5.3's recorder
  or the sequence format moves keys below 12].

## Velocity layers: CONCERT GRAND-16 (2026-11-17)

W1:PIANO2 is NED's concert grand recorded at four dynamics (sound files
`PNO??71` pp, `72` mf, `73` f, `74` ff). CONCERT GRAND-16 (W1:PIANO2 1-2)
has one partial per dynamic over the whole keyboard, and its velocity
slot drives DYN.ENV (sampled destination `1024`) and volume (continuous
`4`), so key velocity picks the recording, and with it the attack. In the
simulator, C4 by MIDI velocity [OBS, sim/devices/synth.py velocity table,
which hdl/core/midi_vpk.sv shares]:

| Velocity | Recording | Peak (16-bit) |
|---|---|---|
| 1-5 | pp | 140-370 |
| 9-17 | mf | 1,360-2,310 |
| 21-77 | f | 2,080-5,460 |
| 81-127 | ff | 8,970-12,080 |

`seq_record.py record --velocity STAFF/VOICE=V,...` sets a MusicXML
voice's velocity (the Gymnopedie: melody 1/2, bass 2/5, chords 1/1 and
2/6). At 17/13/9 (all mf) the melody is about 13 dB over the chords.

Recording on a timbre this size needed two fixes in `seq_record.py`: wait
until the sound files have loaded (3 s without LOADING on the panel), and
repeat STOP until the RECORD and START lights are off (SYN-5.3 missed a
single 0.1 s press and kept recording into the next part).
