# Synclavier for MiSTer

A MiSTer FPGA core of the New England Digital Synclavier: the ABLE CPU, the FM voices, poly
sampling, the floppy and SCSI disks, the terminal and the front panel. It runs NED's own software:
**Release 5.3** (the last release: Model D CPU, velocity keyboard) or **Release L** (1986, the original
Synclavier II). No NED software is included: you make the disk images from files you get
yourself.

## Source

The source, the tests and the design notes are in
[gmcnaught/synthcores](https://github.com/gmcnaught/synthcores) under
[`cores/synclavier/`](https://github.com/gmcnaught/synthcores/tree/main/cores/synclavier). Each
release names the commit it was built from. This repository keeps only the releases, the MGLs, the
image tools and this README; its history before the move still holds the source up to
`Synclavier_20261118.rbf`.

## Installing

Pick one software release. Release 5.3 is the fuller instrument (velocity keyboard, poly sampling,
Music Printing); Release L comes from a free download.

```
SD card
├── Synclavier-5.3.mgl          starts Release 5.3, from releases/
├── Synclavier-ReleaseL.mgl     starts Release L, from releases/
├── _Devices/
│   └── Synclavier_YYYYMMDD.rbf  the core, from releases/
└── games/
    └── Synclavier/
        ├── W0-53.IMG            Release 5.3: hard disk W0     } made in step 2
        ├── W0-53.SST            Release 5.3: state image      }
        ├── ORK-LM.SST           Release L: state image        }
        ├── 03-SYSTD.IMG         Release L: system floppy      }
        ├── 14-RTPO1.IMG         Release L: real-time program  }
        └── 06-TIMBD.IMG         Release L: timbre floppy      }
```

You only need the files for the release you pick.

### 1. Get the NED software

| Release | File | Where to get it |
|---|---|---|
| 5.3 | `W0 Disk Image.simg` and the timbre banks `*NEWDATA.stmb` | inside Synclavier Digital's Synclavier³ app for macOS: `Synclavier³.app/Contents/Resources/` |
| L | `NED_Synclavier_Release_L_DD_Floppies.simg` | GitHub [`Synclavier/Synclavier_Distributions`](https://github.com/Synclavier/Synclavier_Distributions), folder `Release_L/` |

### 2. Make the images

On a PC with Python 3.8 or newer (no extra packages; on Windows, type `py` for `python3`):

```bash
git clone https://github.com/gmcnaught/synclavierii
cd synclavierii
```

**Release 5.3:**

```bash
R="/Applications/Synclavier³.app/Contents/Resources"
python3 tools/w0_image.py "$R/W0 Disk Image.simg" out
```

- It writes `out/W0-53.IMG` (30 MB) and `out/W0-53.SST` in about 3 seconds.
- It takes the timbre banks (`*NEWDATA.stmb`) from the folder the W0 image is in; give one with
  `--newdata FILE` if it is somewhere else. If it prints `No timbre bank (--newdata)`, SYN-5.3 will
  show "Err4" on the panel and an empty Timbre Directory.

**Release L:**

```bash
L=NED_Synclavier_Release_L_DD_Floppies.simg
python3 tools/ned_disk.py "$L" --floppy 03-SYSTD out/03-SYSTD.IMG
python3 tools/ned_disk.py "$L" --floppy 14-RTPO1 out/14-RTPO1.IMG
python3 tools/ned_disk.py "$L" --floppy 06-TIMBD out/06-TIMBD.IMG
python3 tools/state_image.py "$L" out/ORK-LM.SST
```

The last command boots Release L in the simulator and saves the running real-time program
(ORK-LM) as a state image; it takes about 10 seconds.

### 3. Copy the files to the SD card

1. Make the folder `games/Synclavier/` and copy the files from `out/` into it.
2. Copy the newest `Synclavier_YYYYMMDD.rbf` from [`releases/`](releases/) to `_Devices/`.
3. Copy [`releases/Synclavier-5.3.mgl`](releases/Synclavier-5.3.mgl) and/or
   [`releases/Synclavier-ReleaseL.mgl`](releases/Synclavier-ReleaseL.mgl) to the top of the SD card.
4. Start **Synclavier-5.3** or **Synclavier-ReleaseL** from the MiSTer main menu. The MGL loads the
   core and mounts the images:
    - Release 5.3 boots from W0 and shows SYN-5.3's Main Menu after about 6 seconds.
    - Release L starts ORK-LM, then swaps the timbre floppy in after 15 seconds.

The screen shows the terminal at the top and the instrument's panel at the bottom (Release 5.3:
the velocity keyboard's display and 160 buttons; Release L: the 4-digit display and 128 buttons).
Click a panel button with the mouse to press it.

### 4. Connect MIDI

The core plays the MIDI that arrives on the MiSTer's UART through MidiLink.

1. Plug a USB MIDI interface or a USB MIDI keyboard into the MiSTer.
2. Start the core, open the OSD (F12) and press Right to reach the **System** page.
3. Open **UART mode**, set **Connection** to **MIDI** and **MidiLink** to **USB**. Main_MiSTer
   saves this per core.
4. Play. The mapping depends on the release (below).

**Release 5.3 (velocity keyboard).** Defaults suit a Novation Launchkey MK3:

| MIDI | Synclavier |
|---|---|
| notes, channels 1–9, 11–14 | keys with velocity (MIDI 33–108; middle C = MIDI 60) |
| key pressure / channel pressure | per-key pressure |
| pitch bend, CC 1, CC 2 | pitch wheel, mod wheel, breath |
| CC 4, CC 11, CC 16 | pedal 1, pedal 2, ribbon |
| CC 64 | sustain |
| channel 10 notes 36–51 (drum pads) | 36 BANK, 37 ENTRY, 38 START, 39 STOP, 44 RECORD, 45 CONTINUE, 46 REWIND, 47 FAST FORWARD; 40–43 and 48–51 the numbered buttons 1–8 |
| CC 21 (pot 1) | the control knob |
| CC 22–28 (pots 2–8) | select partial volume, partial tuning, ratio, attack, initial decay, sustain, final decay, then act as the knob |
| channel 16 note n, channel 15 note n | panel button n, button 128 + n |
| program change p | recalls timbre p (BANK, button (p/8)%8+1, ENTRY, button p%8+1) |

Velocity, pressure and the wheels act on a timbre once they are patched to it, as on the real
instrument (hold a VK button such as VK VEL and press the destination, e.g. PARTIAL VOLUME).

**Release L (original keyboard).** Channels 1–15 play the 61 keys (MIDI 36–96, no velocity; MIDI
60 is middle C); channel 16 note n presses panel button n; program change p recalls timbre p
(bank p/8, timbre p%8).

## Using it

- **Terminal keys** (VT100): the arrow keys move; Enter is RETURN; keypad Enter is ENTER ("<ENTER>
  when done"; Esc twice also works); F1–F4 are PF1–PF4. In SYN-5.3's Timbre Directory (Main Menu
  A) pick a timbre with the arrows, Return recalls it, keypad Enter leaves the screen.
- **Disks:** writes go back to the image files on the SD card. Mount an image read-only in the OSD
  to protect it.
- **OSD Hardware page:** sets the cards the instrument has, for the next reset (Reset, or Reset and
  close OSD): poly voices (4–128), mono or stereo poly cards, poly memory per bin (4–224 MB), FM
  voices (8–32), the SMPTE reader (MIDI Time Code in) and the printer. "From image" keeps what the
  state image says.
- **More configurations:** `tools/w0_image.py --help` lists the options it bakes into a state image:
  the MIDI card (`--midi`), a second hard disk W1 (`--w1`), a VT640 graphics terminal (`--vt640`),
  multichannel outputs (`--multi 16`), the printer and Music Printing, and the original keyboard
  (`--ork`). The output file name says which, e.g. `W0-53-MIDI.SST`; mount it in the OSD as the
  State image (S2) in place of `W0-53.SST`, or make a copy of the MGL that names it.

## Known limits

- The DAC, envelope and mix details are modelled from NED's documentation and source; they have not
  been compared with recordings of a real instrument.
- The Launchkey defaults for pads and pots are not checked against a captured device.
- Not supported: Direct-to-Disk, sample-to-memory recording (there is no audio input), mono
  sampling, the Macintosh terminal.

## License

MIT; see [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE). The built cores include the MiSTer framework
under GPL-2.0 ([`licenses/GPL-2.0.txt`](licenses/GPL-2.0.txt)). Synclavier® is a registered
trademark of Synclavier Digital; this project is not affiliated with Synclavier Digital or New
England Digital.
