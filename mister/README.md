# MiSTer core

Quartus project for the Synclavier II core on MiSTer (DE10-Nano), built on
[Template_MiSTer](https://github.com/MiSTer-devel/Template_MiSTer)
(commit e901a9fa, November 2026). The machine itself is in `../hdl/`
(`hdl/core/synclavier_core.sv`); see [`docs/hdl.md`](../docs/hdl.md#mister-core-hdlcore-hdlboard-mister).

| File | |
|---|---|
| `Synclavier.sv` | `emu`: hps_io (OSD, two floppy image slots, keyboard), PLL, core, DDR3, video, audio |
| `files.qip` | the HDL files (from `../hdl/`) |
| `Synclavier.qpf/.qsf/.sdc/.srf` | Template project settings, renamed |
| `rtl/pll*` | Template's PLL, set to 50 MHz (`synclavier_core` CLK_HZ must match) |
| `sys/` | MiSTer framework, unchanged (GPL-2.0: `sys/LICENSE-GPL2`); update from upstream, do not edit |
| `build.sh` | compile with Quartus Lite 17.0; fails on negative slack |

## Build

CI builds it on every pull request that touches `hdl/` or `mister/`
(`.github/workflows/build-rbf.yml`, Quartus 17.0 in the
`raetro/quartus:17.0` Docker image); the RBF and reports are artifacts.
A self-hosted runner on the TrueNAS host can take these builds instead
(native x86, image cached): install `mister/ci/truenas-runner.yaml` as a
TrueNAS Custom App (instructions in the file), then set the repository
variable `QUARTUS_RUNNER` to `truenas`; unset it to go back to
`ubuntu-latest`. Locally:

```bash
mister/build.sh                     # quartus_sh on PATH
docker run --rm -v "$PWD:/build" raetro/quartus:17.0 bash -c "cd /build && mister/build.sh _out"
```

## Use

Make floppy images from a Release L `.simg` (not included; see
[`docs/release-l-image.md`](../docs/release-l-image.md)):

```bash
python3 tools/ned_disk.py Release_L.simg --floppy 03-SYSTD 03-SYSTD.IMG
python3 tools/ned_disk.py Release_L.simg --floppy 18-UTILS 18-UTILS.IMG
```

Copy them to `games/Synclavier/` on the SD card. In the OSD, mount
`03-SYSTD.IMG` as F0 (and a second floppy as F1): the core boots MONITOR
from F0 and prints `Ready >`. Type `CATALOG` to list F1. Writes go back to
the image files (mount read-only to protect them).

The bottom of the screen shows the original panel: the 4-digit display and
the 128 buttons, lit ones inverted. Click a button with the mouse to press
it.

The real-time program (ORK-LM) starts from a state image: on Release L it
needs a Winchester disk, so the simulator starts it and saves the state.

```bash
python3 tools/state_image.py Release_L.simg ORK-LM.SST
python3 tools/ned_disk.py Release_L.simg --floppy 14-RTPO1 14-RTPO1.IMG
python3 tools/ned_disk.py Release_L.simg --floppy 06-TIMBD 06-TIMBD.IMG
```

The state image enables the poly sampling voices (a 3200: 32 voices, 32 MB
of poly memory in DDR3; `--no-poly` for an FM-only system): sound files such as
W0:CLARA3 / CLARA4 (Timbre Directory bank 2) load into poly memory and play
from the keyboard. The core clears poly memory at start (about 0.9 s).

Mount `ORK-LM.SST` as the State image (S2), `03-SYSTD.IMG` as F0 and
`14-RTPO1.IMG` as F1, then Reset: the core loads the state and ORK-LM runs.
For timbres, mount `06-TIMBD.IMG` as F0 and press a bank button, then a
timbre button (mouse, MIDI channel 16, or MIDI program change).

Terminal keys (ORK-LM's screens, VT100 conventions): the arrow keys move;
Enter is the VT100 RETURN; keypad Enter is the VT100 ENTER (`ESC O M`,
"<ENTER> when done"); Esc twice also works as ENTER; F1–F4 are PF1–PF4.
In the Timbre Directory (welcome menu A) pick a timbre with the arrows,
Return recalls it, keypad Enter leaves the screen.

Release L's 06-TIMBD is a blank library: all 64 timbres are the default
(WORKSPACE, a sine). A later NED bank (`*NEWDATA.stmb`, see
[`docs/timbre-libraries.md`](../docs/timbre-libraries.md)) can replace a
bank: `tools/ned_disk.py Release_L.simg --floppy 06-TIMBD TOMDTA43.IMG
--bank 1 TOMDTA43/*NEWDATA.stmb`. With TOMDTA43 in bank 1, timbres 4, 5, 6
and 8 are FM timbres that play (simulator); timbre 1 needs a sound file.

### Release 5.3 (Model D)

The core also runs Release 5.3.0, the last Synclavier release, on a Model D
processor (`docs/release-5.3.md`). Its W0 hard disk ships inside
Synclavier³ (`Synclavier³.app/Contents/Resources/W0 Disk Image.simg`, not
included here). Make the two files and copy them to `games/Synclavier/`:

```bash
R="Synclavier³.app/Contents/Resources"
python3 tools/w0_image.py "$R/W0 Disk Image.simg" out/w53     # also takes "$R/*NEWDATA.stmb"
```

`W0-53.IMG` gets Synclavier³'s timbre banks (`*NEWDATA.stmb`, found next to
the W0 image or given with `--newdata`) as `W0:.NEWDATA`; without them
SYN-5.3 shows error 4 ("Err4") on the panel and an empty Timbre Directory.

Mount `W0-53.IMG` as the SCSI disk W0 (S3), then `W0-53.SST` as the state
image (S2): MONITOR 5.3 boots from W0, runs its PROFILE and starts SYN-5.3
(Main Menu after about 6 s). An MGL:

```xml
<mistergamedescription>
    <rbf>_Computer/Synclavier</rbf>
    <file delay="2" type="s" index="3" path="W0-53.IMG"/>
    <file delay="1" type="s" index="2" path="W0-53.SST"/>
</mistergamedescription>
```

MIDI: set the UART to MidiLink (USB MIDI) in the MiSTer menu.

**Release L (original keyboard, ORK).** Channels 1–15 play the keyboard
(MIDI notes 36–96 = the ORK's 61 keys; no velocity); channel 16 note n
presses panel button n; program change p recalls timbre p (bank p/8,
timbre p%8) with the timbre floppy in F0. MIDI 60 is middle C (key 36).

**Release 5.3 (velocity/pressure keyboard, VPK).** `W0-53.SST` puts the
VPK on D130/D131 (`docs/devices/d130-velocity-keyboard.md`;
`tools/w0_image.py --ork` for the ORK instead). The panel strip shows the
VPK's 2 × 16 display and its 160 buttons. MIDI (`hdl/core/midi_vpk.sv`;
defaults for a Novation Launchkey MK3):

| MIDI | VPK |
|---|---|
| notes, channels 1–9, 11–14 | keys with velocity (MIDI 33–108; middle C = MIDI 60) |
| key pressure / channel pressure | per-key pressure |
| pitch bend, CC 1, CC 2 | pitch wheel, mod wheel, breath |
| CC 4, CC 11, CC 16 | pedal 1, pedal 2, ribbon |
| CC 64 | sustain switch |
| channel 10 notes 36–51 (drum pads) | buttons: 36 BANK, 37 ENTRY, 38 START, 39 STOP, 44 RECORD, 45 CONTINUE, 46 REWIND, 47 FAST FORWARD; 40–43 and 48–51 the numbered buttons 1–8 |
| CC 21 (pot 1) | the control knob: changes the selected parameter, one step per pot step (fast turns 4) |
| CC 22–28 (pots 2–8) | select partial volume, partial tuning, ratio, attack, initial decay, sustain, final decay, then act as the knob |
| channel 16 note n, channel 15 note n | button n, button 128 + n |
| program change p | BANK, button (p/8)%8+1, ENTRY, button p%8+1 |

Velocity, pressure and the wheels act on a timbre once they are patched to
it, as on the real instrument (hold a VK button such as VK VEL and press
the destination, e.g. PARTIAL VOLUME).

**Cards: voices, memory, mono or stereo (OSD Hardware page).** The
instrument was upgraded by adding cards, and the OSD page **Hardware**
sets the same complement for the next reset (Reset, or Reset and close
OSD; SYN-5.3 looks for its hardware only at start-up):

| Item | Values | |
|---|---|---|
| Poly voices | From image, 4 … 128 in steps of 4 | voice cards came in fours; bins fill 32 voices each, the last bin takes the rest (72 = 32 + 32 + 8 in 3 bins) |
| Poly voice cards | From image, Mono | mono: a 3200's cards; SYN-5.3 pans hard right and the core plays it on both outputs |
| Poly memory/bin | From image, 4 … 32 MB, 224 MB/bins | memory came in 4 MB steps |
| FM voices | From image, 8, 16, 24, 32 | |

"From image" keeps what the state image says. The same choices exist in
`tools/w0_image.py`, which bakes them into a state image:
`--poly-voices N`, `--mono`, `--poly-mb N` (4–224 in steps of 4, per
bin), `--fm-voices N` (default 32; 8, 16, 24 as a Synclavier II's card
sets), `--poly-bins N`; the name says which, e.g. `W0-53-V72-MONO.SST`,
`W0-53-FM8-P224.SST`. The poly memory is cleared after reset in DDR3
bursts (estimated 0.6 s for 224 MB; not yet measured).

**A second SCSI disk (W1:).** `tools/w0_image.py --w1` keeps W1 (SCSI
target 4) in MONITOR's device table (`W0-53-W1.SST`); mount the second
disk image as S4 (`<file delay="2" type="s" index="4" path="W1.IMG"/>`
in the MGL). A copy of a W0 image, or any NED SCSI disk image up to
32 MB, works; `CATALOG W1:` lists it.

**VT640 graphics terminal and mouse.** `tools/w0_image.py --vt640`
configures SYN-5.3 for a VT640 (Tektronix 4010 graphics over the terminal)
with a mouse on D44 (`W0-53-VT640.SST`; the Synclavier³ W0 is configured
for a Macintosh, whose drawing commands the core skips). The terminal then
fills the screen, 640 × 480, with SYN-5.3's graphics drawn on it: graphic
timbre display (F), music notation (K), sound file editor, the screen
manager's boxes. The MiSTer mouse is SYN-5.3's (it draws its own
crosshair). OSD "VT640: panel strip" shows the panel and the status line
over the bottom 96 lines. Not on a VT640: the Audio Event Editor.

**Release 5.3 with the MIDI subsystem card.** `tools/w0_image.py --midi`
writes `W0-53-MIDI.SST`: the same machine with a MIDI card on D70–D73
(`docs/devices/d70-midi-subsystem.md`). SYN-5.3 then reads MIDI itself, as
a 3200/6400/9600 with a MIDI card does: notes on any channel (OMNI, the
default) play the keyboard timbre with SYN-5.3's own velocity map; CC 1 mod
wheel, CC 64 sustain, pitch bend; MIDI routing, recording to tracks and the
MIDI sync settings work as on the instrument. Panel controls stay as in the
table above: channel 16 and 15 notes, the drum pads (channel 10 notes
36–51), pots (CC 21–28) and program change (which also reaches SYN-5.3).
MIDI out: SYN-5.3's four outputs of the card leave on the UART (MidiLink
forwards them to USB MIDI), at the speed the input runs at; nothing is sent
until a timbre or track is routed to MIDI out, except All Notes Off on
every channel when STOP is pressed twice.

```xml
<mistergamedescription>
    <rbf>_Computer/Synclavier</rbf>
    <file delay="2" type="s" index="3" path="W0-53.IMG"/>
    <file delay="1" type="s" index="2" path="W0-53-MIDI.SST"/>
</mistergamedescription>
```
