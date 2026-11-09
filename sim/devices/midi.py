"""D70-D72 MIDI subsystem card (one card, subsystem 16): the model of
docs/devices/d70-midi-subsystem.md section 9.

  D70 SYSSEL  write: subsystem select; read: the select if it is 16, else 0
              (no second card, no SMPTE reader (8), no DSP70 (32)).
  D71 MCHA    write: port (bits 0-2: 0-3 output jacks, 4 the input jack) and
              reset (bit 3).
      MSTA    read: bit 0 = input FIFO not empty (any port selected); bit 1
              = 0 (cables OK); other bits 0. 0 when another subsystem is
              selected.
  D72 MDAT    read (port 4): the next input byte (0 if empty); write (ports
              0-3): one output byte. With the reset bit set, any MDAT access
              empties that port's FIFO (the read returns 0, the write is
              dropped).
  D73         reads 0, writes ignored.

The input FIFO holds 64 bytes (SYN-5.3 treats 64 bytes in one scan as an
overrun); a byte that arrives with it full is dropped. Bytes arrive through
receive() at whatever pace the caller keeps (the UART's, on the board).
Output bytes from all four ports go to one MIDI out: self.out is a list of
(port, byte), and `output(byte)` is called for each if given. No interrupts.
D51 bit 8 (D70_EXISTS) tells SYN-5.3 the card may be there (sim/system.py).
"""
from collections import deque

from ..bus import Device

SUBSYS = 16          # MIDI.SUBSYS: the first (only) card
IN_PORT = 4          # MCHA port of the input jack
RESET = 0o10         # MCHA bit 3: "select UART and assert reset line"
FIFO = 64


class MidiSubsystem(Device):
    numbers = (0o70, 0o71, 0o72, 0o73)

    def __init__(self, output=None):
        self.sel = 0
        self.mcha = 0
        self.fifo = deque()
        self.out = []
        self.output = output
        self.dropped = 0

    def receive(self, byte):
        """A byte from the MIDI in jack into the input FIFO."""
        if len(self.fifo) >= FIFO:
            self.dropped += 1
        else:
            self.fifo.append(byte & 0xFF)

    def read(self, dev):
        here = self.sel == SUBSYS
        if dev == 0o70:
            return self.sel if here else 0
        if dev == 0o71:
            return int(bool(self.fifo)) if here else 0
        if dev == 0o72 and here:
            port = self.mcha & 7
            if self.mcha & RESET:
                if port == IN_PORT:
                    self.fifo.clear()
                return 0
            if port == IN_PORT and self.fifo:
                return self.fifo.popleft()
        return 0

    def write(self, dev, value):
        value &= 0xFFFF
        if dev == 0o70:
            self.sel = value
        elif dev == 0o71:
            self.mcha = value & 0xF
        elif dev == 0o72 and self.sel == SUBSYS:
            port = self.mcha & 7
            if self.mcha & RESET:
                if port == IN_PORT:
                    self.fifo.clear()
            elif port < 4:
                self.out.append((port, value & 0xFF))
                if self.output:
                    self.output(value & 0xFF)
        return True
