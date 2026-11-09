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

MIDI: set the UART to MidiLink (USB MIDI) in the MiSTer menu. Channels
1–15 play the keyboard (MIDI notes 36–96 = the ORK's 61 keys); channel 16
note n presses panel button n; program change p recalls timbre p (bank
p/8, timbre p%8) with the timbre floppy in F0.
