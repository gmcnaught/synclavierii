"""I/O device models for the simulator (milestones M1.3-M1.5).

Each model documents its evidence and marks open choices with CHOICE.
Reads or writes of registers whose behaviour is unknown return NO_SYN on
purpose, so the CPU halts and reports the device instead of guessing.
"""
from .extmem import ExternalMemory
from .floppy import FloppyController, Media
from .muldiv import MulDiv
from .rtc import RealTimeClock
from .stubs import ProbeDevice
from .synth import ControlVoltages, FMInterface, OriginalKeyboard
from .terminal import Terminal

__all__ = ["ExternalMemory", "FloppyController", "Media", "MulDiv", "ControlVoltages", "OriginalKeyboard", "FMInterface", "ProbeDevice", "RealTimeClock", "Terminal"]
