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
Locally:

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

MIDI: set the UART to MidiLink (USB MIDI) in the MiSTer menu. Channels
1–15 play the keyboard (MIDI notes 36–96 = the ORK's 61 keys); channel 16
note n presses panel button n; program change p recalls timbre p (bank
p/8, timbre p%8) with the timbre floppy in F0.
