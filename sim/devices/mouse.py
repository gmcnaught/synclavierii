"""D44/D45 mouse port of the D40Q card and D54, its interrupt bits: the
model of docs/devices/vt640-graphics-terminal.md section 6.5.

  D44 write   a byte to the mouse: P (0120) -> a 3-byte position report,
              s (0163) -> the status byte O (0117); 0 and D (0104) -> none.
  D44 read    the received byte; clears receive-ready.
  D45 read    bit 1 = receive-ready; other bits 0.
  D45 write   accepted (0 "clears status": the transmit interrupt, which
              this model never raises; receive-ready is kept [CHOICE: SYN-5.3's
              MOUSE.INIT writes 0 just before testing bit 1]).
  D54 write   interrupt enables: bit 0 D40, bit 1 D42, bit 2 D44.
  D54 read    pending bits = enables & (bit 2: receive-ready).
  PSW bit 10  while D54 has a pending bit.

Report (MOUSRSOU:104-126): byte 0 = 0200 | X sign (020, 1 = right) |
Y sign (010, 1 = up) | left 4 | middle 2 | right 1; bytes 1, 2 = |dX|, |dY|
(0-127) of the motion since the last report (larger motion is kept for the
next). Reply bytes arrive one per BYTE_NS of simulated time, the first
BYTE_NS after the command [CHOICE: 1 ms, about 9600 baud].

Host side: host(dx, dy, buttons) - one PS/2 packet: motion (dy up = +,
each -127..127) and the buttons (left 4, middle 2, right 1); move() and
set_buttons() call it.
"""
from collections import deque

from ..bus import Device

IRQ_BIT = 0o2000            # PSW bit 10: D54 (AbleInterpreter.h D1_D54_IRQ)
BYTE_NS = 1_000_000
RX_READY = 0o2
D44_ENABLE = 0o4


class Mouse(Device):
    numbers = (0o44, 0o45, 0o54)

    def __init__(self):
        self.dx = self.dy = 0
        self.buttons = 0            # left 4, middle 2, right 1
        self.out = deque()          # reply bytes still to arrive
        self.next_ns = 0            # time the next one arrives
        self.time_ns = 0
        self.rx = 0
        self.ready = False
        self.enables = 0
        self.commands = []          # bytes written to D44, for tests

    # ------------------------------------------------------------- host
    def host(self, dx, dy, buttons):
        self.dx += max(-127, min(127, dx))
        self.dy += max(-127, min(127, dy))
        self.buttons = buttons & 7

    def move(self, dx, dy):
        self.host(dx, dy, self.buttons)

    def set_buttons(self, left=False, middle=False, right=False):
        self.host(0, 0, (4 if left else 0) | (2 if middle else 0) | (1 if right else 0))

    # -------------------------------------------------------- registers
    def read(self, dev):
        if dev == 0o44:
            self.ready = False
            return self.rx
        if dev == 0o45:
            return RX_READY if self.ready else 0
        return self.enables & (D44_ENABLE if self.ready else 0)

    def write(self, dev, value):
        value &= 0xFFFF
        if dev == 0o44:
            b = value & 0xFF
            self.commands.append(b)
            if b == 0o120:
                self._queue(self._report())
            elif b == 0o163:
                self._queue([0o117])
        elif dev == 0o54:
            self.enables = value & 7
        return True

    def _report(self):
        dx = max(-127, min(127, self.dx))
        dy = max(-127, min(127, self.dy))
        self.dx -= dx
        self.dy -= dy
        b0 = 0o200 | (0o20 if dx >= 0 else 0) | (0o10 if dy >= 0 else 0) | self.buttons
        return [b0, abs(dx), abs(dy)]

    def _queue(self, data):
        if not self.out:
            self.next_ns = self.time_ns + BYTE_NS
        self.out.extend(data)

    def tick(self, ns):
        self.time_ns += ns
        while self.out and self.time_ns >= self.next_ns:
            self.rx = self.out.popleft()
            self.ready = True
            self.next_ns += BYTE_NS

    def irq_bits(self):
        return IRQ_BIT if self.enables & D44_ENABLE and self.ready else 0
