"""Assemble a Model B system with the M1 devices attached."""
from .bus import Bus
from .cpu import CPU
from .devices import ExternalMemory, MulDiv, RealTimeClock, Terminal
from .devices.terminal import D60_EXISTS


def make_system(ext_sectors=1024, baud=9600, rtc_hz=200, output=None):
    """Return a CPU with D3, D4567, D50/D51 and (if ext_sectors) D60-D63.

    The devices are reachable as cpu.rtc, cpu.muldiv, cpu.terminal and
    cpu.extmem (None without external memory).
    """
    bus = Bus()
    cpu = CPU(bus)
    cpu.rtc = bus.attach(RealTimeClock(rtc_hz))
    cpu.muldiv = bus.attach(MulDiv())
    cpu.extmem = bus.attach(ExternalMemory(ext_sectors)) if ext_sectors else None
    bits = D60_EXISTS if ext_sectors else 0
    cpu.terminal = bus.attach(Terminal(baud, device_bits=bits, output=output))
    return cpu
