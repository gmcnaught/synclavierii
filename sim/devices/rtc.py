"""D3 real-time clock.

Evidence:
  * Synclavier Internals section 5: "D3 - Real time clock (used to generate
    5 msec interrupts)". SYSLITS: d03_speed "hardcode to 200 Hz for now".
  * PSW bit 8 (100000 >> 7 = 400 octal) is the D03 interrupt: hardware
    manual's standard assignment and NED's interpreter header (D1_D03_IRQ).
  * The Model B runtime's interrupt dispatch acknowledges it with
    IM(0) TO D3 (*RTB-7 address 705), and XPL says D03 interrupts are
    "automatically cleared by the XPL runtime system".
  * Reading D3 tests for a pending tick: DEVUTIL d100_disk_check polls
    with interrupts off: "if read(d03) then do; i = i + 1; write(d03) = 0;
    end" and "while (read(d03)) write(d03) = 0". The same code tests the
    D100 busy bit (bit 0) with "read(d100)" as a condition, so XPL
    conditions test bit 0: a read returns 1 while a tick is pending, else
    0. [HYP: the other bits.]
"""
from ..bus import Device

IRQ_BIT = 0o400  # PSW bit 8


class RealTimeClock(Device):
    numbers = (0o3,)

    def __init__(self, hz=200):
        self.period_ns = round(1e9 / hz)
        self.elapsed = 0
        self.pending = False
        self.ticks = 0

    def read(self, dev):
        return 1 if self.pending else 0

    def write(self, dev, value):
        self.pending = False
        return True

    def tick(self, ns):
        self.elapsed += ns
        if self.elapsed >= self.period_ns:
            n, self.elapsed = divmod(self.elapsed, self.period_ns)
            self.ticks += n
            self.pending = True  # missed ticks coalesce into one request

    def irq_bits(self):
        return IRQ_BIT if self.pending else 0
