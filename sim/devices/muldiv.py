"""D4567 hardware multiply/divide (devices 004-007).

Evidence: SCSILOAD (MIT) register protocol, and NED's C runtime
(AbleCatRtns.cpp: _write_5(a); _write_6(b); ms = _read_4; ls = _read_5).
  * Multiply-add: a -> D5, addend -> D4, b -> D6 starts it;
    then D5 = low 16 bits and D4 = high 16 bits of a * b + addend.
  * Divide: lo -> D5, hi -> D4, divisor -> D7 starts it;
    then D5 = quotient and D4 = remainder of (hi:lo) / divisor.
  * Only D4 and D5 are readable (the XPL-to-C translator has _read_4 and
    _read_5 but no _read_6/_read_7); reading D6/D7 halts the CPU.
  * Unsigned: the operands are sector numbers and counts. XPL's signed
    multiply and divide do their own sign correction (Scientific XPL manual).
  * NED's C emulation (Code/Includes/XPL.h, MIT): "d4567 itself operated
    unsigned: write to d5 cleared d4; write to d4 loaded d4; write to d6
    computed d5*d6+d4; write to d7 computed (d4:d5) / d7; q to d5, r to
    d4". Its _write_7 stores (n / d) + ((n % d) << 16) in the 32-bit D4:D5,
    so the high bits of a quotient wider than 16 bits add into D4.
    Release L ORK-LM divides with "R0 TO D5; IM(20) TO D7" (no D4 write)
    and relies on the cleared D4.
"""
from ..bus import NO_SYN, Device

M16 = 0xFFFF


class MulDiv(Device):
    numbers = (0o4, 0o5, 0o6, 0o7)

    def __init__(self):
        self.d4 = 0
        self.d5 = 0

    def read(self, dev):
        if dev == 0o4:
            return self.d4
        if dev == 0o5:
            return self.d5
        return NO_SYN

    def write(self, dev, value):
        value &= M16
        if dev == 0o4:
            self.d4 = value
        elif dev == 0o5:
            self.d5 = value
            self.d4 = 0         # XPL.h: "write to d5 cleared d4"
        elif dev == 0o6:
            p = self.d5 * value + self.d4
            self.d5 = p & M16
            self.d4 = (p >> 16) & M16
        else:
            n = (self.d4 << 16) | self.d5
            if value == 0:
                # CHOICE: divide by zero is undefined; return all ones and
                # leave the dividend's low word as the remainder.
                self.d4, self.d5 = self.d5, M16
            else:
                q, r = divmod(n, value)
                both = (q + (r << 16)) & 0xFFFFFFFF   # as XPL.h _write_7
                self.d5 = both & M16
                self.d4 = both >> 16
        return True
