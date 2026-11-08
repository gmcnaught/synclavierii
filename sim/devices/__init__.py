"""I/O device models for the simulator (milestones M1.3-M1.5).

Each model documents its evidence and marks open choices with CHOICE.
Reads or writes of registers whose behaviour is unknown return NO_SYN on
purpose, so the CPU halts and reports the device instead of guessing.
"""
from .extmem import ExternalMemory
from .muldiv import MulDiv
from .rtc import RealTimeClock
from .terminal import Terminal

__all__ = ["ExternalMemory", "MulDiv", "RealTimeClock", "Terminal"]
