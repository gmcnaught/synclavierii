"""Run a Release L real-time program (RTP) under the simulator (M2.1).

Release L is a Winchester system: the install floppies (08-INST1 ...
13-INST6) carry a multi-floppy `.SYSTEM` archive, and the SCRIPT compiler
files that MONITOR's PLAY command opens (.SCOM-6, .SSYM-6, .SCON-6) are not
on any floppy as plain files. So PLAY cannot run from the floppies alone.

Instead this module hands the RTP to the real loader the way MONITOR
starts any program, changing only where the file comes from:

  1. Boot MONITOR from 03-SYSTD (sim.boot) and run a small program with
     "ENTER F0:", "OLD CONFIGUR", "RUN". MONITOR's RUN sets the high-core
     state for an overlay (magic number at MEM.SIZ - 138, run status,
     memory-size words) and enters the .LD-6 loader (entries 1-3).
  2. At that entry, stage the RTP in external memory and enter the
     loader's ECOPY entry (4) instead. The loader copies the object code to
     0, copies the high-core configuration into it (magic number valid),
     moves the swap file to the top of external memory, and starts it.

Multi-floppy executables (catalog type 8): each part starts with a
one-sector header -- name length, name (4 words), 1, word length mod 64K,
total sectors after the headers, disk number -- followed by the data.
[OBS: ORK-LM is 14-RTPO1 + 15-RTPO2, header total 673 = 396 + 277.]

External memory: the staged copy must lie below the swap file's final
place (EMSIZE - swap length), or the loader's ascending copy overwrites
its own source. ORK-LM (673 sectors, 519 swap) needs more than 1024
sectors; the default here is 2048 (512K words). CHOICE.
"""
from .boot import boot_from_image
from .trace import STOP_BREAKPOINT, STOP_INPUT, Debugger

SECTOR_WORDS = 256
LOADER_ECOPY = 4
#: Release L high-core file pointers (offsets below MEM.SIZ; -6 layout,
#: observed by diffing high core across PLAY): length, LS sector, device.
LOC_MON_LENGTH, LOC_P2_LENGTH, LOC_P3_LENGTH = 46, 52, 55


def rtp_parts(W, name):
    """(disk number, path, words) of each part of multi-floppy file `name`."""
    from tools.ned_disk import file_words, walk
    parts = []
    for p, typ, start, length, words in walk(W):
        if p.rsplit("/", 1)[-1] == name and typ == 8:
            fw = file_words(W, start, length, words)
            parts.append((fw[8], p, fw))
    if not parts:
        raise KeyError(name)
    parts.sort()
    return parts


def rtp_words(W, name):
    """The executable: all parts' data concatenated, headers dropped."""
    parts = rtp_parts(W, name)
    total = parts[0][2][7]
    data = []
    for disk, path, fw in parts:
        if fw[7] != total:
            raise ValueError("%s: header total %d differs from %d" % (path, fw[7], total))
        data += fw[SECTOR_WORDS:]
    if [d for d, _, _ in parts] != list(range(1, len(parts) + 1)):
        raise ValueError("%s: disk numbers %s" % (name, [d for d, _, _ in parts]))
    if len(data) != total * SECTOR_WORDS:
        raise ValueError("%s: %d words, header says %d sectors" % (name, len(data), total))
    return data


def start_rtp(image, name="ORK-LM", ext_sectors=2048, strict=False, history_len=64,
              io_sink=None, **system_kw):
    """Boot MONITOR, then start RTP `name` through the loader.

    Returns (cpu, dbg, layout); the CPU is at the loader's ECOPY entry with
    the RTP staged. Synthesizer stubs are non-strict and a ProbeDevice
    answers every other device unless strict=True.
    """
    from tools.ned_disk import load
    from .devices.stubs import ProbeDevice
    W = load(image)
    program = rtp_words(W, name)
    first_floppy = rtp_parts(W, name)[0][1].strip("/").split("/")[0]
    cpu, lay = boot_from_image(image, "03-SYSTD", f1=first_floppy, ext_sectors=ext_sectors,
                               strict=strict, **system_kw)
    if not strict:
        cpu.probe = ProbeDevice()
        cpu.bus.fallback = cpu.probe
    dbg = Debugger(cpu, history_len=history_len)
    if dbg.run(50_000_000, until_input=True) != STOP_INPUT:
        raise RuntimeError("MONITOR did not reach Ready >:\n" + dbg.report())
    entries = {lay["loc_load"] + i for i in (1, 2, 3)}
    # SET RTP + PLAY: MONITOR finds the RTP (F1) and .STAB-6 (F0) and stores
    # their locations in high core (LOC.P2 / LOC.P3) before giving up on the
    # missing SCRIPT compiler. The RTP reads .STAB-6 from LOC.P3.
    for line in ("SET RTP %s\r" % name, "PLAY\r", "ENTER F0:\r", "OLD CONFIGUR\r", "RUN\r"):
        cpu.terminal.feed(line)
        if line == "RUN\r":
            dbg.breakpoints.update(entries)
        stop = dbg.run(100_000_000, until_input=True)
        if line != "RUN\r" and stop != STOP_INPUT:
            raise RuntimeError("%r: %s\n%s" % (line, stop, dbg.report()))
    if stop != STOP_BREAKPOINT:
        raise RuntimeError("MONITOR did not enter the loader:\n" + dbg.report())
    msiz = lay["mem_siz"]
    if cpu.mem[msiz - LOC_P3_LENGTH] == 0:
        raise RuntimeError("PLAY did not record .STAB-6 (LOC.P3):\n" + cpu.terminal.text()[-400:])
    dbg.breakpoints.clear()
    dbg.io_counts.clear()
    if not strict:
        cpu.probe.counts.clear()    # count only what the RTP touches
    cpu.extmem.load(0, program)
    cpu.r[0], cpu.r[1], cpu.r[2] = 0, 0, len(program) & 0xFFFF
    cpu.pc = lay["loc_load"] + LOADER_ECOPY
    dbg.io_sink = io_sink
    lay = dict(lay, rtp=name, rtp_words=len(program))
    return cpu, dbg, lay


NEWDATA_SECTOR = 4          # .NEWDATA on 06-TIMBD starts at floppy sector 4
BANK_SECTORS = 49           # 8 banks of 49 sectors; a bank button reads the first 32


def replace_bank(media, path, bank=0):
    """Write a timbre bank file (raw big-endian words, e.g. a Synclavier
    `*NEWDATA.stmb`) over bank `bank` of the 06-TIMBD floppy media.
    [OBS] Release L layout: .NEWDATA = 8 banks x 49 sectors."""
    import struct
    data = open(path, "rb").read()
    words = list(struct.unpack(">%dH" % (len(data) // 2), data[:len(data) // 2 * 2]))
    size = BANK_SECTORS * SECTOR_WORDS
    if len(words) > size:
        raise ValueError("%s: %d words, a bank holds %d" % (path, len(words), size))
    start = (NEWDATA_SECTOR + bank * BANK_SECTORS) * SECTOR_WORDS
    media.words[start:start + size] = words + [0] * (size - len(words))


def run_seconds(cpu, dbg, seconds):
    """Run for `seconds` of simulated time. Returns a stop reason or None."""
    t0 = cpu.time_ns
    while cpu.time_ns - t0 < seconds * 1e9:
        stop = dbg.run(1_000_000)
        if stop:
            return stop
    return None


def main(argv=None):
    import argparse
    import csv
    import sys
    from .boot import insert_floppy
    from .devices.synth import button_number

    ap = argparse.ArgumentParser(
        description="Run a Release L RTP, play it from the simulated panel and log device accesses (M2)")
    ap.add_argument("image", help="Release L .simg (user-supplied)")
    ap.add_argument("--rtp", default="ORK-LM", help="ORK-LM or ORK-LFM")
    ap.add_argument("--seconds", type=float, default=10.0,
                    help="simulated seconds to run before any panel actions")
    ap.add_argument("--log", help="CSV file for every device access of the RTP")
    ap.add_argument("--quiet-devices", default="50,51,60,61,62,63",
                    help="octal devices left out of the CSV (default: terminal, ext memory)")
    ap.add_argument("--swap-f0", metavar="FLOPPY",
                    help="after start, put this floppy in F0 (e.g. 06-TIMBD, the timbre library)")
    ap.add_argument("--bank-file", metavar="PATH",
                    help="with --swap-f0 06-TIMBD: replace a bank of .NEWDATA with this file")
    ap.add_argument("--bank", type=int, default=0, help="bank number for --bank-file (0-7)")
    ap.add_argument("--buttons", default="",
                    help="panel buttons to press in order, names or numbers (e.g. bank.0,timb.0)")
    ap.add_argument("--keys", default="", help="keys to hold together, 12-72 (e.g. 48 = C4)")
    ap.add_argument("--hold", type=float, default=1.0, help="simulated seconds to hold the keys")
    ap.add_argument("--fm-log", help="CSV of every FM register write (D162) during the actions")
    ap.add_argument("--wav", help="render the FM voices during the actions to this WAV file (M3.2)")
    a = ap.parse_args(argv)

    quiet = {int(x, 8) for x in a.quiet_devices.split(",") if x}
    f = writer = None
    if a.log:
        f = open(a.log, "w", newline="")
        writer = csv.writer(f)
        writer.writerow(["time_ns", "pc", "rw", "device", "value"])

    def sink(t, pc, kind, dev, value):
        if dev not in quiet:
            writer.writerow([t, "%06o" % (pc or 0), kind, "%03o" % dev,
                             "NOSYN" if value is None else "%06o" % value])

    out = sys.stdout
    cpu, dbg, lay = start_rtp(a.image, a.rtp, io_sink=sink if writer else None,
                              output=lambda b: (out.write(chr(b & 0o177)), out.flush()))
    print("\n[rtp] %s staged (%d words); starting at %06o" % (a.rtp, lay["rtp_words"], cpu.pc))
    t0 = cpu.time_ns
    stop = run_seconds(cpu, dbg, a.seconds)
    fm0 = len(cpu.fm.log)
    t_keys = cpu.fm.time_ns     # render from here: the key press, if any
    if not stop and a.swap_f0:
        insert_floppy(cpu, a.image, 0, a.swap_f0)
        print("\n[rtp] F0 <- %s" % a.swap_f0)
        if a.bank_file:
            replace_bank(cpu.floppy.media[0], a.bank_file, a.bank)
            print("[rtp] bank %d <- %s" % (a.bank, a.bank_file))
    for b in [x for x in a.buttons.split(",") if x]:
        if stop:
            break
        pbn = button_number(b)
        print("\n[rtp] button %s (PBN %d)" % (b, pbn))
        cpu.keyboard.press_button(pbn)
        stop = run_seconds(cpu, dbg, 0.1)
        cpu.keyboard.press_button(pbn, False)
        stop = stop or run_seconds(cpu, dbg, 1.5)
    keys = [int(k) for k in a.keys.split(",") if k]
    if keys and not stop:
        print("\n[rtp] keys %s for %.2f s" % (keys, a.hold))
        k0 = len(cpu.fm.log)
        t_keys = cpu.fm.time_ns
        for k in keys:
            cpu.keyboard.press_key(k)
        stop = run_seconds(cpu, dbg, a.hold)
        for k in keys:
            cpu.keyboard.press_key(k, False)
        stop = stop or run_seconds(cpu, dbg, 0.5)
        print("\n[rtp] FM writes while playing: %d" % (len(cpu.fm.log) - k0))
    if f:
        f.close()
    if a.fm_log:
        with open(a.fm_log, "w", newline="") as g:
            w = csv.writer(g)
            w.writerow(["time_ns", "channel_word", "channel", "function", "value"])
            for t, word, fn, v in cpu.fm.log[fm0:]:
                w.writerow([t, "%06o" % word, "%03o" % (word & 0o377), "%02o" % fn, "%06o" % v])
    if a.wav and cpu.fm.log[fm0:]:
        from .voice import render, write_wav
        if len(cpu.fm.log) >= cpu.fm.log_len:
            print("[rtp] warning: FM log full (%d writes); later writes are not rendered"
                  % cpu.fm.log_len)
        samples = render(cpu.fm.log, t_keys if keys else cpu.fm.log[fm0][0], cpu.fm.time_ns,
                         voices=cpu.fm.voices)
        clipped = write_wav(a.wav, samples)
        print("[rtp] %s: %.2f s rendered, %d samples clipped" % (a.wav, len(samples) / 48_000, clipped))
    print("\n" + "=" * 60)
    print("[rtp] stop: %s after %.2f simulated s, %d instructions"
          % (stop or "end of script", (cpu.time_ns - t0) / 1e9, cpu.instructions))
    if stop:
        print(dbg.report(history=16, io=16))
    return 1 if stop == "halted" else 0


if __name__ == "__main__":
    raise SystemExit(main())
