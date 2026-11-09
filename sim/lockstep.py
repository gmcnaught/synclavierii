"""Lockstep traces: check the HDL against this simulator (M4.3-M4.5).

`record` runs the Python system and writes a trace; hdl/sim/lockstep.cpp
(built with Verilator by `build`) runs the HDL from the same state and
stops at the first difference. Two HDL tops:

  cpu     hdl/able_cpu.sv alone: every device read is answered with the
          value the Python devices returned, every write must match.
  system  hdl/able_system.sv: CPU plus the devices in HDL (D3, D4-D7,
          D50/D51, D60-D63, D100-D104, D130/D131, D160-D165), whose
          values, interrupt bits and timing are compared; any other device
          is answered from the trace.

Trace format v2 (little-endian):
  b"ABLT2\\0\\0\\0"
  16 x u16 registers, u8 flags {pcs, ion, m, c, z} (bit 4 .. bit 0)
  65536 x u16 internal memory
  header sections, then 'B':
    'X' u32 sectors, sectors x 256 x u16   external memory contents
    'V' u8 device u16 index u32 value      HDL device state (system top):
          device 0 D3 (0 elapsed ns, 1 pending), 1 D4567 (0 D4, 1 D5),
          2 D60 (0 sector, 1 word), 3 D50 (0 baud index, 1 rx char,
          2 char_rdy, 3 rx_wait ns, 4 tx_busy ns, 5 xmit_irq), 4 D100
          (fields as hdl/dev/dev_floppy.sv's state load), 5 D160 (as
          dev_fm.sv), 6 wave memory byte (index = memory x 256 + point),
          7 D130 (as dev_keyboard.sv; index 31 = strict)
    'F' u8 drive u16 sectors u8 spt u8 sides u8 protected, words
                                           a floppy in that drive
    'O' u64 rr u16 to_next u8 phase, 16 x (u16 acc u8 prescale u8 point)
                                           voice engine state (audio traces)
    'C' u8 model u16 d57 u16 D51 device bits, u16 page u16 ppc u8 rpt_next
        u8 rpt_left u16 rpt_word u16 rpt_pc u16 d2 u8 shadow
                                           Model C/D CPU state (sim/cpu.py)
  events, in the order the instruction performs them:
    'P' u16       interrupt bits returned by a PSW read (device 001)
    'w' u32       the next read was held (BUS_WAIT) for this many steps
    'R' u8 u16    device read: device, value
    'W' u8 u16    device write: device, value
    'Q' u16       interrupt bits at the end of an instruction with ION and
                  PCS set (the interrupt is taken if nonzero)
    'I' u16 u16   instruction completed: pc, word
    'S' 16 x u16 u8 u64   registers, flags and simulated ns since the start,
                  after the preceding instruction
    'T' u32 u16 bytes   terminal input, fed after this many held steps of
                  the current read (0: before the next instruction)
    'A' i64 i64   audio sample (sim/voice.py FMSynth.sample_int: left, right)
                  at the next 192 kHz render instant (audio traces only)
    'K' u8 u8 u16 host key/button change before the next instruction: 0
                  clavier octave or 1 panel, index, new word
    'H' u8        halted: 1 no SYN on read, 2 no SYN on write, 3 HALT
    'E'           end of trace

Usage:
  python3 -m sim.lockstep random OUT.trace [--instructions N] [--seed S]
  python3 -m sim.lockstep monitor IMAGE OUT.trace [--instructions N]
  python3 -m sim.lockstep ork-lm IMAGE OUT.trace [--instructions N]
  python3 -m sim.lockstep ork-lm-note IMAGE OUT.trace   (timbre recall + C4 held)
  python3 -m sim.lockstep w0boot W0-53.IMG OUT.trace   (Release 5.3 from the
                                    state tools/w0_image.py stores: MONITOR,
                                    PROFILE, PLAY SYN-5.3 over SCSI)
  python3 -m sim.lockstep syn53 W0IMAGE OUT.trace [--skip N]
                                    (Release 5.3: boot W0, CREATE USER, PLAY
                                     SYN-5.3, skip N instructions, record)
  python3 -m sim.lockstep check OUT.trace [--top cpu|system]
"""
import os
import random
import struct
import subprocess

from .bus import BUS_WAIT, NO_SYN, Device

M16 = 0xFFFF
MAGIC = b"ABLT2\0\0\0"
HALT_CODES = {"no SYN on read": 1, "no SYN on write": 2, "HALT": 3}
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD_DIR = os.path.join(ROOT, "out", "hdl-lockstep")
BAUDS = (300, 1200, 2400, 4800, 9600, 19200, 38400, 76800)


class _RecordingBus:
    """Wraps the CPU's bus and records what the CPU sees."""

    def __init__(self, inner, out):
        self.inner = inner
        self.out = out
        self.in_psw = False
        self.waits = 0              # held steps of the current read so far

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def read(self, dev):
        v = self.inner.read(dev)
        if v is not NO_SYN and v is not BUS_WAIT:
            if self.waits:
                self.out += struct.pack("<cI", b"w", self.waits)
            self.out += struct.pack("<cBH", b"R", dev, v & M16)
        return v

    def write(self, dev, value):
        ok = self.inner.write(dev, value)
        if ok:
            self.out += struct.pack("<cBH", b"W", dev, value & M16)
        return ok

    def tick(self, ns):
        self.inner.tick(ns)

    def irq_bits(self):
        v = self.inner.irq_bits()
        self.out += struct.pack("<cH", b"P" if self.in_psw else b"Q", v & 0xFFF0)
        return v


def _flags(cpu):
    return cpu.pcs << 4 | cpu.ion << 3 | cpu.m << 2 | cpu.c << 1 | cpu.z


def _device_header(cpu):
    """'X' and 'V' sections for the HDL devices, if the system has them."""
    out = bytearray()
    devs = [getattr(cpu, a, None) for a in ("rtc", "muldiv", "extmem", "terminal")]
    if None in devs:
        return out
    rtc, md, xm, term = devs
    out += struct.pack("<cI", b"X", xm.sectors) + xm.data.tobytes()
    fd = getattr(cpu, "floppy", None)
    if fd is not None:
        from .devices.floppy import REV_NS
        if fd.buf is not None:
            raise ValueError("floppy is in the middle of a sector transfer")
        for drive, m in enumerate(fd.media):
            if m is not None:
                out += struct.pack("<cBHBBB", b"F", drive, m.sectors, m.spt, m.sides, m.protected)
                out += struct.pack("<%dH" % len(m.words), *m.words)
        kind, lsn, wait = fd.pending or ("read", None, 0)
        for idx, v in enumerate((fd.select, fd.track, fd.sector, fd.data, fd.status, fd.type1,
                                 fd.time % REV_NS, fd.busy_ns, fd.pending is not None,
                                 kind == "write", lsn is None, lsn or 0, wait, False,
                                 fd._kind == "write", fd.head[0], fd.head[1], fd.step_dir < 0)):
            out += struct.pack("<cBHI", b"V", 4, idx, int(v) & 0xFFFFFFFF)
    fm, kb = getattr(cpu, "fm", None), getattr(cpu, "keyboard", None)
    if fm is not None and kb is not None:
        from .fm import wave_memory_number
        nch = 2 * fm.voices
        g = [fm.channel_word, fm.function, fm.switches, fm.ext_clock_in, fm.ext_clock_out,
             fm.adc_select, (fm.time_ns * 24) % 125000, 0] + list(fm.adc)
        for idx, v in enumerate(g):
            out += struct.pack("<cBHI", b"V", 5, idx, int(v) & 0xFFFFFFFF)
        for ch in range(nch):
            it = fm.interpolator(ch)            # advanced to now (lazy in Python)
            r = lambda fn: fm.channels.get((ch, fn), 0) & 0o377
            for k, v in enumerate((it.div, it.add, it.limit, it.value, it.prescale, it.acc,
                                   fm.mar.get(ch, 0),
                                   r(0) << 24 | r(1) << 16 | r(2) << 8 | r(4), r(0o13))):
                out += struct.pack("<cBHI", b"V", 5, 32 + 16 * ch + k, int(v) & 0xFFFFFFFF)
        for m, mem in enumerate(fm.wave):
            for i, b in enumerate(mem):
                if b:
                    out += struct.pack("<cBHI", b"V", 6, m * 256 + i, b)
        for idx, v in enumerate([kb.creg, kb.dreg] + kb.clavier + kb.buttons + kb.lights
                                + kb.display):
            out += struct.pack("<cBHI", b"V", 7, idx, int(v) & 0xFFFFFFFF)
        out += struct.pack("<cBHI", b"V", 7, 31, bool(kb.strict and fm.strict))
        assert kb.strict == fm.strict
    for dev, idx, v in ((0, 0, rtc.elapsed), (0, 1, rtc.pending),
                        (1, 0, md.d4), (1, 1, md.d5),
                        (2, 0, xm.sector), (2, 1, xm.word),
                        (3, 0, BAUDS.index(term.baud)), (3, 1, term.rx_char),
                        (3, 2, term.char_rdy), (3, 3, term.rx_wait), (3, 4, term.tx_busy),
                        (3, 5, term.xmit_irq)):
        out += struct.pack("<cBHI", b"V", dev, idx, int(v) & 0xFFFFFFFF)
    return out


OSC_NUM, OSC_D = 656015360, 123_000_000_000      # sim/voice.py OSC_CLOCK = NUM / D per ns
SAMPLE_RATE = 192_000                             # render instants: 48 kHz x 4


class _Audio:
    """A live sim/voice.py FMSynth fed from the FM interface's log, sampled
    at the render instants start + k x 1e9 // 192000 (start = trace start)."""

    def __init__(self, fm):
        from .voice import FMSynth
        if len(fm.log) >= fm.log_len:
            raise ValueError("FM log was truncated; cannot rebuild the voice state")
        self.fm = fm
        fm.log_len = 1 << 62
        self.synth = FMSynth(fm.voices)
        for e in fm.log:
            self.synth.write(*e)
        self.n = len(fm.log)
        self.start = fm.time_ns
        self.synth.advance_all(self.start)
        self.k = 0

    def header(self):
        out = struct.pack("<cQHB", b"O", self.start * OSC_NUM % OSC_D, 0, 0)
        for ch in self.synth.ch:
            o = ch.osc
            out += struct.pack("<HBB", o.acc, o.prescale, o.point)
        return out

    def samples(self, ev):
        """After a step: apply its writes, emit the samples before now."""
        log = self.fm.log
        while self.n < len(log):
            self.synth.write(*log[self.n])
            self.n += 1
        now = self.fm.time_ns
        while True:
            t = self.start + self.k * 1_000_000_000 // SAMPLE_RATE
            if t >= now:
                break
            ev += struct.pack("<cqq", b"A", *self.synth.sample_int(t))
            self.k += 1


def record(cpu, path, instructions, snapshot_every=256, max_steps=None, max_wait=10_000,
           on_wait=None, actions=(), audio=False):
    """Run `cpu` for `instructions` completed instructions, writing a trace
    to `path`. Stops early if the CPU halts, or if a read stays held for
    `max_wait` steps (a program waiting for terminal input) and
    `on_wait(cpu)` is absent or returns False (it may feed input and
    return True to go on). `actions`: (ns after the start, callable(cpu))
    host actions on devices the HDL does not model (panel buttons, keys),
    run between instructions. audio=True also records the voice engine's
    samples (sim/voice.py), for the system top. Returns the number recorded."""
    actions = sorted(actions, key=lambda a: a[0])
    out = bytearray(MAGIC)
    out += struct.pack("<16HB", *cpu.r, _flags(cpu))
    out += struct.pack("<65536H", *cpu.mem)
    out += _device_header(cpu)
    if cpu.model != "B":
        term = getattr(cpu, "terminal", None)
        out += struct.pack("<cBHHHHBBHHHB", b"C", "ABCD".index(cpu.model), cpu.d57,
                           term.device_bits if term else 0, cpu.page, cpu.ppc,
                           cpu.rpt_next, cpu.rpt_left, cpu.rpt_word, cpu.rpt_pc, cpu.d2,
                           cpu.int_shadow)
    aud = _Audio(cpu.fm) if audio else None
    if aud:
        out += aud.header()
    out += b"B"
    t0 = cpu.time_ns
    ev = bytearray()
    rbus = _RecordingBus(cpu.bus, ev)
    cpu.bus = rbus
    term = getattr(cpu, "terminal", None)
    if term is not None:
        if term.input:
            ev += struct.pack("<cIH", b"T", 0, len(term.input)) + bytes(term.input)
        feed = term.feed

        def recorded_feed(data):
            b = data.encode("latin-1") if isinstance(data, str) else bytes(data)
            ev.extend(struct.pack("<cIH", b"T", rbus.waits, len(b)) + b)
            feed(b)
        term.feed = recorded_feed

    kb = getattr(cpu, "keyboard", None)
    if kb is not None:
        press_key, press_button = kb.press_key, kb.press_button

        def recorded_key(key, down=True):
            press_key(key, down)
            octave = (key - 12) // 12
            ev.extend(struct.pack("<cBBH", b"K", 0, octave, kb.clavier[octave]))

        def recorded_button(pbn, down=True):
            press_button(pbn, down)
            ev.extend(struct.pack("<cBBH", b"K", 1, pbn // 16, kb.buttons[pbn // 16]))
        kb.press_key, kb.press_button = recorded_key, recorded_button

    def snapshot(time_ns=None):
        t = cpu.time_ns if time_ns is None else time_ns
        return b"S" + struct.pack("<16HBQ", *cpu.r, _flags(cpu), t - t0)
    t_done = t0                   # time at the end of the last completed instruction
    mark = 0                      # end of its events in `ev`; later ones are dropped
    snap_at_mark = False
    read_psw = cpu.read_psw

    def psw():
        rbus.in_psw = True
        try:
            return read_psw()
        finally:
            rbus.in_psw = False
    cpu.read_psw = psw
    n = steps = waits = 0
    max_steps = max_steps or 50 * instructions + 1_000_000
    try:
        with open(path, "wb") as f:
            f.write(out)
            while n < instructions and steps < max_steps:
                while actions and cpu.time_ns - t0 >= actions[0][0]:
                    actions.pop(0)[1](cpu)
                steps += 1
                if cpu.rpt_left:                  # Model C repeat: same instruction
                    pc, word = cpu.rpt_pc, cpu.rpt_word
                else:
                    pc = cpu.pc
                    base = cpu._paged(cpu.pcs)
                    word = cpu.mem[pc] if base is None else cpu._code_read(base, pc)
                running = cpu.step()
                if aud and not cpu.halted and cpu.waiting is not None:
                    aud.samples(ev)          # a held step: time ran, no instruction
                if cpu.halted:
                    if cpu.halted.reason == "HALT":
                        ev += struct.pack("<cHH", b"I", pc, word)   # completed, then halted
                    ev += struct.pack("<cB", b"H", HALT_CODES[cpu.halted.reason])
                    mark, snap_at_mark = len(ev), True    # no snapshot after a halt
                    break
                if cpu.waiting is not None:
                    waits += 1               # held read: the instruction did not complete
                    rbus.waits = waits
                    if waits >= max_wait:
                        if not (on_wait and on_wait(cpu)):
                            break
                        waits = rbus.waits = 0
                    continue
                waits = rbus.waits = 0
                t_done = cpu.time_ns
                ev += struct.pack("<cHH", b"I", pc, word)
                n += 1
                snap_at_mark = n % snapshot_every == 0
                if snap_at_mark:
                    ev += snapshot()
                if aud:
                    aud.samples(ev)
                if len(ev) > 1 << 20:
                    f.write(ev)
                    del ev[:]
                mark = len(ev)
                if not running:
                    break
            del ev[mark:]             # input fed while a read is still held at the end
            if not snap_at_mark:
                ev += snapshot(t_done)
            ev += b"E"
            f.write(ev)
    finally:
        cpu.bus = rbus.inner
        del cpu.read_psw
        if term is not None:
            del term.feed
        if kb is not None:
            del kb.press_key, kb.press_button
    return n


EDGE_VALUES = (0, 1, 2, 0o77, 0o100, 0o377, 0o400, 0x7FFF, 0x8000, 0x8001, 0xFFFE, 0xFFFF)


def random_value(rng):
    """16-bit value, half the time an edge case (so equal operands, carries
    and sign changes are common)."""
    if rng.random() < 0.5:
        return rng.randrange(0x10000)
    return rng.choice(EDGE_VALUES)


class RandomDevice(Device):
    """Answers every device number with pseudo-random data and drives
    pseudo-random interrupt requests (for random-program lockstep runs)."""

    def __init__(self, seed):
        self.rng = random.Random(seed)
        self.irq = 0

    def read(self, dev):
        return random_value(self.rng)

    def write(self, dev, value):
        return True

    def tick(self, ns):
        if self.rng.random() < 0.05:
            self.irq = self.rng.choice((0, 0, 1 << self.rng.randrange(4, 16),
                                        self.rng.randrange(0x10000)))

    def irq_bits(self):
        return self.irq


def random_cpu(seed, model="B"):
    """A CPU with random memory, registers and flags; every device random."""
    from .cpu import CPU
    rng = random.Random(seed)
    cpu = CPU()
    cpu.model = model
    cpu.bus.attach(RandomDevice(seed + 1), [n for n in range(0o200) if n != 1])
    cpu.mem = [rng.randrange(0x10000) for _ in range(0x10000)]   # code: uniform
    for _ in range(0x4000):                                     # data: some edge cases
        cpu.mem[rng.randrange(0x10000)] = random_value(rng)
    cpu.r = [random_value(rng) for _ in range(16)]
    cpu.z, cpu.c, cpu.m, cpu.ion, cpu.pcs = (rng.random() < 0.5 for _ in range(5))
    if not cpu.pcs:
        cpu.ion = False
    return cpu


SYSTEM_RTL = ["hdl/able_cpu.sv", "hdl/code_cache.sv", "hdl/dev/dev_rtc.sv", "hdl/dev/dev_muldiv.sv",
              "hdl/dev/dev_extmem.sv", "hdl/dev/dev_terminal.sv",
              "hdl/dev/dev_floppy.sv", "hdl/dev/dev_keyboard.sv",
              "hdl/dev/dev_fm.sv", "hdl/dev/fm_voices.sv",
              "hdl/dev/pcm_out.sv", "hdl/throttle.sv", "hdl/able_system.sv"]
CORE_RTL = ["hdl/core/sd_floppy.sv", "hdl/dev/dev_scsi.sv", "hdl/dev/dev_poly.sv",
            "hdl/core/boot_loader.sv", "hdl/core/term_display.sv",
            "hdl/core/ps2_ascii.sv", "hdl/core/midi_in.sv", "hdl/core/panel_mouse.sv", "hdl/core/audio_fifo.sv",
            "hdl/core/synclavier_core.sv",
            "hdl/board/ddram_word.sv"]
TOPS = {
    "cpu": ("able_sim_top", ["hdl/able_cpu.sv", "hdl/sim/able_sim_top.sv"], []),
    "system": ("able_sys_top", SYSTEM_RTL + ["hdl/sim/able_sys_top.sv"], ["-DSYSTEM"]),
    # the MiSTer core from power-on (boot loader, SD floppies, DDR3, display)
    "board": ("board_top", SYSTEM_RTL + CORE_RTL + ["hdl/sim/board_top.sv"], ["-DBOARD"]),
}
INCLUDES = ["hdl/core/boot_defaults.svh", "hdl/core/font8x8.svh", "hdl/core/panel_labels.svh",
            "hdl/dev/sine_rom.svh"]


def build(top="cpu", force=False):
    """Build the Verilator bench for `top` ("cpu", "system" or "board");
    returns the executable path."""
    name, rtl, defines = TOPS[top]
    mdir = os.path.join(BUILD_DIR, top)
    exe = os.path.join(mdir, "V" + name)
    srcs = [os.path.join(ROOT, p) for p in rtl + ["hdl/sim/lockstep.cpp"] + INCLUDES]
    if not force and os.path.exists(exe) and \
            os.path.getmtime(exe) > max(os.path.getmtime(s) for s in srcs):
        return exe
    os.makedirs(mdir, exist_ok=True)          # older Verilator does not create parents
    subprocess.run(["verilator", "--cc", "--exe", "--build", "-O3", "-Wall", "-Wno-fatal",
                    "--x-assign", "unique", "--x-initial", "unique",
                    "-I" + os.path.join(ROOT, "hdl", "dev"), "-I" + os.path.join(ROOT, "hdl", "core"),
                    "--top-module", name, "-Mdir", mdir, "-o", "V" + name,
                    "-CFLAGS", "-O2 " + " ".join(defines)]
                   + [x for x in srcs if not x.endswith(".svh")],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return exe


def check(path, max_instructions=None, top="cpu", wav=None, realtime=False, frame=None,
          state=None, w0=None):
    """Run a trace on the HDL. Returns (ok, output text). wav: write the
    system's 48 kHz PCM output (pcm_out.sv) to this WAV file. realtime:
    run the system with the throttle on (50 MHz); behaviour must not change
    and simulated time must track the clock. frame (board): write a video
    frame (PGM) taken after the run. state (board): a state image
    (tools/state_image.py) to boot from instead of F0."""
    cmd = [build(top), path] + ([str(max_instructions)] if max_instructions else [])
    env = dict(os.environ)
    if frame:
        env["LOCKSTEP_FRAME"] = frame
    if state:
        env["LOCKSTEP_STATE"] = state
    if w0:
        env["LOCKSTEP_W0"] = w0
    if wav:
        env["LOCKSTEP_WAV"] = wav
    if realtime:
        env["LOCKSTEP_REALTIME"] = "1"
    p = subprocess.run(cmd, capture_output=True, text=True, env=env)
    return p.returncode == 0, p.stdout + p.stderr


def expected_wav(trace_path, wav_path):
    """The WAV sim/voice.py render() + write_wav() give for the audio samples
    in a trace (groups of 4 from the trace start). Returns the frame count."""
    from .voice import FULL_SCALE, write_wav
    samples = [s for s in _trace_audio(trace_path)]
    frames = []
    for i in range(0, len(samples) - 3, 4):
        acc_l = acc_r = 0.0
        for l, r in samples[i:i + 4]:
            acc_l += l / FULL_SCALE
            acc_r += r / FULL_SCALE
        frames.append((acc_l / 4, acc_r / 4))
    write_wav(wav_path, frames)
    return len(frames)


def _trace_audio(path):
    """The 'A' samples of a trace, in order."""
    b = open(path, "rb").read()
    p = len(MAGIC) + 33 + 131072
    while True:
        k = b[p:p + 1]
        p += 1
        if k == b"B":
            break
        if k == b"X":
            p += 4 + struct.unpack_from("<I", b, p)[0] * 512
        elif k == b"F":
            p += 6 + struct.unpack_from("<H", b, p + 1)[0] * 512
        elif k == b"V":
            p += 7
        elif k == b"O":
            p += 11 + 64
        elif k == b"C":
            p += 18
    sizes = {b"P": 2, b"R": 3, b"W": 3, b"Q": 2, b"I": 4, b"S": 41, b"H": 1, b"E": 0,
             b"w": 4, b"K": 4, b"A": 16}
    while p < len(b):
        k = b[p:p + 1]
        p += 1
        if k == b"T":
            p += 6 + struct.unpack_from("<H", b, p + 4)[0]
            continue
        if k == b"A":
            yield struct.unpack_from("<qq", b, p)
        p += sizes[k]


def ork_lm_note_actions(cpu, dbg, image):
    """Run ORK-LM to its main loop (not recorded), put the timbre floppy in
    F0, and return the panel/key actions: recall bank 0 timbre 0, hold C4
    for 0.5 s. The floppy, FM and keyboard accesses all land in the trace."""
    from .boot import insert_floppy
    from .devices.synth import button_number
    from .rtp import run_seconds
    if run_seconds(cpu, dbg, 8):
        raise RuntimeError("ORK-LM stopped:\n" + dbg.report())
    insert_floppy(cpu, image, 0, "06-TIMBD")
    kb = cpu.keyboard
    ms = 1_000_000
    return [(0, lambda c: kb.press_button(button_number("bank.0"))),
            (100 * ms, lambda c: kb.press_button(button_number("bank.0"), False)),
            (1600 * ms, lambda c: kb.press_button(button_number("timb.0"))),
            (1700 * ms, lambda c: kb.press_button(button_number("timb.0"), False)),
            (3200 * ms, lambda c: kb.press_key(48)),
            (3700 * ms, lambda c: kb.press_key(48, False))]


def w0_poly_actions(cpu):
    """Panel and key actions for a W0 boot with poly voices: SYN-5.3 is at
    its Main Menu by 10.3 s; recall bank 2 entry 1 (CLARA3, a sound file
    loaded into poly memory over SCSI), then hold key 45 (A, the file's
    pitch) for 0.6 s."""
    from .devices.synth import button_number
    kb = cpu.keyboard
    ms = 1_000_000
    b, e = button_number("bank.1"), button_number("timb.0")
    return [(10_600 * ms, lambda c: kb.press_button(b)),
            (10_700 * ms, lambda c: kb.press_button(b, False)),
            (12_200 * ms, lambda c: kb.press_button(e)),
            (12_300 * ms, lambda c: kb.press_button(e, False)),
            (16_000 * ms, lambda c: kb.press_key(45)),
            (16_600 * ms, lambda c: kb.press_key(45, False))]


def syn53_cpu(image, skip=0):
    """Release 5.3 from a W0 image (sim.boot.boot_from_w0, 30 MB disk): boot
    to Ready, CREATE USER, SET RTP SYN-5.3, PLAY, then `skip` instructions."""
    from .boot import boot_from_w0
    cpu, _ = boot_from_w0(image, disk_mb=30)

    def until(pred, limit):
        n = 0
        while n < limit and not cpu.halted and not pred():
            n += cpu.run(100_000)
    until(lambda: b"Ready >" in bytes(cpu.terminal.out), 30_000_000)
    for cmd in (b"create user\r", b"set rtp syn-5.3\r", b"play\r"):
        k = bytes(cpu.terminal.out).count(b"Ready >")
        cpu.terminal.feed(cmd)
        if cmd != b"play\r":
            until(lambda: bytes(cpu.terminal.out).count(b"Ready >") > k, 10_000_000)
    n = 0
    while n < skip and not cpu.halted:
        n += cpu.run(min(100_000, skip - n))
    if cpu.halted:
        raise RuntimeError("SYN-5.3 stopped: %s" % (cpu.halted,))
    return cpu


def main(argv=None):
    import argparse
    import sys
    import time
    ap = argparse.ArgumentParser(description="Record / check HDL lockstep traces (M4.3)")
    ap.add_argument("mode", choices=("random", "monitor", "ork-lm", "ork-lm-note", "syn53", "w0boot", "check"))
    ap.add_argument("--skip", type=int, default=0, help="syn53: instructions to run before recording")
    ap.add_argument("args", nargs="+", help="[IMAGE] TRACE")
    ap.add_argument("--instructions", type=int, default=1_000_000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--model", default="B")
    ap.add_argument("--top", choices=tuple(TOPS), default="cpu", help="HDL top for check")
    ap.add_argument("--audio", action="store_true", help="also record voice engine samples")
    ap.add_argument("--wav", help="check --top system: write the HDL's 48 kHz PCM to this WAV")
    ap.add_argument("--realtime", action="store_true", help="check --top system with the throttle on")
    ap.add_argument("--state", help="check --top board: state image (S2)")
    ap.add_argument("--w0", help="check --top board: SCSI disk image (S3)")
    ap.add_argument("--poly", action="store_true",
                    help="w0boot: with poly voices (sim/devices/poly.py); at 10.6 s recall "
                         "bank 2 entry 1 (W0:CLARA3) and hold key 45 at 16 s")
    a = ap.parse_args(argv)
    if a.mode == "check":
        ok, text = check(a.args[0], top=a.top, wav=a.wav, realtime=a.realtime, state=a.state,
                         w0=a.w0)
        print(text, end="")
        return 0 if ok else 1
    t = time.time()
    if a.mode == "random":
        cpu, path = random_cpu(a.seed, a.model), a.args[0]
    elif a.mode == "syn53":
        cpu = syn53_cpu(a.args[0], a.skip)
        path = a.args[1]
    elif a.mode == "w0boot":
        from .boot import boot_from_w0
        poly = None
        if a.poly:
            from .devices.poly import PolySynth
            poly = PolySynth()
        cpu, _ = boot_from_w0(a.args[0], poly=poly)
        path = a.args[1]
    elif a.mode == "monitor":
        from .boot import boot_from_image
        cpu, _ = boot_from_image(a.args[0], "03-SYSTD", f1="18-UTILS")
        lines = ["CATALOG\r"]

        def on_wait(cpu):          # type the next command at each prompt
            if lines:
                cpu.terminal.feed(lines.pop(0))
                return True
            return False
        path = a.args[1]
    elif a.mode not in ("syn53", "w0boot"):
        from .rtp import start_rtp
        cpu, dbg, _ = start_rtp(a.args[0], "ORK-LM")
        path = a.args[1]
    actions = []
    if a.mode == "ork-lm-note":
        actions = ork_lm_note_actions(cpu, dbg, a.args[0])
    if a.mode == "w0boot" and a.poly:
        actions = w0_poly_actions(cpu)
    n = record(cpu, path, a.instructions, on_wait=on_wait if a.mode == "monitor" else None,
               actions=actions, audio=a.audio)
    if a.mode == "monitor":
        print(cpu.terminal.text()[-300:], file=sys.stderr)
    print("recorded %d instructions in %.1f s -> %s%s" % (
        n, time.time() - t, path, " (halted: %s)" % (cpu.halted,) if cpu.halted else ""),
        file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
