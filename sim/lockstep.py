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
          2 char_rdy, 3 rx_wait ns, 4 tx_busy ns, 5 xmit_irq; 8 poly
          memory size per bin in 128 KB units, to able_system; 9 VT640
          graphics terminal, to term_display; 10 D44/D45/D54 mouse; 11 SCSI
          disk time, ns per block; 12 SCSI seek ns; 13 poly bins, when
          more than 1), 4 D100
          (fields as hdl/dev/dev_floppy.sv's state load), 5 D160 (as
          dev_fm.sv; 16 FM voices present), 6 wave memory byte (index = memory x 256 + point),
          7 D130 (as dev_keyboard.sv; index 30 = velocity keyboard
            (dev_vpk.sv) instead, 31 = strict)
    'F' u8 drive u16 sectors u8 spt u8 sides u8 protected, words
                                           a floppy in that drive
    'O' u64 rr u16 to_next u8 phase u8 n, n x (u16 acc u8 prescale u8 point)
                                           voice engine state, channels 0..n-1
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
                  clavier octave or 1 panel, index, new word; 2-7 velocity
                  keyboard host op (kind - 2, addr, data); 8 a byte into
                  the MIDI card's input FIFO (index 0, byte; board top); 9 a
                  mouse packet (index buttons, word dX << 8 | dY, 8-bit
                  two's complement; board top)
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
        out += struct.pack("<cBHI", b"V", 5, 16, fm.voices)        # voices present
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
        from .devices.synth import VelocityKeyboard
        if isinstance(kb, VelocityKeyboard):
            # dev_vpk.sv has no load port: it starts as at power-on
            fresh = VelocityKeyboard(kb.strict)
            if any(getattr(kb, f) != getattr(fresh, f) for f in
                   ("creg", "dreg", "request", "keys", "reported", "velocity", "pressure",
                    "analog", "switches", "banks", "lights", "chars")):
                raise ValueError("velocity keyboard state is not the power-on state")
            out += struct.pack("<cBHI", b"V", 7, 30, 1)
        else:
            for idx, v in enumerate([kb.creg, kb.dreg] + kb.clavier + kb.buttons + kb.lights
                                    + kb.display):
                out += struct.pack("<cBHI", b"V", 7, idx, int(v) & 0xFFFFFFFF)
        out += struct.pack("<cBHI", b"V", 7, 31, bool(kb.strict and fm.strict))
        assert kb.strict == fm.strict
    card = getattr(cpu, "midi", None)
    if card is not None and (card.sel or card.mcha or card.fifo):
        raise ValueError("MIDI card state is not the power-on state (dev_midi.sv has no load port)")
    from .devices.poly import PolySynth
    if getattr(term, "vt640", False):                       # VT640 graphics terminal
        out += struct.pack("<cBHI", b"V", 3, 9, 1)
    sc = getattr(cpu, "scsi", None)
    if sc is not None:
        sc.head = None          # dev_scsi.sv starts with no head position (no load port)
    if sc is not None and sc.block_ns:                      # SCSI disk time per block
        if sc.timed or sc.phase != 0:
            raise ValueError("SCSI host mid-command (dev_scsi.sv has no load port)")
        out += struct.pack("<cBHI", b"V", 3, 11, sc.block_ns)
        if sc.seek_ns:                                      # SCSI seek time
            out += struct.pack("<cBHI", b"V", 3, 12, sc.seek_ns)
    m = getattr(cpu, "mouse", None)
    if m is not None:                                       # D44/D45/D54 mouse
        if m.dx or m.dy or m.out or m.ready or m.enables or m.buttons:
            raise ValueError("mouse state is not the power-on state (dev_mouse.sv has no load port)")
        out += struct.pack("<cBHI", b"V", 3, 10, 1)
    if isinstance(getattr(cpu, "poly", None), PolySynth):   # poly memory size, 128 KB units
        out += struct.pack("<cBHI", b"V", 3, 8, cpu.poly.sectors // 256)
        if cpu.poly.nbins != 1:                             # poly bins (a 6400: 2)
            out += struct.pack("<cBHI", b"V", 3, 13, cpu.poly.nbins)
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
        out = struct.pack("<cQHBB", b"O", self.start * OSC_NUM % OSC_D, 0, 0, len(self.synth.ch))
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
    vpk_wrapped = ()
    if kb is not None and hasattr(kb, "set_analog"):     # velocity keyboard: 'K' kind 2 + op
        from .devices.synth import VPK_ANALOG, VPK_KEY_OFFSET
        orig = {f: getattr(kb, f) for f in ("press_key", "press_button", "set_analog", "set_pressure")}

        def k_event(op, addr, data):
            ev.extend(struct.pack("<cBBH", b"K", 2 + op, addr & 0xFF, data & 0xFF))

        def v_key(key, down=True, velocity=100):
            orig["press_key"](key, down, velocity)
            k_event(0 if down else 1, key - VPK_KEY_OFFSET, max(1, min(127, velocity)) if down else 0)

        def v_button(pbn, down=True):
            orig["press_button"](pbn, down)
            k_event(2, pbn, int(bool(down)))

        def v_analog(name, value):
            orig["set_analog"](name, value)
            k_event(3, VPK_ANALOG.index(name) if isinstance(name, str) else name, value)

        def v_pressure(key, value):
            orig["set_pressure"](key, value)
            k_event(5, key - VPK_KEY_OFFSET, value)
        kb.press_key, kb.press_button, kb.set_analog, kb.set_pressure = (
            v_key, v_button, v_analog, v_pressure)
        vpk_wrapped = tuple(orig)
    elif kb is not None:
        press_key, press_button = kb.press_key, kb.press_button

        def recorded_key(key, down=True):
            press_key(key, down)
            octave = (key - 12) // 12
            ev.extend(struct.pack("<cBBH", b"K", 0, octave, kb.clavier[octave]))

        def recorded_button(pbn, down=True):
            press_button(pbn, down)
            ev.extend(struct.pack("<cBBH", b"K", 1, pbn // 16, kb.buttons[pbn // 16]))
        kb.press_key, kb.press_button = recorded_key, recorded_button

    mouse = getattr(cpu, "mouse", None)
    if mouse is not None:                                # mouse packet: 'K' kind 9
        mouse_host = mouse.host

        def recorded_host(dx, dy, buttons):
            mouse_host(dx, dy, buttons)
            ev.extend(struct.pack("<cBBH", b"K", 9, buttons & 7,
                                  (max(-127, min(127, dx)) & 0xFF) << 8 | (max(-127, min(127, dy)) & 0xFF)))
        mouse.host = recorded_host

    card = getattr(cpu, "midi", None)
    if card is not None:                                 # MIDI card input: 'K' kind 8
        card_receive = card.receive

        def recorded_receive(byte):
            card_receive(byte)
            ev.extend(struct.pack("<cBBH", b"K", 8, 0, byte & 0xFF))
        card.receive = recorded_receive

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
        if card is not None:
            del card.receive
        if mouse is not None:
            del mouse.host
        if vpk_wrapped:
            for f in vpk_wrapped:
                delattr(kb, f)
        elif kb is not None:
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
              "hdl/dev/dev_floppy.sv", "hdl/dev/dev_keyboard.sv", "hdl/dev/dev_vpk.sv",
              "hdl/dev/dev_fm.sv",
              "hdl/dev/pcm_out.sv", "hdl/throttle.sv", "hdl/voice_clock.sv", "hdl/able_system.sv"]
CORE_RTL = ["hdl/core/sd_floppy.sv", "hdl/dev/dev_scsi.sv", "hdl/dev/dev_poly.sv", "hdl/dev/dev_midi.sv", "hdl/dev/dev_mouse.sv",
            "hdl/core/boot_loader.sv", "hdl/core/term_display.sv", "hdl/core/tek_plane.sv",
            "hdl/core/ps2_ascii.sv", "hdl/core/midi_in.sv", "hdl/core/midi_vpk.sv", "hdl/core/midi_card_feed.sv",
            "hdl/core/panel_mouse.sv", "hdl/core/audio_fifo.sv",
            "hdl/core/synclavier_core.sv",
            "hdl/board/ddram_word.sv"]
TOPS = {
    "cpu": ("able_sim_top", ["hdl/able_cpu.sv", "hdl/sim/able_sim_top.sv"], []),
    "system": ("able_sys_top", SYSTEM_RTL + ["hdl/sim/able_sys_top.sv"], ["-DSYSTEM"]),
    # the MiSTer core from power-on (boot loader, SD floppies, DDR3, display)
    "board": ("board_top", SYSTEM_RTL + CORE_RTL + ["hdl/sim/board_top.sv"], ["-DBOARD"]),
}
INCLUDES = ["hdl/core/boot_defaults.svh", "hdl/core/font8x8.svh", "hdl/core/midi_tables.svh", "hdl/core/panel_labels.svh",
            "hdl/dev/sine_rom.svh", "hdl/dev/fm_num_rom.svh"]


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
          state=None, w0=None, w1=None, rt_voices=False, stall=None):
    """Run a trace on the HDL. Returns (ok, output text). wav: write the
    system's 48 kHz PCM output (pcm_out.sv) to this WAV file. realtime:
    run the system with the throttle on (50 MHz); behaviour must not change
    and simulated time must track the clock. frame (board): write a video
    frame (PGM) taken after the run. state (board): a state image
    (tools/state_image.py) to boot from instead of F0. rt_voices (system,
    with realtime): the voices on real time (voice_clock.sv, M14); audio is
    counted instead of compared. stall (system): (instruction, clocks), hold
    the CPU that long before it fetches that instruction."""
    cmd = [build(top), path] + ([str(max_instructions)] if max_instructions else [])
    env = dict(os.environ)
    if frame:
        env["LOCKSTEP_FRAME"] = frame
    if state:
        env["LOCKSTEP_STATE"] = state
    if w0:
        env["LOCKSTEP_W0"] = w0
    if w1:
        env["LOCKSTEP_W1"] = w1
    if wav:
        env["LOCKSTEP_WAV"] = wav
    if realtime:
        env["LOCKSTEP_REALTIME"] = "1"
    if rt_voices:
        env["LOCKSTEP_RT_VOICES"] = "1"
    if stall:
        env["LOCKSTEP_STALL"] = "%d,%d" % stall
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
            p += 12 + 4 * b[p + 11]
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


def w0_vpk_actions(cpu):
    """Velocity keyboard actions for a W0 boot with poly voices (as
    w0_poly_actions): BANK 2, ENTRY 1 on the VPK panel (CLARA3), key 45 with
    velocity 100 and pressure, mod and pitch wheels, then partial volume
    selected and the knob deflected (one step down)."""
    from .devices.synth import vpk_button_number as B
    kb = cpu.keyboard
    ms = 1_000_000
    acts = []
    for t, name in ((10_600, "bankb"), (10_900, "timb.1"), (12_500, "entryb"), (12_800, "timb.0")):
        acts += [(t * ms, lambda c, n=name: kb.press_button(B(n))),
                 ((t + 100) * ms, lambda c, n=name: kb.press_button(B(n), False))]
    acts += [(16_000 * ms, lambda c: kb.press_key(45, velocity=100)),
             (16_100 * ms, lambda c: kb.set_pressure(45, 90)),
             (16_200 * ms, lambda c: kb.set_analog("mod wheel", 150)),
             (16_300 * ms, lambda c: kb.set_analog("pitch wheel", 170)),
             (16_600 * ms, lambda c: kb.press_key(45, False)),
             (16_700 * ms, lambda c: kb.set_analog("pitch wheel", 128)),
             (16_800 * ms, lambda c: kb.press_button(B("pvol"))),
             (16_900 * ms, lambda c: kb.press_button(B("pvol"), False)),
             (17_200 * ms, lambda c: kb.set_analog("knob", 88)),
             (17_220 * ms, lambda c: kb.set_analog("knob", 128))]
    return acts


def w0_bin_actions(cpu, b=1):
    """Before w0_vpk_actions on a system with more than one poly bin: hold
    TRACK ROUTING and press timbre button b + 1, which makes bin b the
    keyboard timbre's poly bin (175-PRF5:135-149, THD.POLY of track 0), so
    the sound file the recall loads (CLARA3) goes into bin b and its notes
    play on bin b's voices (198-SYN2 ALLOC.SUB). With w0_vpk_actions' key 45
    it also holds 8 more keys, so 9 voices of bin b sound together (9 poly
    memory reads per 48 kHz mix, several in flight on DDR3)."""
    from .devices.synth import vpk_button_number as B
    kb = cpu.keyboard
    ms = 1_000_000
    t = "timb.%d" % b
    acts = [(10_300 * ms, lambda c: kb.press_button(B("trrout"))),
            (10_380 * ms, lambda c: kb.press_button(B(t))),
            (10_440 * ms, lambda c: kb.press_button(B(t), False)),
            (10_500 * ms, lambda c: kb.press_button(B("trrout"), False))]
    for i, k in enumerate((36, 38, 40, 41, 43, 47, 48, 50)):   # 2 us apart: one 'K' per instruction
        acts += [(16_000 * ms + 2000 * (i + 1), lambda c, k=k: kb.press_key(k, velocity=90)),
                 (16_600 * ms + 2000 * (i + 1), lambda c, k=k: kb.press_key(k, False))]
    return acts


def w0_midi_actions(cpu):
    """MIDI card actions for a W0 boot with the velocity keyboard and the
    MIDI card (cpu.midi): BANK 1, ENTRY 2 on the VPK panel (SIMPLE FM SINE),
    then MIDI in through the card at 31250-baud byte spacing: note 60 on
    (velocity 100), mod wheel, pitch bend, note off, and a clock; then STOP
    twice, which sends All Notes Off (Bn 7B 00, n = 0-15) on each output."""
    from .devices.synth import vpk_button_number as B
    kb, card = cpu.keyboard, cpu.midi
    ms, us = 1_000_000, 1_000
    acts = []
    for t, name in ((10_600, "bankb"), (10_900, "timb.0"), (12_500, "entryb"), (12_800, "timb.1"),
                    (16_000, "stop"), (16_300, "stop")):
        acts += [(t * ms, lambda c, n=name: kb.press_button(B(n))),
                 ((t + 100) * ms, lambda c, n=name: kb.press_button(B(n), False))]
    for t, msg in ((14_500, (0x90, 60, 100)), (14_700, (0xB0, 1, 90)), (14_800, (0xE0, 0, 100)),
                   (15_200, (0x80, 60, 0)), (15_300, (0xF8,))):
        for i, b in enumerate(msg):
            acts.append((t * ms + 320 * us * i, lambda c, b=b: card.receive(b)))
    return acts


def w0_chord_actions(cpu):
    """Velocity keyboard actions for a W0 boot: BANK 1, ENTRY 2 on the VPK
    panel (SIMPLE FM SINE), then 20 keys (30-49) pressed 20 ms apart from
    14.5 s, all released at 15.6 s: more voices than 8 FM voices hold."""
    from .devices.synth import vpk_button_number as B
    kb = cpu.keyboard
    ms = 1_000_000
    acts = []
    for t, name in ((10_600, "bankb"), (10_900, "timb.0"), (12_500, "entryb"), (12_800, "timb.1")):
        acts += [(t * ms, lambda c, n=name: kb.press_button(B(n))),
                 ((t + 100) * ms, lambda c, n=name: kb.press_button(B(n), False))]
    for i, key in enumerate(range(30, 50)):
        acts += [((14_500 + 20 * i) * ms, lambda c, k=key: kb.press_key(k, velocity=90)),
                 ((15_600 + 5 * i) * ms, lambda c, k=key: kb.press_key(k, False))]
    return acts


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
    ap.add_argument("--w1", help="w0boot: a second SCSI disk (W1, target 4) and a 3-entry "
                                 "device table; check --top board: its image (S4)")
    ap.add_argument("--poly", action="store_true",
                    help="w0boot: with poly voices (sim/devices/poly.py); at 10.6 s recall "
                         "bank 2 entry 1 (W0:CLARA3) and hold key 45 at 16 s")
    ap.add_argument("--midi", action="store_true",
                    help="w0boot: with the MIDI card (sim/devices/midi.py; with --poly --vpk: "
                         "w0_midi_actions)")
    ap.add_argument("--poly-mb", type=int, default=32, help="w0boot --poly: poly memory in MB (per bin)")
    ap.add_argument("--poly-bins", type=int, default=1, help="w0boot --poly: poly bins (a 6400: 2)")
    ap.add_argument("--type", help="w0boot: terminal input typed at 11 s (e.g. F: SYN-5.3's "
                                   "graphic timbre display)")
    ap.add_argument("--vt640", action="store_true",
                    help="w0boot: configure a VT640 graphics terminal (MONITOR word 18)")
    ap.add_argument("--disk-us", type=int, default=0,
                    help="w0boot: SCSI disk time, microseconds per block read (0: instant)")
    ap.add_argument("--seek-us", type=int, default=0,
                    help="w0boot: with --disk-us, SCSI seek time of a READ that does not "
                         "continue the last one (us)")
    ap.add_argument("--mouse", action="store_true",
                    help="w0boot: a D44/D45/D54 mouse (sim/devices/mouse.py; MONITOR word 17)")
    ap.add_argument("--commands", help="w0boot: MONITOR commands typed at each wait for "
                                       "terminal input, separated by ';' (e.g. 'catalog w1:')")
    ap.add_argument("--fm-voices", type=int, default=8,
                    help="w0boot: FM voices installed (32: a 9600; with --vpk and no --midi: "
                         "w0_chord_actions)")
    ap.add_argument("--vpk", action="store_true",
                    help="w0boot: the velocity keyboard instead of the ORK (with --poly: "
                         "w0_vpk_actions)")
    a = ap.parse_args(argv)
    if a.mode == "check":
        ok, text = check(a.args[0], top=a.top, wav=a.wav, realtime=a.realtime, state=a.state,
                         w0=a.w0, w1=a.w1)
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
            poly = PolySynth(sectors=a.poly_mb * 2048, bins=a.poly_bins)
        midi = None
        if a.midi:
            from .devices.midi import MidiSubsystem
            midi = MidiSubsystem()
        cpu, _ = boot_from_w0(a.args[0], poly=poly, keyboard="vpk" if a.vpk else "ork", midi=midi,
                              fm_voices=a.fm_voices, w1=a.w1,
                              terminal="vt640" if a.vt640 else None, mouse=a.mouse,
                              scsi_block_ns=a.disk_us * 1000, scsi_seek_ns=a.seek_us * 1000)
        path = a.args[1]
        if a.commands:
            lines = [c.strip() + "\r" for c in a.commands.split(";")]

            def on_wait(cpu):          # type the next command at each prompt
                if lines:
                    cpu.terminal.feed(lines.pop(0))
                    return True
                return False
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
        actions = (w0_midi_actions(cpu) if a.midi and a.vpk else
                   w0_chord_actions(cpu) if a.vpk and a.fm_voices > 8 else
                   w0_vpk_actions(cpu) if a.vpk else w0_poly_actions(cpu))
        if a.vpk and a.poly_bins > 1 and not a.midi and a.fm_voices == 8:
            actions = w0_bin_actions(cpu) + actions        # CLARA3 into bin 1
    if a.mode == "w0boot" and a.type:
        text = a.type.encode("latin-1")
        actions.append((11_000_000_000, lambda c: c.terminal.feed(text)))
    n = record(cpu, path, a.instructions,
               on_wait=on_wait if a.mode == "monitor" or (a.mode == "w0boot" and a.commands) else None,
               actions=actions, audio=a.audio)
    if a.mode == "monitor" or (a.mode == "w0boot" and a.commands):
        print(cpu.terminal.text()[-600:], file=sys.stderr)
    print("recorded %d instructions in %.1f s -> %s%s" % (
        n, time.time() - t, path, " (halted: %s)" % (cpu.halted,) if cpu.halted else ""),
        file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
