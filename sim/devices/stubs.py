"""Minimal stand-ins for the synthesizer devices, enough for MONITOR (M1).

The register maps are milestone M2's job (docs/plan.md). These stubs model
only what MONITOR's start-up is seen to need, record every access for M2,
and halt (no SYN) on anything else so new uses are noticed.

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


class FMInterface(Device):
    """D160-D162 FM voice interface: write-only recorder (M2 decodes it)."""
    numbers = (0o160, 0o161, 0o162)

    def __init__(self, log_len=4096):
        self.regs = {0o160: 0, 0o161: 0}
        self.writes = 0
        self.log = []
        self.log_len = log_len
        self.channels = {}   # (channel, function) -> last value

    def read(self, dev):
        return NO_SYN        # no NED read seen yet

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

    def __init__(self):
        self.d131 = 0
        self.d130_writes = []

    def read(self, dev):
        if dev == 0o130 and self.d131 == KEYBOARD_TYPE_QUERY:
            return OLD_KEYBOARD
        return NO_SYN        # key/panel reads: M2

    def write(self, dev, value):
        if dev == 0o131:
            self.d131 = value
        else:
            self.d130_writes.append((self.d131, value))
        return True
