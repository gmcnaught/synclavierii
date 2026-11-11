#!/usr/bin/env python3
"""Make the MiSTer files for Release 5.3 (docs/release-5.3.md) from a W0
image (Synclavier3's "W0 Disk Image.simg", not redistributable):

    w0_image.py W0IMAGE OUTDIR [--mb 30] [--newdata FILE] [--midi [--smpte]] [--fm-voices N] [--poly-mb N]
                [--poly-bins N | --poly-voices N] [--mono] [--w1] [--vt640]
                [--disk-us N] [--dig-stm] [--multi N] [--printer [TYPE]]

  OUTDIR/W0-53.IMG   the W0 disk padded to --mb megabytes, with a USER
                     subcatalog made by MONITOR's own CREATE USER (MONITOR
                     keeps .CURRENT, DO files and history there; Synclavier3
                     supplies it as a separate USER.simg), and .NEWDATA,
                     the timbre banks (--newdata; default: "*NEWDATA.stmb"
                     next to W0IMAGE, as in Synclavier3's Resources; SYN-5.3
                     shows error 4 on the panel without one). Mount as W0 (S3).
  OUTDIR/W0-53.SST   a state image (tools/state_image.py, version 2): the
                     machine just before MONITOR starts, as sim.boot.
                     boot_from_w0 sets it up (Model D, 8192 sectors of
                     external memory, the SCSI loader slot of .LD-7 at
                     LOC.LOAD, MONITOR staged in external memory; D51's
                     poly bit: a 3200's poly sampling, 32 voices and 32 MB,
                     unless --no-poly; the velocity/pressure keyboard on
                     D130/D131, unless --ork). Mount as the state image (S2). The core then boots MONITOR, which
                     runs W0's PROFILE ("set rtp syn-5.3 ... play") over SCSI.
  OUTDIR/W0-53-MIDI.SST  with --midi instead of W0-53.SST: the same with the
                     MIDI subsystem card (D51 bit 8; D70-D73): MIDI in goes
                     to SYN-5.3's own MIDI input, and MIDI out works
                     (hdl/dev/dev_midi.sv, hdl/core/midi_card_feed.sv).
  --smpte            with the card, the SMPTE reader on its bus (D70 subsystem
                     8), which reads MIDI Time Code from MIDI in (docs/devices/
                     smpte.md; implies --midi): the name gets -SMPTE, e.g.
                     W0-53-MIDI-SMPTE.SST. The core's OSD can add it at load.
  --fm-voices N      FM voices installed (default 32, as on a 3200, 6400 and
                     9600; 8/16/24: a Synclavier II's smaller card sets): the
                     name gets -FM<N> when not 32, e.g. W0-53-FM8.SST.
  --poly-mb N        poly memory per bin in 4 MB steps (default 32; up to 224
                     in all in the core's 256 MB of DDR3): the name gets -P<N>,
                     e.g. W0-53-P224.SST.
                     The core clears it after reset. Per bin with --poly-bins.
  --poly-bins N      poly bins (default 1, a 3200; 2 = a 6400, 32 more poly
                     voices with their own memory; up to 4, SYN-5.3's limit):
                     N x --poly-mb at most 224; the name gets -BIN<N>, e.g.
                     W0-53-BIN2.SST.
  --poly-voices N    poly voices in all, 4..128 in steps of 4 (voice cards came
                     in fours): bins of 32 in order, the last takes the rest
                     (72 = 32 + 32 + 8, 3 bins); replaces --poly-bins; the
                     name gets -V<N>. The core's OSD Hardware page can set this,
                     the memory, mono cards and FM voices at load instead.
  --mono             mono poly voice cards (a 3200's; options bit o#pvoice):
                     SYN-5.3 pans hard right and the core plays the right sum
                     on both outputs; the name gets -MONO.
  --w1               a second SCSI disk, W1: (target 4, mounted as S4): the
                     device table keeps W0, F0 and W1; the name gets -W1.
                     MONITOR then expects a disk in S4.
  --disk-us N        SCSI disk time, microseconds per block read (default 500,
                     about 1 MB/s like a disk of the time; 0: instant). Reads
                     take simulated time, so the machine keeps running (and
                     playing) while a sound file loads, as on the instrument.
  --seek-us N        SCSI seek time (default 25000): a READ that does not
                     continue the last READ or WRITE first costs N us, a
                     drive's access time. The core reads the line from the
                     SD card meanwhile, so the CPU polls with time running
                     instead of stopping while the SD card answers.
  --vt640            SYN-5.3 configured for a VT640 graphics terminal and a
                     D44 mouse (MONITOR configuration words 18 = 021400 and
                     17 | 0100; Synclavier3's W0 says Macintosh): the core
                     draws its Tektronix graphics on a 640 x 480 plane and the
                     PS/2 mouse is SYN-5.3's; the name gets -VT640.
  --dig-stm          the digital sample-to-memory input (M18): D57 bit 0x4000,
                     so SYN-5.3's STM screen records from the source file in
                     S5 (tools/stm_source.py; the core's OSD can set this at
                     load instead); the name gets -DSTM.
  --multi N          a D32/D33 multichannel distributor with N (8 or 16)
                     outputs (D51 bit 0x0800; sim/devices/multi.py,
                     hdl/dev/dev_multi.sv): SYN-5.3 analyses its connections
                     at start-up and offers output routing; the core's OSD
                     Outputs item picks the stereo mix or one output pair;
                     the name gets -MC<N>.
  --music-printing OUTDIR  NED's Music Printing (PF3; built from NED's
                     source by tools/music_printing.py build OUTDIR) in
                     W0:.SYSTEM; with --vt640 and --printer it prints a score
                     as PostScript into the S6 capture file.
  --printer [TYPE]   a printer on the D40/D41 port (MONITOR options word 17 |
                     o#d40 020, configuration word 19 = TYPE << 8; TYPE one
                     of prism (default: SYN-5.3's screen hardcopy is for an
                     IDS Paper Tiger/Prism), printronix, la34, decIII,
                     diablo): the core appends what SYN-5.3 prints to the
                     capture file mounted in S6 (docs/devices/d40-printer.md);
                     the name gets -PRN. The OSD's Hardware page can add the
                     printer to any W0 state image instead.

Both are made by the simulator, so the core starts exactly where the
lockstep traces do (sim/lockstep.py w0boot).
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def prepared_disk(image, mb=30, newdata=None):
    """The W0 image bytes, padded to `mb` MB, with a USER subcatalog and,
    given `newdata` (a .stmb file: 8 timbre banks, big-endian words), a
    .NEWDATA after it."""
    from sim.boot import boot_from_w0
    cpu, _ = boot_from_w0(image, disk_mb=mb)

    def until(pred, limit):
        n = 0
        while n < limit and not cpu.halted and not pred():
            n += cpu.run(100_000)
    until(lambda: b"Ready >" in bytes(cpu.terminal.out), 30_000_000)
    k = bytes(cpu.terminal.out).count(b"Ready >")
    cpu.terminal.feed(b"create user\r")
    until(lambda: bytes(cpu.terminal.out).count(b"Ready >") > k, 10_000_000)
    text = bytes(b & 0o177 for b in cpu.terminal.out).decode("latin-1")
    if cpu.halted or "Ready >" not in text.split("create user")[-1]:
        raise RuntimeError("CREATE USER failed:\n" + text[-400:])
    disk = bytearray(cpu.w0.data)
    if newdata:
        from tools.ned_disk import add_root_file
        add_root_file(disk, ".NEWDATA", open(newdata, "rb").read())
    return bytes(disk)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("image")
    ap.add_argument("outdir")
    ap.add_argument("--mb", type=int, default=30)
    ap.add_argument("--newdata", help="timbre bank file (.stmb) for W0:.NEWDATA")
    ap.add_argument("--no-poly", action="store_true",
                    help="state image without poly voices (D51 poly bit clear)")
    ap.add_argument("--midi", action="store_true",
                    help="state image with the MIDI subsystem card (W0-53-MIDI.SST)")
    ap.add_argument("--smpte", action="store_true",
                    help="the SMPTE reader (MIDI Time Code in) on the MIDI card's bus; implies --midi")
    ap.add_argument("--fm-voices", type=int, default=32, choices=(8, 16, 24, 32),
                    help="FM voices installed (default 32)")
    ap.add_argument("--poly-mb", type=int, default=32, choices=range(4, 225, 4),
                    metavar="{4,8,...,224}", help="poly memory in MB (per bin)")
    ap.add_argument("--poly-bins", type=int, default=1, choices=(1, 2, 3, 4),
                    help="poly bins (2: a 6400)")
    ap.add_argument("--poly-voices", type=int, choices=range(4, 129, 4), metavar="{4,8,...,128}",
                    help="poly voices in all (bins of 32; replaces --poly-bins)")
    ap.add_argument("--mono", action="store_true", help="mono poly voice cards (o#pvoice)")
    ap.add_argument("--w1", action="store_true", help="W1: at SCSI target 4 (S4)")
    ap.add_argument("--disk-us", type=int, default=500, help="SCSI disk time per block (us)")
    ap.add_argument("--seek-us", type=int, default=25000, help="SCSI seek time (us; with --disk-us)")
    ap.add_argument("--vt640", action="store_true", help="VT640 graphics terminal")
    ap.add_argument("--dig-stm", action="store_true",
                    help="the digital STM input (D57 bit 0x4000; source file in S5)")
    ap.add_argument("--multi", type=int, choices=(8, 16),
                    help="multichannel distributor outputs (D32/D33)")
    ap.add_argument("--printer", nargs="?", const="prism", default=None,
                    choices=("prism", "printronix", "la34", "decIII", "diablo"),
                    help="a printer on D40 (default type prism)")
    ap.add_argument("--music-printing", metavar="OUTDIR",
                    help="install NED Music Printing built by tools/music_printing.py build")
    ap.add_argument("--ork", action="store_true",
                    help="state image with the original keyboard instead of the velocity keyboard")
    a = ap.parse_args(argv)
    from sim.devices.digstm import DigitalStm
    from sim.devices.poly import PolySynth
    last = 32
    if a.poly_voices:
        a.poly_bins, last = PolySynth.layout(a.poly_voices)
    if a.poly_mb * a.poly_bins > 224:
        ap.error("--poly-mb x --poly-bins: at most 224 MB (the core's DDR3)")
    os.makedirs(a.outdir, exist_ok=True)
    newdata = a.newdata
    if newdata is None:
        guess = os.path.join(os.path.dirname(os.path.abspath(a.image)), "*NEWDATA.stmb")
        newdata = guess if os.path.exists(guess) else None
    if newdata is None:
        print("no timbre bank (--newdata): W0 without .NEWDATA")
    disk = prepared_disk(a.image, a.mb, newdata)
    if a.music_printing:
        from tools.music_printing import install, mplt_files
        disk = bytearray(disk)
        for name, action in install(disk, mplt_files(a.music_printing)):
            print("W0:.SYSTEM:%s %s" % (name, action))
        disk = bytes(disk)
    w0 = os.path.join(a.outdir, "W0-53.IMG")
    open(w0, "wb").write(disk)
    from sim.boot import boot_from_w0
    from tools.state_image import state_bytes
    poly = None
    if not a.no_poly:
        poly = PolySynth(sectors=a.poly_mb * 2048, bins=a.poly_bins, last_voices=last)
    midi = None
    if a.midi or a.smpte:
        from sim.devices.midi import MidiSubsystem
        from sim.devices.smpte import SmpteReader
        midi = MidiSubsystem(smpte=SmpteReader() if a.smpte else None)
    cpu, _ = boot_from_w0(w0, poly=poly, keyboard="ork" if a.ork else "vpk", midi=midi,
                          fm_voices=a.fm_voices, devices=3 if a.w1 else 2,
                          terminal="vt640" if a.vt640 else None, mouse=a.vt640, mono=a.mono,
                          scsi_block_ns=a.disk_us * 1000, scsi_seek_ns=a.seek_us * 1000,
                          dig_stm=DigitalStm() if a.dig_stm else None, multi=a.multi,
                          printer=a.printer)
    name = ("W0-53" + ("-MIDI" if midi else "") + ("-SMPTE" if a.smpte else "") + ("-FM%d" % a.fm_voices if a.fm_voices != 32 else "")
            + ("-P%d" % a.poly_mb if a.poly_mb != 32 else "")
            + ("-V%d" % a.poly_voices if a.poly_voices else
               "-BIN%d" % a.poly_bins if a.poly_bins != 1 else "") + ("-MONO" if a.mono else "") + ("-W1" if a.w1 else "") + ("-VT640" if a.vt640 else "") + ("-DSTM" if a.dig_stm else "")
            + ("-MC%d" % a.multi if a.multi else "") + ("-PRN" if a.printer else ""))
    sst = os.path.join(a.outdir, name + ".SST")
    data = state_bytes(cpu)
    open(sst, "wb").write(data)
    print("%s: %d MB; %s: %d blocks" % (w0, len(disk) >> 20, sst, len(data) // 512))


if __name__ == "__main__":
    raise SystemExit(main())
