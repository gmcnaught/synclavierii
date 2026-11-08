"""Software simulator for the NED ABLE / Synclavier II (milestone M1).

See docs/simulator.md.
"""
from .bus import NO_SYN, Bus, Device
from .cpu import CPU, Halt
from .system import make_system

__all__ = ["CPU", "Halt", "Bus", "Device", "NO_SYN", "make_system"]
