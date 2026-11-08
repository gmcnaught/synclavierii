"""D50/D51 system control terminal (serial port on the D40Q card).

Evidence:
  * NED interpreter header (AbleInterpreter.h, MIT): D51 status bits
    1 = XMIT_IRQ ("XMIT MT caused interrupt"), 2 = CHAR_RDY ("character is
    present in D50"), 4 = XMIT_MT ("room in xmit output buffer"); bits 8-15
    report which other cards are installed (D60 = 1000, D100A = 10000,
    D24 SCSI = 40000, ...). D1_D50_IRQ = 100: PSW bit 6.
  * Loaders read D51 for the device bits (FLPLOAD tests 10000 for D100A,
    SCSILOAD tests 40000 for SCSI) and write D50 to ring the bell.
  * Model B runtime (*RTB-7): polled input tests D51 bit 2 then reads D50
    (address 4373); polled output waits for XMIT_MT (bit 4) before writing;
    the interrupt dispatch reads D51 and, if CHAR_RDY, reads D50 (TTIINT),
    otherwise writes 0 to D51 to clear the transmit interrupt (TTOINT).
  * SYSLITS: baud rate codes 0-7 (300 ... 76800) shifted left 8 and ORed
    with 100000 before writing D51.
"""
from collections import deque

from ..bus import Device

XMIT_IRQ = 0o1
CHAR_RDY = 0o2
XMIT_MT = 0o4
IRQ_BIT = 0o100  # PSW bit 6

# device-present bits in D51 (AbleInterpreter.h)
D70_EXISTS = 0o400
D60_EXISTS = 0o1000
POLY_EXISTS = 0o2000
D32_EXISTS = 0o4000
D100A_EXISTS = 0o10000
D110A_EXISTS = 0o20000
D24_EXISTS = 0o40000
D57_EXISTS = 0o100000

BAUD = (300, 1200, 2400, 4800, 9600, 19200, 38400, 76800)


class Terminal(Device):
    numbers = (0o50, 0o51)

    def __init__(self, baud=9600, device_bits=0, output=None):
        """output: callable(byte) for each character sent; default collects
        them in self.out."""
        self.device_bits = device_bits & 0xFF00
        self.out = bytearray()
        self.output = output if output is not None else self.out.append
        self.input = deque()
        self.set_baud(baud)
        self.rx_char = 0
        self.char_rdy = False
        self.rx_wait = 0     # ns until the next input character can arrive
        self.tx_busy = 0     # ns until the transmitter is empty again
        self.xmit_irq = False

    def set_baud(self, baud):
        self.baud = baud
        self.char_ns = round(10 * 1e9 / baud)  # start + 8 data + stop

    def feed(self, data):
        """Queue host keyboard input (bytes or str)."""
        if isinstance(data, str):
            data = data.encode("latin-1")
        self.input.extend(data)
        self._receive()

    def _receive(self):
        if not self.char_rdy and self.input and self.rx_wait <= 0:
            self.rx_char = self.input.popleft()
            self.char_rdy = True
            self.rx_wait = self.char_ns

    def status(self):
        return (self.device_bits
                | (XMIT_MT if self.tx_busy <= 0 else 0)
                | (CHAR_RDY if self.char_rdy else 0)
                | (XMIT_IRQ if self.xmit_irq else 0))

    def read(self, dev):
        if dev == 0o51:
            return self.status()
        # CHOICE: reading D50 with no character waiting returns the last one.
        self.char_rdy = False
        self._receive()
        return self.rx_char

    def write(self, dev, value):
        if dev == 0o51:
            self.xmit_irq = False
            if value & 0o100000:
                self.set_baud(BAUD[(value >> 8) & 7])
            return True
        # CHOICE: a write while the transmitter is busy is still sent
        # (a real UART might drop or overwrite it).
        self.output(value & 0o377)
        self.tx_busy = self.char_ns
        self.xmit_irq = False
        return True

    def tick(self, ns):
        if self.tx_busy > 0:
            self.tx_busy -= ns
            if self.tx_busy <= 0:
                self.xmit_irq = True  # transmitter went empty
        if self.rx_wait > 0:
            self.rx_wait -= ns
        if not self.char_rdy and self.input:
            self._receive()

    def irq_bits(self):
        # CHOICE: interrupt requests are always enabled at the card; software
        # masks them with ION. NED code shows no separate enable bits.
        return IRQ_BIT if (self.char_rdy or self.xmit_irq) else 0

    def text(self):
        """Output so far as text, parity bit stripped."""
        return bytes(b & 0o177 for b in self.out).decode("latin-1")
