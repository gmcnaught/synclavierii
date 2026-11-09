"""ProbeDevice for M2 exploration (sim.rtp): answers any device number
nothing else claims, so a program's unknown accesses are counted instead of
halting the CPU. The synthesizer devices are modelled in synth.py.
"""
from ..bus import Device


class ProbeDevice(Device):
    """Answers any device number: reads return `value` (0), writes are
    accepted. Every access is counted per (device, "R"/"W"). Used as the
    bus fallback when probing what a program touches (M2.1)."""

    def __init__(self, value=0):
        self.value = value
        self.counts = {}

    def read(self, dev):
        self.counts[(dev, "R")] = self.counts.get((dev, "R"), 0) + 1
        return self.value

    def write(self, dev, value):
        self.counts[(dev, "W")] = self.counts.get((dev, "W"), 0) + 1
        return True


class PolyNoVoices(Device):
    """D154-D157 poly synthesizer interface with no voice hardware behind it
    (M7.5 placeholder). SYN-5.3 (a 9600 build: inc.poly = 1) writes the
    channel register D155 in routines that do not check D51's poly-present
    bit; POLY.CHECK (SYNSOU:POLYMOD:POLYSOU) counts bins only when that bit
    is set and a written channel number reads back from D155.
    [HYP] Writes are accepted and reads return 0, so no bin answers. Every
    access is counted per (device, "R"/"W")."""

    numbers = (0o154, 0o155, 0o156, 0o157)

    def __init__(self):
        self.counts = {}

    def read(self, dev):
        self.counts[(dev, "R")] = self.counts.get((dev, "R"), 0) + 1
        return 0

    def write(self, dev, value):
        self.counts[(dev, "W")] = self.counts.get((dev, "W"), 0) + 1
        return True
