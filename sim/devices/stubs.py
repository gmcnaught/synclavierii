"""Minimal stand-ins for the synthesizer devices, enough for MONITOR (M1).

The register maps are milestone M2's job (docs/plan.md). These stubs model
only what MONITOR's start-up is seen to need, record every access for M2,
and halt (no SYN) on anything else so new uses are noticed. With
strict=False (M2 probing) unknown reads return 0 instead and are counted
in `unknown_reads`; ProbeDevice does the same for any other device.

Evidence: NED MONCAT:MON (MIT) and the Release L MONITOR binary.
  * SILENCE.VOICES (if the options word has o#d160, 100000): for each
    channel I = 0..255 and function J = 0..11: WRITE("160") = I;
    WRITE("161") = J; WRITE("162") = INIT.DATA(J). No reads.
  * CLEAR.KEYBOARD (if o#d130, 40000): WRITE("131") = "105" /* CHECK
    KEYBOARD TYPE */; IF READ("130") = 1 THEN /* OLD KEYBOARD */ clears the
    light panel with D131/D130 writes; otherwise the velocity/pressure
    keyboard path.
"""
from ..bus import NO_SYN, Device

KEYBOARD_TYPE_QUERY = 0o105
OLD_KEYBOARD = 1   # original keyboard (ORK), as Release L for ORK expects


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


class FMInterface(Device):
    """D160-D162 FM voice interface: write recorder (M2 decodes it)."""
    numbers = (0o160, 0o161, 0o162)

    def __init__(self, log_len=4096, strict=True):
        self.strict = strict
        self.unknown_reads = 0
        self.regs = {0o160: 0, 0o161: 0}
        self.writes = 0
        self.log = []
        self.log_len = log_len
        self.channels = {}   # (channel, function) -> last value

    def read(self, dev):
        if self.strict:
            return NO_SYN    # no MONITOR read seen
        self.unknown_reads += 1
        return 0

    def write(self, dev, value):
        self.writes += 1
        if len(self.log) < self.log_len:
            self.log.append((dev, value))
        if dev == 0o162:
            self.channels[(self.regs[0o160], self.regs[0o161])] = value
        else:
            self.regs[dev] = value
        return True


class OriginalKeyboard(Device):
    """D130/D131 keyboard and button panel: answers the type query only."""
    numbers = (0o130, 0o131)

    def __init__(self, strict=True):
        self.strict = strict
        self.unknown_reads = 0
        self.d131 = 0
        self.d130_writes = []

    def read(self, dev):
        if dev == 0o130 and self.d131 == KEYBOARD_TYPE_QUERY:
            return OLD_KEYBOARD
        if self.strict:
            return NO_SYN    # key/panel reads: M2
        self.unknown_reads += 1
        return 0

    def write(self, dev, value):
        if dev == 0o131:
            self.d131 = value
        else:
            self.d130_writes.append((self.d131, value))
        return True
