"""Assemble a Model B system with the M1 devices attached."""
from .bus import Bus
from .cpu import CPU
from .devices import (ControlVoltages, ExternalMemory, FloppyController, FMInterface,
                      MulDiv, OriginalKeyboard, RealTimeClock, Terminal)
from .devices.terminal import D60_EXISTS


def make_system(ext_sectors=1024, baud=9600, rtc_hz=200, output=None, floppy=False,
                synth=False, strict=True):
    """Return a CPU with D3, D4567, D50/D51 and (if ext_sectors) D60-D63.

    The devices are reachable as cpu.rtc, cpu.muldiv, cpu.terminal and
    cpu.extmem (None without external memory). floppy=True adds the D100
    controller (D100-D104) as cpu.floppy (None otherwise). synth=True adds
    the FM interface with the old panel's switches/A-D (cpu.fm, D160-D163),
    the original keyboard and panel (cpu.keyboard, D130/D131) and the CV
    board (cpu.cv, D164/D165); strict=False makes their unknown
    reads return 0 instead of halting (M2 probing).
    """
    bus = Bus()
    cpu = CPU(bus)
    cpu.rtc = bus.attach(RealTimeClock(rtc_hz))
    cpu.muldiv = bus.attach(MulDiv())
    cpu.extmem = bus.attach(ExternalMemory(ext_sectors)) if ext_sectors else None
    bits = D60_EXISTS if ext_sectors else 0
    cpu.terminal = bus.attach(Terminal(baud, device_bits=bits, output=output))
    cpu.floppy = bus.attach(FloppyController()) if floppy else None
    cpu.fm = bus.attach(FMInterface(strict=strict)) if synth else None
    cpu.keyboard = bus.attach(OriginalKeyboard(strict=strict)) if synth else None
    cpu.cv = bus.attach(ControlVoltages()) if synth else None
    return cpu
