"""Debug tooling (milestone M1.7): instruction history, device-access log,
breakpoints and a HOP-like inspect/halt report.

The real machine is inspected through the HOP (front panel) while halted;
Debugger offers the same view on a simulated CPU: registers, flags, memory,
the last instructions executed and the last device transfers.

    dbg = Debugger(cpu)
    dbg.breakpoints.add(0o1234)
    stop = dbg.run(1_000_000)   # None, "breakpoint" or "halted"
    print(dbg.report())

Attaching a Debugger costs about 15% speed (one Python call per instruction); detach()
restores the CPU's original hooks.
"""
from collections import Counter, deque

from .bus import NO_SYN

try:  # shared decode tables / mnemonics (tools/ is a sibling package)
    from tools.able_disasm import disassemble as _disassemble
except ImportError:  # pragma: no cover - tools/ not on the path
    _disassemble = None

STOP_BREAKPOINT = "breakpoint"
STOP_HALTED = "halted"


def disassemble(words, base=0, model="B"):
    """Disassemble words at base (NED syntax, octal). Falls back to octal."""
    if _disassemble is None:
        return ["%06o  %06o" % ((base + i) & 0xFFFF, w) for i, w in enumerate(words)]
    return _disassemble(list(words), base, model)


class Debugger:
    """Records history and device accesses for one CPU.

    history_len: instructions kept (pc, word).
    io_len:      device transfers kept (pc, "R"/"W", device, value).
    """

    def __init__(self, cpu, history_len=64, io_len=64):
        self.cpu = cpu
        self.history = deque(maxlen=history_len)
        self.io = deque(maxlen=io_len)
        self.io_counts = Counter()   # (device, "R"/"W") -> transfers
        self.breakpoints = set()
        self.last_pc = None
        self._prev_trace = cpu.trace
        self._bus = cpu.bus
        self._bus_read = cpu.bus.read
        self._bus_write = cpu.bus.write
        cpu.trace = self._on_fetch
        cpu.bus.read = self._read
        cpu.bus.write = self._write

    def detach(self):
        self.cpu.trace = self._prev_trace
        # remove the instance attributes so the class methods show through
        del self._bus.read
        del self._bus.write

    # ------------------------------------------------------------- hooks

    def _on_fetch(self, cpu, pc, word):
        self.last_pc = pc
        self.history.append((pc, word))
        if self._prev_trace:
            self._prev_trace(cpu, pc, word)

    def _read(self, dev):
        v = self._bus_read(dev)
        self.io.append((self.last_pc, "R", dev, v))
        self.io_counts[(dev, "R")] += 1
        return v

    def _write(self, dev, value):
        ok = self._bus_write(dev, value)
        self.io.append((self.last_pc, "W", dev, value if ok else NO_SYN))
        self.io_counts[(dev, "W")] += 1
        return ok

    # ----------------------------------------------------------- running

    def run(self, max_instructions=None):
        """Run until a breakpoint (checked before fetch), a halt, or the
        instruction budget runs out. A breakpoint at the starting PC is
        stepped over, so run() can resume from one.

        Returns STOP_BREAKPOINT, STOP_HALTED or None (budget used up).
        """
        cpu = self.cpu
        bps = self.breakpoints
        n = 0
        first = True
        while max_instructions is None or n < max_instructions:
            if bps and not first and cpu.pc in bps:
                return STOP_BREAKPOINT
            first = False
            if not cpu.step():
                return STOP_HALTED
            n += 1
        return None

    # ----------------------------------------------------------- inspect

    def registers(self):
        cpu = self.cpu
        regs = " ".join("R%o=%06o" % (i, v) for i, v in enumerate(cpu.r))
        flags = "Z=%d C=%d M=%d ION=%d PC=R%o" % (
            cpu.z, cpu.c, cpu.m, cpu.ion, cpu.pc_reg)
        return regs + "\n" + flags

    def memory(self, addr, count=8, disasm=False):
        """Octal dump (8 words per line) or disassembly of internal memory."""
        mem = self.cpu.mem
        words = [mem[(addr + i) & 0xFFFF] for i in range(count)]
        if disasm:
            return "\n".join(disassemble(words, addr))
        lines = []
        for i in range(0, count, 8):
            row = " ".join("%06o" % w for w in words[i:i + 8])
            lines.append("%06o: %s" % ((addr + i) & 0xFFFF, row))
        return "\n".join(lines)

    def history_lines(self, n=None):
        items = list(self.history)[-n:] if n else list(self.history)
        out = []
        for pc, w in items:
            # disassemble the word with its following literal for PCI sources
            nxt = self.cpu.mem[(pc + 1) & 0xFFFF]
            out.append(disassemble([w, nxt], pc)[0]
                       + ("  [%06o]" % nxt if (w & 0o377) == 0o377 else ""))
        return out

    def io_lines(self, n=None):
        items = list(self.io)[-n:] if n else list(self.io)
        out = []
        for pc, kind, dev, v in items:
            val = "NO SYN" if v is NO_SYN else "%06o" % v
            pcs = "------" if pc is None else "%06o" % pc
            out.append("%s  %s D%-3o %s" % (pcs, kind, dev, val))
        return out

    def report(self, history=32, io=16):
        """Halt/inspect report: why stopped, registers, recent history."""
        cpu = self.cpu
        lines = []
        h = cpu.halted
        if h:
            dev = "" if h.device is None else " device D%o" % h.device
            lines.append("HALT: %s at %06o (word %06o)%s"
                         % (h.reason, h.pc, h.word, dev))
        else:
            lines.append("stopped at %06o" % cpu.pc)
        lines.append("instructions=%d  time=%.3f ms" % (cpu.instructions, cpu.time_ns / 1e6))
        lines.append(self.registers())
        lines.append("-- last %d instructions" % min(history, len(self.history)))
        lines.extend(self.history_lines(history))
        lines.append("-- last %d device transfers" % min(io, len(self.io)))
        lines.extend(self.io_lines(io))
        lines.append("-- device transfer counts")
        for (dev, kind), n in sorted(self.io_counts.items()):
            lines.append("D%-3o %s %d" % (dev, kind, n))
        return "\n".join(lines)
