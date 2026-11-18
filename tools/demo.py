#!/usr/bin/env python3
"""Demo scripts: one timed script of panel buttons, keys and terminal keys,
rendered in the simulator to a video (MP4: the VT640 picture and the
core's 48 kHz audio) or played on a MiSTer while its HDMI is recorded.

    demo.py render SCRIPT.demo OUT.mp4 [--images DIR] [--fps 30] [--height 1080]
    demo.py events SCRIPT.demo            # the compiled event list
    demo.py hw SCRIPT.demo [--host root@192.168.20.62] [--dry-run]

Script format (one step per line; '#' after a space or at the start of a
line begins a comment; times in seconds):

    title: Gymnopedie No. 1
    w0: W0-53.IMG               # disk images (--images DIR, the script's
    w1: W1-TIMBRES.IMG          #   directory, or out/images)
    fps: 30
    baud: 38400                 # terminal rate (default 9600; the board needs a
                                #   state image made with w0_image.py --baud)

    type D                      # terminal characters, as typed
    key ENTER                   # ENTER ESC UP DOWN LEFT RIGHT TAB BACKSPACE F1-F4 CTRL-A..Z
    wait 3                      # let time pass
    record                      # the video starts here; steps before set up
    button seqb                 # tap a VPK panel button (name or PBN; hold 0.1 s, then 0.3 s)
    button start 0.2            #   ... held 0.2 s
    press trrout              # hold a button down / let it go
    release trrout
    program 9                   # MIDI program change: bank 2, entry 2 (as midi_vpk.sv)
    note C4 1.5 [100]           # play one key for 1.5 s (velocity 100)
    play SCORE [tempo=BPM] [transpose=N] [parts=1,2] [velocity=V] [from=BEAT] [to=BEAT]
                                # a score (.mxl/.musicxml, .mid, seq_record note list)
                                # played live on the keys; takes the score's length
    end                         # the video ends here (default: after the last step)

Each step becomes events at script times: MIDI messages (panel buttons on
channel 16 notes, PBN 128-159 on channel 15; keys on channel 1 with
velocity; program change), the same messages hdl/core/midi_vpk.sv takes
on the board, and terminal keys (the bytes hdl/core/ps2_ascii.sv sends;
on the board mister_keys.py presses the keys). The simulator boots SYN-5.3
from the W0 image first (with the VPK and the VT640, like the Demos MGLs),
then runs the events; the board starts from its state image instead.

render: the frame is tools/vt100.py's VT640 picture (term_display.sv draws
the same), green as the core's default colour, scaled by whole pixels to
--height; audio is sim/pcm.py render_frames() of the FM writes and
devices/poly.py's output P(m) (pcm_out.sv bit for bit: 768 kHz instants,
the poly staircase averaged over each, 512-tap FIR, M26; the OSD FM/Poly
levels and limiter at their defaults or --fm-level/--poly-level/--limiter-off,
#76).
Simulated time runs about 2-3 x slower than real time.
"""
import argparse
import json
import math
import os
import shlex
import struct
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tools.seq_record import fold, note_number, read_piece  # noqa: E402

#: terminal keys: the bytes ps2_ascii.sv sends; and mister_keys.py names
KEYS = {"ENTER": b"\r", "ESC": b"\x1b", "TAB": b"\t", "BACKSPACE": b"\x08",
        "UP": b"\x0b", "DOWN": b"\x0a", "LEFT": b"\x08", "RIGHT": b"\x0c",
        "F1": b"\x1bOP", "F2": b"\x1bOQ", "F3": b"\x1bOR", "F4": b"\x1bOS"}
#: CTRL-A ... CTRL-Z: letter & 037, as ps2_ascii.sv sends Ctrl + a letter
KEYS.update(("CTRL-%c" % c, bytes([ord(c) & 31])) for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ")
#: mister_keys.py names where they differ from KEYS'
BOARD_KEYS = {"CTRL-%c" % c: "LEFTCTRL+%c" % c.lower() for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"}
TAP_HOLD, TAP_GAP = 0.1, 0.3          # a `button` step (as seq_record.py)
TYPE_GAP = 0.1                        # between typed characters
GREEN = (0x33, 0xFF, 0x66)
BAUDS = (300, 1200, 2400, 4800, 9600, 19200, 38400, 76800)   # D50/D51 rates (SYSLITS b#300 ...)            # term_display.sv colour 0


# --------------------------------------------------------------------------
# Script

class Script:
    def __init__(self):
        self.title = ""
        self.header = {}
        self.events = []        # (time s, kind, data): kind "midi" (bytes) or "term" (bytes)
        self.record = 0.0       # video start
        self.end = None         # video end
        self.path = ""


def button_number(name):
    from sim.devices.synth import vpk_button_number
    try:
        return vpk_button_number(name)
    except ValueError:
        raise ValueError("unknown VPK button %r (sim/devices/synth.py VPK_BUTTONS)" % name)


def button_msg(pbn, down):
    """The MIDI note midi_vpk.sv takes as PBN `pbn`: channel 16 note n, or
    channel 15 note n - 128."""
    ch, n = (15, pbn) if pbn < 128 else (14, pbn - 128)
    return bytes(((0x90 if down else 0x80) | ch, n, 64 if down else 0))


def key_msg(midi_key, down, vel=100):
    return bytes(((0x90 if down else 0x80), midi_key & 0x7F, vel if down else 0))


def piece_events(path, opts, base_dir):
    """Key events (seconds from the step's start, midi key, down, velocity)
    and the length of a `play` step."""
    from fractions import Fraction
    p = read_piece(resolve(path, base_dir, [os.path.join(ROOT, "out", "scores")]))
    beat_s = p.beat_ms / 1000
    if "tempo" in opts:
        beat_s = 60 / float(opts["tempo"])
    parts = p.parts
    if "parts" in opts:
        parts = [p.parts[int(i) - 1] for i in opts["parts"].split(",")]
    tr = int(opts.get("transpose", 0))
    vel = opts.get("velocity")
    lo = Fraction(opts["from"]) if "from" in opts else None
    hi = Fraction(opts["to"]) if "to" in opts else None
    notes = [n for part in parts for n in part.notes
             if (lo is None or n.start >= lo) and (hi is None or n.start < hi)]
    if not notes:
        raise ValueError("%s: no notes" % path)
    t0 = lo if lo is not None else 0
    ev = []
    for n in notes:
        on = float(n.start - t0) * beat_s
        off = max(on + 0.01, float(n.start + n.dur - t0) * beat_s - 0.02)
        k = fold(n.key + tr)                 # into the VPK's MIDI 33..108
        v = int(vel) if vel else n.vel
        ev.append((on, k, True, v))
        ev.append((off, k, False, 0))
    # releases first at equal times; a key struck again while held is lifted first
    ev.sort(key=lambda e: (e[0], e[2]))
    out, down = [], {}
    for at, k, on, v in ev:
        if on:
            if down.get(k):
                out.append((at, k, False, 0))
            down[k] = down.get(k, 0) + 1
            out.append((at, k, True, v))
        elif down.get(k):
            down[k] -= 1
            if not down[k]:
                out.append((at, k, False, 0))
    return out, max(e[0] for e in out) + 0.5


def resolve(name, base_dir, extra=()):
    if os.path.isabs(name):
        return name
    for d in (base_dir, *extra):
        if d and os.path.exists(os.path.join(d, name)):
            return os.path.join(d, name)
    return os.path.join(base_dir, name)


def parse(path, text=None):
    """Read a demo script; returns a Script with its events compiled."""
    import re
    s = Script()
    s.path = path
    base = os.path.dirname(os.path.abspath(path))
    t = 0.0
    if text is None:
        text = open(path, encoding="utf-8").read()
    for ln, raw in enumerate(text.splitlines(), 1):
        line = re.sub(r"(^|\s)#(\s.*)?$", "", raw).strip()
        if not line:
            continue
        head, sep, val = line.partition(":")
        if sep and " " not in head.strip():
            s.header[head.strip().lower()] = val.strip()
            if head.strip().lower() == "title":
                s.title = val.strip()
            continue
        op, _, rest = line.partition(" ")
        op = op.lower()
        args = rest.split()
        where = "%s:%d" % (path, ln)
        try:
            if op == "wait":
                t += float(args[0])
            elif op == "type":
                text_ = raw.split(None, 1)[1].split(" #")[0].rstrip() if len(raw.split(None, 1)) > 1 else ""
                for c in text_:
                    s.events.append((t, "term", c.encode("latin-1")))
                    t += TYPE_GAP
            elif op == "key":
                for k in args:
                    if k.upper() not in KEYS:
                        raise ValueError("unknown key %r (ENTER ESC TAB BACKSPACE UP DOWN LEFT RIGHT "
                                         "F1-F4 CTRL-A..CTRL-Z)" % k)
                    s.events.append((t, "term", k.upper()))
                    t += TYPE_GAP
            elif op == "button":
                pbn = button_number(args[0])
                hold = float(args[1]) if len(args) > 1 else TAP_HOLD
                s.events.append((t, "midi", button_msg(pbn, True)))
                s.events.append((t + hold, "midi", button_msg(pbn, False)))
                t += hold + TAP_GAP
            elif op in ("press", "release"):
                s.events.append((t, "midi", button_msg(button_number(args[0]), op == "press")))
            elif op == "program":
                prog = int(args[0])
                if not 0 <= prog < 128:
                    raise ValueError("program 0..127")
                s.events.append((t, "midi", bytes((0xC0, prog))))
                t += 4 * TAP_HOLD + 3 * 0.2 + 1.5 + 0.2
            elif op == "note":
                k = note_number(args[0])
                dur = float(args[1]) if len(args) > 1 else 0.5
                vel = int(args[2]) if len(args) > 2 else 100
                s.events.append((t, "midi", key_msg(fold(k), True, vel)))
                s.events.append((t + dur, "midi", key_msg(fold(k), False)))
                t += dur
            elif op == "play":
                opts = dict(a.split("=", 1) for a in args[1:])
                ev, length = piece_events(args[0], opts, base)
                for at, k, on, v in ev:
                    s.events.append((t + at, "midi", key_msg(k, on, v)))
                t += length
            elif op == "record":
                s.record = t
            elif op == "end":
                s.end = t
            else:
                raise ValueError("unknown step %r" % op)
        except (IndexError, ValueError, OSError) as e:
            raise ValueError("%s: %s" % (where, e)) from None
    if s.end is None:
        s.end = max([t] + [e[0] for e in s.events])
    s.events.sort(key=lambda e: e[0])          # stable: same-time events keep script order
    return s


# --------------------------------------------------------------------------
# Simulator

class SimInput:
    """Apply script events to the simulator as the board applies them:
    MIDI as midi_vpk.sv (keys, panel buttons, program change), terminal
    keys as ps2_ascii.sv's bytes."""

    def __init__(self, cpu):
        self.cpu = cpu
        self.kb = cpu.keyboard
        self.later = []          # (time ns, callable): program-change taps

    def apply(self, kind, data):
        if kind == "term":
            self.cpu.terminal.feed(KEYS.get(data, data) if isinstance(data, str) else data)
            return
        st, ch = data[0] & 0xF0, data[0] & 0x0F
        if st in (0x80, 0x90):
            down = st == 0x90 and data[2] > 0
            if ch in (15, 14):
                self.kb.press_button(data[1] + (128 if ch == 14 else 0), down)
            else:
                self.kb.press_key(data[1] - 60 + 36, down, data[2] if down else 64)
        elif st == 0xC0:
            p = data[1]
            now = self.cpu.time_ns
            taps = (("bankb", 0.2), ("timb.%d" % (p >> 3 & 7), 1.5), ("entryb", 0.2), ("timb.%d" % (p & 7), 0.2))
            for name, gap in taps:
                pbn = button_number(name)
                self.later.append((now, lambda b=pbn: self.kb.press_button(b, True)))
                now += int(TAP_HOLD * 1e9)
                self.later.append((now, lambda b=pbn: self.kb.press_button(b, False)))
                now += int(gap * 1e9)
            self.later.sort(key=lambda e: e[0])

    def due(self, t_ns):
        while self.later and self.later[0][0] <= t_ns:
            self.later.pop(0)[1]()

    def next_ns(self):
        return self.later[0][0] if self.later else None


def frame_planes(px, color=GREEN):
    """640 x 480 bytes of 0/1 -> gbrp planes (ffmpeg planar G, B, R)."""
    planes = []
    for c in (color[1], color[2], color[0]):
        planes.append(px.translate(bytes([0, c] + [0] * 254)))
    return b"".join(planes)


def render(a):
    s = parse(a.script)
    base = os.path.dirname(os.path.abspath(a.script))
    dirs = [x for x in (a.images, base, os.path.join(ROOT, "out", "images")) if x]
    w0 = resolve(s.header.get("w0", "W0-53.IMG"), dirs[0], dirs[1:])
    w1 = s.header.get("w1")
    w1 = resolve(w1, dirs[0], dirs[1:]) if w1 else None
    fps = float(s.header.get("fps", a.fps))
    baud = script_baud(s, a.baud)
    from sim.devices.poly import PolySynth
    from sim.boot import boot_from_w0

    def log(msg):
        print("[demo] %s" % msg, flush=True)

    wall = time.time()
    poly = PolySynth(bins=a.poly_bins)
    cpu, _ = boot_from_w0(w0, w1=w1, poly=poly, keyboard="vpk", fm_voices=a.fm_voices,
                          terminal="vt640", mouse=True, baud=baud)
    cpu.fm.log_len = 1 << 62
    step = 2_000

    def run_to(t_ns):
        while cpu.time_ns < t_ns and not cpu.halted:
            left = (t_ns - cpu.time_ns) // 1000
            cpu.run(max(step, min(20_000, left)) if left > 2 * step else step)
        if cpu.halted:
            raise RuntimeError("simulator halted: %s" % (cpu.halted,))

    run_to(int(a.boot * 1e9))
    log("booted in %.0f s (terminal %d baud): %s | %s" % ((time.time() - wall, baud, *cpu.keyboard.display_text())))
    inp = SimInput(cpu)
    t_start = cpu.time_ns
    rec_ns = t_start + int(s.record * 1e9)
    end_ns = t_start + int((s.end + a.tail) * 1e9)
    nframes = int((end_ns - rec_ns) * fps / 1e9)

    tmpdir = tempfile.TemporaryDirectory(prefix="demo-")
    tmp = tmpdir.name
    video = os.path.join(tmp, "video.mkv")
    wav = os.path.join(tmp, "audio.wav")
    ff = None
    events = list(s.events)
    frame = 0
    screen = cpu.screen
    out = cpu.terminal.out
    seen, planes = -1, None
    while frame < nframes or events:
        t_frame = rec_ns + int(frame * 1e9 / fps) if frame < nframes else 1 << 62
        t_ev = t_start + int(events[0][0] * 1e9) if events else 1 << 62
        t_later = inp.next_ns() or 1 << 62
        t = min(t_frame, t_ev, t_later)
        if t >= end_ns and t != t_frame:
            break
        if poly.out_l is None and t >= rec_ns - POLY_LEAD_NS:
            run_to(max(0, rec_ns - POLY_LEAD_NS))
            poly.record()
        run_to(t)
        inp.due(cpu.time_ns)
        while events and t_start + int(events[0][0] * 1e9) <= cpu.time_ns:
            _, kind, data = events.pop(0)
            inp.apply(kind, data)
        if t == t_frame:
            if ff is None:
                ff = start_ffmpeg(video, fps)
                log("recording from %.1f s (script time); %d frames" % (s.record, nframes))
            if len(out) != seen or planes is None:
                seen = len(out)
                planes = frame_planes(screen.render640())
            ff.stdin.write(planes)
            frame += 1
            if frame % int(fps * 10) == 0:
                log("%5.1f s of %.1f s video, %.0f s wall | %s | %s"
                    % (frame / fps, nframes / fps, time.time() - wall, *cpu.keyboard.display_text()))
    run_to(end_ns)
    ff.stdin.close()
    if ff.wait():
        raise RuntimeError("ffmpeg (video) failed")
    if poly.time_ns != cpu.time_ns:
        raise RuntimeError("poly time %d != CPU time %d" % (poly.time_ns, cpu.time_ns))
    poly.advance()
    log("rendering audio (%d FM writes)" % len(cpu.fm.log))
    n = (end_ns - rec_ns) * 48_000 // 1_000_000_000
    from sim.pcm import LIM_T, limit_frames
    wide = fm_render_parallel(cpu.fm.log, rec_ns, end_ns, cpu.fm.voices, a.jobs,
                              poly=(poly.out_m0, poly.out_l, poly.out_r),
                              fm_level=a.fm_level, poly_level=a.poly_level, limit=None)
    over = sum(1 for f in wide for v in f if abs(v) > LIM_T)
    peak = max([abs(v) for f in wide for v in f] or [0])
    fm = limit_frames(wide, not a.limiter_off)
    clipped = write_mix(wav, fm, n, 10 ** (a.gain / 20))
    log("audio: %.1f s, peak %.1f dBFS before the limiter, %d of %d samples over -1 dBFS (%s), "
        "%d clipped (%.2f%%)%s"
        % (n / 48_000, 20 * math.log10(max(peak, 1) / 32768), over, 2 * n,
           "clipped" if a.limiter_off else "limited", clipped, 100 * clipped / max(1, 2 * n),
           "" if a.gain == 0 else ", gain %+g dB (not the core's level)" % a.gain))
    vf = "scale=-2:%d:flags=neighbor" % a.height
    cmd = ["ffmpeg", "-loglevel", "error", "-y", "-i", video, "-i", wav, "-vf", vf,
           "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
           "-tune", "animation", "-c:a", "aac", "-b:a", "256k", "-shortest",
           "-metadata", "title=%s" % (s.title or os.path.basename(a.script)), a.out]
    subprocess.run(cmd, check=True)
    if a.wav:
        os.replace(wav, a.wav)
    log("%s: %.1f s, %.0f s wall" % (a.out, nframes / fps, time.time() - wall))
    return 0


CHUNK_NS = 1_000_000_000          # render chunks: whole seconds = whole 16-instant groups
POLY_LEAD_NS = 2_000_000          # poly recorded from before the FIR's warm-up (512 instants)


def _fm_chunk(job):
    from sim.pcm import render_frames
    log, c0, c1, voices, origin, poly, kw = job
    return render_frames(log, c0, c1, voices=voices, origin_ns=origin, poly=poly, **kw)


def _poly_slice(poly, c0, c1):
    """The part of (m0, pl, pr) a chunk from c0 to c1 ns reads (with its
    warm-up), or None."""
    if poly is None:
        return None
    from sim.pcm import F0_TICK_NS
    m0, pl, pr = poly
    a = max(m0, (c0 - POLY_LEAD_NS) // F0_TICK_NS)
    b = max(a, min(m0 + len(pl), c1 // F0_TICK_NS + 2))
    return a, pl[a - m0:b - m0], pr[a - m0:b - m0]


def fm_render_parallel(log, start_ns, end_ns, voices, jobs=None, poly=None,
                       fm_level=0, poly_level=0, limit=True):
    """pcm_out.sv's 16-bit FM frames from start_ns to end_ns (sim/pcm.py
    render_frames, instants start_ns + k x 1e9 // 768000) in chunks on
    `jobs` processes. Chunks start at start_ns + whole multiples of CHUNK_NS
    (768 instants a ms: whole groups of 16); render_frames rebuilds the
    voice state by replaying the log and warms the FIR up over the 512
    instants before each chunk, so the joined chunks equal one call.
    poly: (m0, pl, pr), the poly output added before the filter.
    fm_level, poly_level: OSD level codes (#76). The chunks are rendered
    unlimited (pcm_wide) and the limiter (limit True/False) runs once over
    the joined render, from start_ns; limit None returns the pcm_wide pairs."""
    from multiprocessing import get_context
    from sim.pcm import limit_frames
    log = sorted(log, key=lambda e: e[0])
    cuts = list(range(start_ns, end_ns, CHUNK_NS)) + [end_ns]
    kw = dict(fm_level=fm_level, poly_level=poly_level, limit=None)
    work = [(log, c0, c1, voices, start_ns, _poly_slice(poly, c0, c1), kw)
            for c0, c1 in zip(cuts, cuts[1:])]
    if (jobs or 0) == 1 or len(work) == 1:
        parts = [_fm_chunk(w) for w in work]
    else:
        with get_context("spawn").Pool(jobs or os.cpu_count()) as pool:
            parts = pool.map(_fm_chunk, work, chunksize=1)
    wide = [x for part in parts for x in part]
    return wide if limit is None else limit_frames(wide, limit)


def write_mix(path, frames, n, gain=1.0):
    """The core's 48 kHz output: pcm_out.sv's 16-bit frames (FM and poly,
    already clipped; one at a rail is counted as clipped); `n` frames.
    gain != 1 scales them, clipped again (not the core's level). Returns
    the number of clipped samples."""
    clipped = 0
    out = bytearray()
    for i in range(n):
        for f in frames[i] if i < len(frames) else (0, 0):
            if f >= 32767 or f <= -32768:
                clipped += 1
            y = f if gain == 1.0 else int(round(f * gain))
            if y > 32767 or y < -32768:
                clipped += 1
                y = max(-32768, min(32767, y))
            out += struct.pack("<h", y)
    with open(path, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", 36 + len(out)) + b"WAVE")
        f.write(b"fmt " + struct.pack("<IHHIIHH", 16, 1, 2, 48_000, 192_000, 4, 16))
        f.write(b"data" + struct.pack("<I", len(out)) + out)
    return clipped


def start_ffmpeg(path, fps):
    cmd = ["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gbrp",
           "-s", "640x480", "-r", "%g" % fps, "-i", "-", "-c:v", "ffv1", path]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE)


# --------------------------------------------------------------------------
# Board

PLAYER = r'''
import json, os, subprocess, sys, time
ev = json.load(open(sys.argv[1]))
rec = float(sys.argv[2])
fd = os.open("/dev/ttyS1", os.O_WRONLY | os.O_NOCTTY)
t0 = time.monotonic()
said = False
for at, kind, data in ev:
    if not said and at >= rec:
        input("setup done: start the HDMI recording, then press Return ")
        t0 = time.monotonic() - at
        said = True
    d = t0 + at - time.monotonic()
    if d > 0:
        time.sleep(d)
    if kind == "keys":
        subprocess.run(["python3", "/tmp/mister_keys.py"] + data)
    else:
        os.write(fd, bytes(data))
print("done")
'''

KEY_GROUP_S = 0.15        # terminal keys this close go in one mister_keys.py call


def board_events(s):
    """Events for the board player: MIDI as byte lists; terminal keys as
    groups of mister_keys.py arguments (ENTER, text:a, ...), one group per
    run of keys at most KEY_GROUP_S apart, at the run's first time."""
    out, last = [], None
    for at, kind, data in s.events:
        if kind != "term":
            out.append((at, "midi", list(data)))
            last = None
            continue
        if isinstance(data, str):
            arg = BOARD_KEYS.get(data, data)
        else:
            c = data.decode("latin-1")
            if not " " <= c <= "~":
                raise ValueError("terminal character %r: not typeable by mister_keys.py" % c)
            arg = "text:" + c
        if last is not None and out and out[-1][1] == "keys" and at - last <= KEY_GROUP_S + 1e-9:
            out[-1][2].append(arg)
        else:
            out.append((at, "keys", [arg]))
        last = at
    return out


def script_baud(s, cli=None):
    """Terminal baud rate: --baud, else the script's `baud:` header, else 9600."""
    baud = int(cli or s.header.get("baud", 9600))
    if baud not in BAUDS:
        raise ValueError("baud %d: one of %s" % (baud, ", ".join(map(str, BAUDS))))
    return baud


def hw(a):
    s = parse(a.script)
    ev = board_events(s)
    baud = script_baud(s)
    if baud != 9600:
        print("note: the script runs the terminal at %d baud; load a state image made with "
              "tools/w0_image.py --baud %d (its name ends -B%d)" % (baud, baud, baud))
    if a.dry_run:
        print(json.dumps(ev, indent=0)[:4000])
        return 0
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(ev, f)
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as g:
        g.write(PLAYER)
    subprocess.run(["scp", "-q", f.name, "%s:/tmp/demo_events.json" % a.host], check=True)
    subprocess.run(["scp", "-q", g.name, "%s:/tmp/demo_player.py" % a.host], check=True)
    subprocess.run(["scp", "-q", os.path.join(ROOT, "scripts", "mister", "mister_keys.py"),
                    "%s:/tmp/mister_keys.py" % a.host], check=True)
    return subprocess.run(["ssh", "-t", a.host, "python3 /tmp/demo_player.py /tmp/demo_events.json %s"
                           % shlex.quote(str(s.record))]).returncode


# --------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("render", help="render a script in the simulator to a video")
    r.add_argument("script")
    r.add_argument("out", help="video file (.mp4)")
    r.add_argument("--images", help="directory of the script's disk images")
    r.add_argument("--fps", type=float, default=30)
    r.add_argument("--height", type=int, default=1080, help="output height (nearest-neighbour scaling)")
    r.add_argument("--boot", type=float, default=12, help="simulated seconds of boot before the script")
    r.add_argument("--tail", type=float, default=1, help="seconds of video after the end")
    r.add_argument("--baud", type=int, help="terminal baud rate (default: the script's baud:, else 9600; "
                   "38400 redraws about 4x faster)")
    r.add_argument("--fm-voices", type=int, default=32)
    r.add_argument("--poly-bins", type=int, default=1)
    r.add_argument("--wav", help="also keep the audio as this WAV")
    r.add_argument("--fm-level", type=int, default=0, choices=range(4),
                   help="OSD FM level code: 0 +12 dB (default), 1 +18, 2 +6, 3 0 dB")
    r.add_argument("--poly-level", type=int, default=0, choices=range(4),
                   help="OSD Poly level code: 0 +6 dB (default), 1 +12, 2 0, 3 -6 dB")
    r.add_argument("--limiter-off", action="store_true", help="OSD Limiter Off: clip at 16 bits")
    r.add_argument("--gain", type=float, default=0,
                   help="dB applied to the mix before clipping (default 0: the core's output)")
    r.add_argument("--jobs", type=int, help="processes for the audio render (default: all CPUs)")
    e = sub.add_parser("events", help="print the compiled events")
    e.add_argument("script")
    h = sub.add_parser("hw", help="play a script on a MiSTer (its MIDI in and keyboard)")
    h.add_argument("script")
    h.add_argument("--host", default="root@192.168.20.62")
    h.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "render":
        return render(a)
    if a.cmd == "hw":
        return hw(a)
    s = parse(a.script)
    print("title: %s  record at %.2f s  end at %.2f s  %d events" % (s.title, s.record, s.end, len(s.events)))
    for at, kind, data in s.events:
        print("%9.3f  %-4s  %s" % (at, kind, data if isinstance(data, str) else data.hex(" ")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
