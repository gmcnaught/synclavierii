"""D40/D41 printer port of the D40Q card and bit 0 of D54, its interrupt:
the model of docs/devices/d40-printer.md.

  D40 write   a byte to the printer (bits 0-7): appended to `out`; the
              transmitter is busy for one character time, then raises its
              transmit interrupt.
  D40 read    the received byte (a printer's XON/XOFF; none arrives: 0).
  D41 read    status as D51: 4 transmitter empty, 2 receive-ready (never),
              1 transmit interrupt.
  D41 write   clears the transmit interrupt ("acknowledge interrupt(s)",
              D40SOU boot_d40); bit 15 sets the baud rate from bits 10-8
              (SYSLITS b#300 ... b#76800), as D51.
  D54 write   interrupt enables: bit 0 D40 (shared with the mouse, bit 2).
  D54 read    pending bits = enables & (bit 0: transmit interrupt).
  PSW bit 10  while D54 bit 0 is pending.

[OBS] SYN-5.3's driver (SYNSOU/D40MOD/D40SOU) writes a byte to D40 when the
port is idle and sends the next one from WHEN D40INT (D54 bit 0, RTP
B10INT: WHEN 16 + bit); with nothing left it writes D41 = 0 and goes idle.
In the handler it tests D41 bit 1 for an XON/XOFF byte first.
[CHOICE] Until a D41 baud write (SYN-5.3 never writes one; the D40Q's
power-on rate is [UNK]) a byte takes FAST_NS, faster than any D40Q rate:
SYN-5.3's screen hardcopy (D40SOU hardcopy) reads the dot rows it sends
through MAM/MAL, and its sendc, when the 8-byte queue is full, calls
CHILL.OUT.AND.RUN.SYN (SYNRSOU/03-PRIM/410-TTY), which runs MAIN.LOOP and
PERFORM without keeping MAM/MAL: the rest of the row then comes from the
wrong memory. At 76800 baud the queue fills and the page is garbage (seen
in the simulator); at FAST_NS it never does.
"""
from ..bus import Device

IRQ_BIT = 0o2000            # PSW bit 10: D54
D40_ENABLE = 0o1
XMIT_IRQ, CHAR_RDY, XMIT_MT = 0o1, 0o2, 0o4
BAUD = (300, 1200, 2400, 4800, 9600, 19200, 38400, 76800)
FAST_NS = 10_000            # ns per byte until a baud rate is set


class Printer(Device):
    numbers = (0o40, 0o41, 0o54)

    def __init__(self, baud=None, output=None):
        """baud: a D40Q rate (BAUD), or None for FAST_NS a byte. output:
        callable(byte) for each byte printed; default collects them in
        self.out."""
        self.out = bytearray()
        self.output = output if output is not None else self.out.append
        self.baud, self.char_ns = None, FAST_NS
        if baud:
            self.set_baud(baud)
        self.tx_busy = 0            # ns until the transmitter is empty
        self.xmit_irq = False
        self.enables = 0

    def set_baud(self, baud):
        self.baud = baud
        self.char_ns = round(10 * 1e9 / baud)       # start + 8 data + stop

    def pending(self):
        return self.enables & (D40_ENABLE if self.xmit_irq else 0)

    def read(self, dev):
        if dev == 0o41:
            return (XMIT_MT if self.tx_busy <= 0 else 0) | (XMIT_IRQ if self.xmit_irq else 0)
        if dev == 0o40:
            return 0
        return self.pending()

    def write(self, dev, value):
        value &= 0xFFFF
        if dev == 0o40:
            self.output(value & 0o377)
            self.tx_busy = self.char_ns
            self.xmit_irq = False
        elif dev == 0o41:
            self.xmit_irq = False
            if value & 0o100000:
                self.set_baud(BAUD[(value >> 8) & 7])
        else:
            self.enables = value & 7
        return True

    def tick(self, ns):
        if self.tx_busy > 0:
            self.tx_busy -= ns
            if self.tx_busy <= 0:
                self.xmit_irq = True

    def irq_bits(self):
        return IRQ_BIT if self.pending() else 0


class D54(Device):
    """D54 when the printer and the mouse are both on the D40Q: writes go
    to both (each keeps its own enable bits), reads OR their pending bits."""
    numbers = (0o54,)

    def __init__(self, *ports):
        self.ports = ports

    def read(self, dev):
        v = 0
        for p in self.ports:
            v |= p.read(dev)
        return v

    def write(self, dev, value):
        for p in self.ports:
            p.write(dev, value)
        return True
