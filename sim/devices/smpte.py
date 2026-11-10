"""SMPTE reader, D70 subsystem 8, fed from MIDI Time Code (M20):
docs/devices/smpte.md.

SYN-5.3 reads the NED SMPTE reader through the MIDI card's D70-D73 bus
(SYNLITS/GLOBLITS:58-64; 10-INT/144-TIM1 SMPTE.SCAN every 20 ms while
SMPTE is on):

  D70  write 8: select the reader; read: 8 | 256 (256 = data available)
  D71  write: opcode (frame mode "220"/"221"/"222", "200" error correction;
       latched, not used); read: status << 8 | bit, bit 0-79 within the
       frame being read; status "200" no sync, "004" drop frame
  D72  read: seconds << 8 | frames of the last complete frame
  D73  read: hours << 8 | minutes of it; the read latches the next reading

A reading is latched when D73 is read, so SMPTE.SCAN gets the one taken
at its previous scan ("THE D70 BOARD PROVIDES SMPTE READINGS THAT ARE 1
BEHIND", 143-SIO LOCK.TO.SMPTE), and the time is that of the frame before
the one the bit counts in ("WE DON'T NORMALLY SEE THE SMPTE FRAME UNTIL THE
END OF THE FRAME").

The time code comes from MIDI Time Code on MIDI in (receive(): every
byte from the UART, unfiltered): quarter frames F1 0nnn dddd and the
full-frame SysEx F0 7F id 01 01 hh mm ss ff F7. Eight quarter frames in
order (pieces 0-7) give the time T0 of piece 0; at piece 7 the reader
stands at frame T0 + 1, quarter 3; each further quarter frame in order
moves it a quarter (20 of the 80 bits). Between quarter frames the bit
advances 20 per measured quarter-frame period (interpolated in simulated
time, at most to the quarter's last bit). The reading is invalid (status
"200") before the first eight pieces, after a piece out of order or a
full frame (until eight pieces again), and when no quarter frame has come
for LIMIT_NS. The frame rate (24, 25, 30 drop, 30) is the one in the time
code; drop frame sets status "004".

The interpolation is the same integer algorithm as hdl/dev/dev_smpte.sv
(per tick of simulated time), so lockstep reads match exactly.
"""

SUBSYS = 8                    # SMPTE.SUBSYS
AVAILABLE = 0o400             # D70 read: data available
NO_SYNC = 0o200               # status: data invalid
DROP = 0o004                  # status: drop frame bit
LIMIT_NS = 50_000_000         # no quarter frame for this long: invalid
FPS = (24, 25, 30, 30)        # MTC rate code 0-3 (2: 29.97 drop frame)


def next_frame(t, rate):
    """(h, m, s, f) one frame later at MTC rate code `rate` (out-of-range
    fields carry as their last value does, as in dev_smpte.sv)."""
    h, m, s, f = t
    if f < FPS[rate] - 1:
        return h, m, s, f + 1
    f = 0
    if s < 59:
        s += 1
    else:
        s = 0
        if m < 59:
            m += 1
        else:
            m = 0
            h = h + 1 if h < 23 else 0
    if rate == 2 and s == 0 and m % 10:
        f = 2                           # drop frame: no frames 0, 1
    return h, m, s, f


class SmpteReader:
    """The reader's registers and MTC decoder (owned by MidiSubsystem,
    which passes D70-D73 accesses while subsystem 8 is selected)."""

    def __init__(self):
        self.opcode = 0
        self.info = (NO_SYNC << 8, 0, 0)     # latched D71, D72, D73
        # MTC decoder
        self.sx = 0                          # SysEx bytes seen (0: none)
        self.sxb = [0] * 8
        self.qf = False                      # F1 seen, data byte next
        self.nib = [0] * 8
        self.got = 0                         # pieces of this run (bits)
        self.last = 7                        # last piece
        self.valid = False
        self.rate = 3
        self.cur = (0, 0, 0, 0)              # frame the bit counts in
        self.prev = (0, 0, 0, 0)             # last complete frame (read)
        self.quarter = 0
        # time since the last quarter frame, its period, interpolation
        self.elapsed = LIMIT_NS
        self.period = 0
        self.frac = 0
        self.acc = 0

    # -- MIDI in -----------------------------------------------------------
    def receive(self, b):
        b &= 0xFF
        if b >= 0xF8:                        # real time: anywhere, ignored
            return
        if b & 0x80:
            self.qf = b == 0xF1
            self.sx = 1 if b == 0xF0 else 0
            return
        if self.qf:
            self.qf = False
            self._quarter_frame(b >> 4 & 7, b & 15)
        elif 0 < self.sx < 9:
            self.sxb[self.sx - 1] = b
            self.sx += 1
            s = self.sxb
            if self.sx == 9 and s[0] == 0x7F and s[2] == 1 and s[3] == 1:
                self.sx = 0                  # full frame: located, stopped
                self.rate = s[4] >> 5 & 3
                self.cur = self.prev = (s[4] & 31, s[5] & 63, s[6] & 63, s[7] & 31)
                self.quarter = 0
                self.valid = False
                self.got = 0

    def _quarter_frame(self, piece, nib):
        self.period = self.elapsed
        self.elapsed = 0
        self.frac = 0
        self.acc = 0
        if piece == 0:
            self.got = 0
        elif piece != (self.last + 1) & 7:
            self.got = 0
            self.valid = False
        self.last = piece
        self.nib[piece] = nib
        self.got |= 1 << piece
        if piece == 7 and self.got == 0xFF:
            n = self.nib
            self.rate = n[7] >> 1 & 3
            t0 = ((n[7] & 1) << 4 | n[6], (n[5] & 3) << 4 | n[4],
                  (n[3] & 3) << 4 | n[2], (n[1] & 1) << 4 | n[0])
            self.prev, self.cur = t0, next_frame(t0, self.rate)
            self.quarter = 3
            self.valid = True
        elif self.valid:
            self.quarter += 1
            if self.quarter == 4:
                self.quarter = 0
                self.prev, self.cur = self.cur, next_frame(self.cur, self.rate)

    def tick(self, ns):
        if self.elapsed < LIMIT_NS:
            self.elapsed = min(self.elapsed + ns, LIMIT_NS)
        if self.period and self.frac < 19:
            a = self.acc + 20 * ns
            if a >= self.period:
                self.frac += 1
                a -= self.period
            self.acc = a

    # -- registers (subsystem 8 selected) ------------------------------------
    def latch(self):
        ok = self.valid and self.elapsed < LIMIT_NS
        status = (0 if ok else NO_SYNC) | (DROP if self.rate == 2 else 0)
        h, m, s, f = self.prev
        self.info = (status << 8 | (self.quarter * 20 + self.frac), s << 8 | f, h << 8 | m)

    def read(self, dev):
        if dev == 0o70:
            return SUBSYS | AVAILABLE
        if dev == 0o73:
            v = self.info[2]
            self.latch()
            return v
        return self.info[dev - 0o71]

    def write(self, dev, value):
        if dev == 0o71:
            self.opcode = value & 0xFFFF


# -- MTC senders (tests, lockstep actions) -------------------------------------
def quarter_frame_ns(rate):
    """Nominal quarter-frame period in ns (29.97 for drop frame)."""
    return 1001 * 10**9 // 120_000 if rate == 2 else 10**9 // (4 * FPS[rate])


def quarter_frames(t0, rate, count):
    """`count` quarter-frame messages (F1 dd) from piece 0 of frame t0, as
    a sender running forward sends them: each 8 carry the frame of their
    piece 0, which advances by two frames."""
    out, t = [], t0
    for i in range(count):
        piece = i & 7
        if i and piece == 0:
            t = next_frame(next_frame(t, rate), rate)
        h, m, s, f = t
        nib = (f & 15, f >> 4, s & 15, s >> 4, m & 15, m >> 4, h & 15, rate << 1 | h >> 4)[piece]
        out.append((0xF1, piece << 4 | nib))
    return out


def full_frame(t, rate, device=0x7F):
    """The MTC full-frame SysEx for (h, m, s, f)."""
    h, m, s, f = t
    return (0xF0, 0x7F, device, 0x01, 0x01, rate << 5 | h, m, s, f, 0xF7)
