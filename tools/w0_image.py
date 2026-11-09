#!/usr/bin/env python3
"""Make the MiSTer files for Release 5.3 (docs/release-5.3.md) from a W0
image (Synclavier3's "W0 Disk Image.simg", not redistributable):

    w0_image.py W0IMAGE OUTDIR [--mb 30] [--newdata FILE] [--midi]

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
    ap.add_argument("--ork", action="store_true",
                    help="state image with the original keyboard instead of the velocity keyboard")
    a = ap.parse_args(argv)
    os.makedirs(a.outdir, exist_ok=True)
    newdata = a.newdata
    if newdata is None:
        guess = os.path.join(os.path.dirname(os.path.abspath(a.image)), "*NEWDATA.stmb")
        newdata = guess if os.path.exists(guess) else None
    if newdata is None:
        print("no timbre bank (--newdata): W0 without .NEWDATA")
    disk = prepared_disk(a.image, a.mb, newdata)
    w0 = os.path.join(a.outdir, "W0-53.IMG")
    open(w0, "wb").write(disk)
    from sim.boot import boot_from_w0
    from tools.state_image import state_bytes
    poly = None
    if not a.no_poly:
        from sim.devices.poly import PolySynth
        poly = PolySynth()
    midi = None
    if a.midi:
        from sim.devices.midi import MidiSubsystem
        midi = MidiSubsystem()
    cpu, _ = boot_from_w0(w0, poly=poly, keyboard="ork" if a.ork else "vpk", midi=midi)
    sst = os.path.join(a.outdir, "W0-53-MIDI.SST" if a.midi else "W0-53.SST")
    data = state_bytes(cpu)
    open(sst, "wb").write(data)
    print("%s: %d MB; %s: %d blocks" % (w0, len(disk) >> 20, sst, len(data) // 512))


if __name__ == "__main__":
    raise SystemExit(main())
