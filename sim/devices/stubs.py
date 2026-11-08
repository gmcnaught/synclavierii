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
