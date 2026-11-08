"""Lockstep traces: check the HDL CPU against this simulator (M4.3).

`record` runs the Python CPU and writes a trace; hdl/sim/lockstep.cpp
(built with Verilator by `build`) replays it on hdl/able_cpu.sv and stops
at the first difference. Devices are not simulated on the HDL side: every
device read is answered with the value the Python devices returned, and
every device write must match. So the HDL CPU runs real code (MONITOR,
ORK-LM) without HDL devices.

Trace format (little-endian):
  b"ABLT1\\0\\0\\0"
  16 x u16 registers, u8 flags {pcs, ion, m, c, z} (bit 4 .. bit 0)
  65536 x u16 internal memory
  events, in the order the instruction performs them:
    'P' u16       interrupt bits returned by a PSW read (device 001)
    'R' u8 u16    device read: device, value
    'W' u8 u16    device write: device, value
    'Q' u16       interrupt bits at the end of an instruction with ION and
                  PCS set (the interrupt is taken if nonzero)
    'I' u16 u16   instruction completed: pc, word
    'S' 16 x u16 u8   registers and flags after the preceding instruction
    'H' u8        halted: 1 no SYN on read, 2 no SYN on write, 3 HALT
    'E'           end of trace

Usage:
  python3 -m sim.lockstep random OUT.trace [--instructions N] [--seed S]
  python3 -m sim.lockstep monitor IMAGE OUT.trace [--instructions N]
  python3 -m sim.lockstep ork-lm IMAGE OUT.trace [--instructions N]
  python3 -m sim.lockstep check OUT.trace     (builds the Verilator model if needed)
"""
import os
import random
import struct
import subprocess

from .bus import BUS_WAIT, NO_SYN, Device

M16 = 0xFFFF
MAGIC = b"ABLT1\0\0\0"
HALT_CODES = {"no SYN on read": 1, "no SYN on write": 2, "HALT": 3}
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD_DIR = os.path.join(ROOT, "out", "hdl-lockstep")


class _RecordingBus:
    """Wraps the CPU's bus and records what the CPU sees."""

    def __init__(self, inner, out):
        self.inner = inner
        self.out = out
        self.in_psw = False

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def read(self, dev):
        v = self.inner.read(dev)
        if v is not NO_SYN and v is not BUS_WAIT:
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
    ev = bytearray()
    rbus = _RecordingBus(cpu.bus, ev)
    cpu.bus = rbus
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
                    break
                if cpu.waiting is not None:
                    waits += 1               # held read: the instruction did not complete
                    if waits >= max_wait:
                        if not (on_wait and on_wait(cpu)):
                            break
                        waits = 0
                    continue
                waits = 0
                ev += struct.pack("<cHH", b"I", pc, word)
                n += 1
                if n % snapshot_every == 0:
                    ev += b"S" + struct.pack("<16HB", *cpu.r, _flags(cpu))
                if len(ev) > 1 << 20:
                    f.write(ev)
                    del ev[:]
                if not running:
                    break
            ev += b"S" + struct.pack("<16HB", *cpu.r, _flags(cpu)) + b"E"
            f.write(ev)
    finally:
        cpu.bus = rbus.inner
        del cpu.read_psw
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


def build(force=False):
    """Build the Verilator model; returns the executable path."""
    exe = os.path.join(BUILD_DIR, "Vable_sim_top")
    srcs = [os.path.join(ROOT, p) for p in
            ("hdl/able_cpu.sv", "hdl/sim/able_sim_top.sv", "hdl/sim/lockstep.cpp")]
    if not force and os.path.exists(exe) and \
            os.path.getmtime(exe) > max(os.path.getmtime(s) for s in srcs):
        return exe
    os.makedirs(BUILD_DIR, exist_ok=True)     # older Verilator does not create parents
    subprocess.run(["verilator", "--cc", "--exe", "--build", "-O3", "-Wall", "-Wno-fatal",
                    "--top-module", "able_sim_top", "-Mdir", BUILD_DIR,
                    "-o", "Vable_sim_top", "-CFLAGS", "-O2"] + srcs,
                   check=True, stdout=subprocess.DEVNULL)
    return exe


def check(path, max_instructions=None):
    """Replay a trace on the HDL CPU. Returns (ok, output text)."""
    cmd = [build(), path] + ([str(max_instructions)] if max_instructions else [])
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
    a = ap.parse_args(argv)
    if a.mode == "check":
        ok, text = check(a.args[0])
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
