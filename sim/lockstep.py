"""Lockstep traces: check the HDL against this simulator (M4.3-M4.5).

`record` runs the Python system and writes a trace; hdl/sim/lockstep.cpp
(built with Verilator by `build`) runs the HDL from the same state and
stops at the first difference. Two HDL tops:

  cpu     hdl/able_cpu.sv alone: every device read is answered with the
          value the Python devices returned, every write must match.
  system  hdl/able_system.sv: CPU plus the devices ported to HDL (D3,
          D4-D7, D50/D51, D60-D63), whose values, interrupt bits and timing
          are compared; other devices (floppy, keyboard, FM) are answered
          from the trace.

Trace format v2 (little-endian):
  b"ABLT2\\0\\0\\0"
  16 x u16 registers, u8 flags {pcs, ion, m, c, z} (bit 4 .. bit 0)
  65536 x u16 internal memory
  header sections, then 'B':
    'X' u32 sectors, sectors x 256 x u16   external memory contents
    'V' u8 device u8 index u32 value       HDL device state (system top):
          device 0 D3 (0 elapsed ns, 1 pending), 1 D4567 (0 D4, 1 D5),
          2 D60 (0 sector, 1 word), 3 D50 (0 baud index, 1 rx char,
          2 char_rdy, 3 rx_wait ns, 4 tx_busy ns, 5 xmit_irq)
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
    'H' u8        halted: 1 no SYN on read, 2 no SYN on write, 3 HALT
    'E'           end of trace

Usage:
  python3 -m sim.lockstep random OUT.trace [--instructions N] [--seed S]
  python3 -m sim.lockstep monitor IMAGE OUT.trace [--instructions N]
  python3 -m sim.lockstep ork-lm IMAGE OUT.trace [--instructions N]
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
    for dev, idx, v in ((0, 0, rtc.elapsed), (0, 1, rtc.pending),
                        (1, 0, md.d4), (1, 1, md.d5),
                        (2, 0, xm.sector), (2, 1, xm.word),
                        (3, 0, BAUDS.index(term.baud)), (3, 1, term.rx_char),
                        (3, 2, term.char_rdy), (3, 3, term.rx_wait), (3, 4, term.tx_busy),
                        (3, 5, term.xmit_irq)):
        out += struct.pack("<cBBI", b"V", dev, idx, int(v) & 0xFFFFFFFF)
    return out


def record(cpu, path, instructions, snapshot_every=256, max_steps=None, max_wait=10_000,
           on_wait=None):
    """Run `cpu` for `instructions` completed instructions, writing a trace
    to `path`. Stops early if the CPU halts, or if a read stays held for
    `max_wait` steps (a program waiting for terminal input) and
    `on_wait(cpu)` is absent or returns False (it may feed input and
    return True to go on). Returns the number recorded."""
    out = bytearray(MAGIC)
    out += struct.pack("<16HB", *cpu.r, _flags(cpu))
    out += struct.pack("<65536H", *cpu.mem)
    out += _device_header(cpu) + b"B"
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
                steps += 1
                pc = cpu.pc
                word = cpu.mem[pc]
                running = cpu.step()
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


TOPS = {
    "cpu": ("able_sim_top", ["hdl/able_cpu.sv", "hdl/sim/able_sim_top.sv"], []),
    "system": ("able_sys_top", ["hdl/able_cpu.sv", "hdl/dev/dev_rtc.sv", "hdl/dev/dev_muldiv.sv",
                                "hdl/dev/dev_extmem.sv", "hdl/dev/dev_terminal.sv",
                                "hdl/able_system.sv", "hdl/sim/able_sys_top.sv"], ["-DSYSTEM"]),
}


def build(top="cpu", force=False):
    """Build the Verilator bench for `top` ("cpu" or "system"); returns the
    executable path."""
    name, rtl, defines = TOPS[top]
    mdir = os.path.join(BUILD_DIR, top)
    exe = os.path.join(mdir, "V" + name)
    srcs = [os.path.join(ROOT, p) for p in rtl + ["hdl/sim/lockstep.cpp"]]
    if not force and os.path.exists(exe) and \
            os.path.getmtime(exe) > max(os.path.getmtime(s) for s in srcs):
        return exe
    os.makedirs(mdir, exist_ok=True)          # older Verilator does not create parents
    subprocess.run(["verilator", "--cc", "--exe", "--build", "-O3", "-Wall", "-Wno-fatal",
                    "--top-module", name, "-Mdir", mdir, "-o", "V" + name,
                    "-CFLAGS", "-O2 " + " ".join(defines)] + srcs,
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return exe


def check(path, max_instructions=None, top="cpu"):
    """Run a trace on the HDL. Returns (ok, output text)."""
    cmd = [build(top), path] + ([str(max_instructions)] if max_instructions else [])
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode == 0, p.stdout + p.stderr


def main(argv=None):
    import argparse
    import sys
    import time
    ap = argparse.ArgumentParser(description="Record / check HDL lockstep traces (M4.3)")
    ap.add_argument("mode", choices=("random", "monitor", "ork-lm", "check"))
    ap.add_argument("args", nargs="+", help="[IMAGE] TRACE")
    ap.add_argument("--instructions", type=int, default=1_000_000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--model", default="B")
    ap.add_argument("--top", choices=tuple(TOPS), default="cpu", help="HDL top for check")
    a = ap.parse_args(argv)
    if a.mode == "check":
        ok, text = check(a.args[0], top=a.top)
        print(text, end="")
        return 0 if ok else 1
    t = time.time()
    if a.mode == "random":
        cpu, path = random_cpu(a.seed, a.model), a.args[0]
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
    else:
        from .rtp import start_rtp
        cpu, _, _ = start_rtp(a.args[0], "ORK-LM")
        path = a.args[1]
    n = record(cpu, path, a.instructions, on_wait=on_wait if a.mode == "monitor" else None)
    if a.mode == "monitor":
        print(cpu.terminal.text()[-300:], file=sys.stderr)
    print("recorded %d instructions in %.1f s -> %s%s" % (
        n, time.time() - t, path, " (halted: %s)" % (cpu.halted,) if cpu.halted else ""),
        file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
