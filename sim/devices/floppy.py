"""D100 floppy disk controller (devices 100-104), register level (M1.6 step B).

Evidence (NED source, MIT, jbemond/Software):
  * FLPLOAD (loader) and RTP DISKREAD/DISKSEEK (runtime driver) program the
    controller like a Western Digital FD1771/179x:
      D100  write = command, read = status
      D101  track register (written with the saved head position, read back
            after a read to update it)
      D102  sector register (written, then read back and compared)
      D103  data register: seek target, and the byte stream of a sector
      D104  write = drive select: drive + 2*side + 4*density + 8*rate +
            16*precomp + 32*motor speed (+ 100000 on a D100A); read = drive
            ID, D100A only
  * Commands used: restore = stepping rate (0-3), seek = 20 + rate,
    step in = 100 + rate ("DATA 103 STEP IN COMMAND"), read sector = 210
    ("READ COMMAND, NOT MULTIPLE, IBM FORMAT") or 214 (with 10 ms head
    settle), force interrupt = 320 ("HD0").
  * Status: 1 busy, 2 data request (DRQ) for Type II, index pulse for
    Type I/forced interrupt (d100_disk_check counts index edges after
    "HD0"), 4 lost data, 10 CRC, 20 record not found (seek error for
    Type I), 100 write protect (DEVUTIL: shr(status, 5) and 2), 200 not
    ready ("TEST NOT READY BIT").
  * Byte order: the read loops take the first byte from D103, then the
    second, and combine them with BSOR, so the first byte on the disk is
    the low half of the word.
  * Track/sector mapping (DISKSEEK): cylinder = sector / sectors-per-
    cylinder; if the remainder is >= sectors-per-track it is on side 1;
    sector numbers start at 1. Release L's F0/F1 configuration: 5 sectors
    per cylinder, 5 per track (single-sided).

This models the original D100 (no D100A drive ID, no side compare). Read
Address, Read Track, Write Track (formatting) and multi-sector commands are
not modelled: issuing one halts the CPU (no SYN) so it is noticed.
"""
from ..bus import NO_SYN, Device

SECTOR_WORDS = 256
SECTOR_BYTES = 2 * SECTOR_WORDS

BUSY = 0o1
DRQ = 0o2            # Type II
INDEX = 0o2          # Type I / forced interrupt
TRACK0 = 0o4         # Type I
LOST_DATA = 0o4      # Type II
CRC_ERROR = 0o10
RNF = 0o20           # record not found (Type II) / seek error (Type I)
HEAD_LOADED = 0o40   # Type I
PROTECT = 0o100
NOT_READY = 0o200

#: FD1771 stepping rates in ns for rate codes 0-3 (data sheet: 6, 6, 10, 20 ms)
STEP_NS = (6_000_000, 6_000_000, 10_000_000, 20_000_000)
#: CHOICE: 360 rpm (8" drive) and a 4 ms index pulse
REV_NS = 166_666_667
INDEX_NS = 4_000_000
#: CHOICE: a sector command takes this long before the first DRQ / result
SECTOR_START_NS = 50_000


class Media:
    """A floppy's sectors (list of 16-bit words) and its geometry."""

    def __init__(self, words, sectors_per_track=5, sides=1, protected=False):
        n = (len(words) + SECTOR_WORDS - 1) // SECTOR_WORDS
        self.words = list(words) + [0] * (n * SECTOR_WORDS - len(words))
        self.sectors = n
        self.spt = sectors_per_track
        self.sides = sides
        self.protected = protected

    def logical(self, cylinder, side, sector):
        """Logical sector number for a physical address, or None."""
        if not (1 <= sector <= self.spt and 0 <= side < self.sides):
            return None
        n = (cylinder * self.sides + side) * self.spt + sector - 1
        return n if n < self.sectors else None


class FloppyController(Device):
    numbers = (0o100, 0o101, 0o102, 0o103, 0o104)

    def __init__(self):
        self.media = [None, None]   # drive 0 (F0), drive 1 (F1)
        self.head = [0, 0]          # physical cylinder of each drive
        self.select = 0             # last D104 write
        self.track = 0
        self.sector = 1
        self.data = 0
        self.status = 0
        self.type1 = True           # status format: Type I vs Type II
        self.time = 0               # ns, for the index pulse
        self.busy_ns = 0            # remaining time of a Type I command
        self.pending = None         # Type II: ("read"|"write", logical) once started
        self.buf = None             # bytes being read / written
        self.pos = 0
        self.step_dir = 1
        self.commands = []          # (command, drive, track, sector) history, for debugging

    # ------------------------------------------------------------ host side

    def insert(self, drive, media):
        self.media[drive] = media

    @property
    def drive(self):
        return self.select & 1

    @property
    def side(self):
        return (self.select >> 1) & 1

    def _media(self):
        return self.media[self.drive]

    # ------------------------------------------------------------ registers

    def read(self, dev):
        if dev == 0o100:
            return self._status()
        if dev == 0o101:
            return self.track
        if dev == 0o102:
            return self.sector
        if dev == 0o103:
            if self.buf is not None and not self.pending and self._reading():
                b = self.buf[self.pos]
                self.pos += 1
                if self.pos >= len(self.buf):
                    self._finish(0)
                self.data = b
                return b
            return self.data
        return NO_SYN  # D104 read: drive ID exists on the D100A only

    def write(self, dev, value):
        value &= 0xFFFF
        if dev == 0o100:
            return self._command(value & 0o377)
        if dev == 0o101:
            self.track = value & 0o377
        elif dev == 0o102:
            self.sector = value & 0o377
        elif dev == 0o103:
            self.data = value & 0o377
            if self.buf is not None and not self.pending and not self._reading():
                self.buf[self.pos] = self.data
                self.pos += 1
                if self.pos >= len(self.buf):
                    self._commit_write()
        else:
            self.select = value
        return True

    def tick(self, ns):
        self.time += ns
        if self.busy_ns > 0:
            self.busy_ns -= ns
            if self.busy_ns <= 0:
                self.status &= ~BUSY
        if self.pending:
            kind, lsn, wait = self.pending
            wait -= ns
            if wait > 0:
                self.pending = (kind, lsn, wait)
            else:
                self.pending = None
                self._start_transfer(kind, lsn)

    # ------------------------------------------------------------ internals

    def _reading(self):
        return self._kind == "read"

    def _status(self):
        m = self._media()
        s = self.status
        if m is None:
            s |= NOT_READY
        if self.type1:
            s &= ~(INDEX | TRACK0 | PROTECT)
            if m is not None:
                if self.time % REV_NS < INDEX_NS:
                    s |= INDEX
                if m.protected:
                    s |= PROTECT
            if self.head[self.drive] == 0:
                s |= TRACK0
        else:
            s &= ~DRQ
            if self.buf is not None and not self.pending:
                s |= DRQ
        return s

    def _command(self, cmd):
        self.commands.append((cmd, self.drive, self.track, self.sector))
        if len(self.commands) > 256:
            del self.commands[:128]
        hi = cmd >> 4
        if hi == 0o15:                          # D0-DF: force interrupt
            self.buf = None
            self.pending = None
            self.busy_ns = 0
            self.status = 0
            self.type1 = True
            return True
        if self.status & BUSY:
            return True                         # ignored while busy (as on the WD chips)
        if hi < 8:
            return self._type1(cmd)
        if hi in (8, 0o12) and not cmd & 0o20:  # single-sector read / write
            return self._type2("read" if hi == 8 else "write")
        return False                            # not modelled: halt and report

    def _type1(self, cmd):
        hi = cmd >> 4
        d = self.drive
        start = self.head[d]
        self.type1 = True
        self.status = 0
        if hi == 0:                             # restore
            if self._media() is None:
                target = start                  # no track 0 signal: gives up
                self.status |= RNF
            else:
                target = 0
            self.track = 0
        elif hi == 1:                           # seek
            target = max(0, start + self.data - self.track)
            self.track = self.data
        else:                                   # step / step in / step out
            if hi >= 6:
                self.step_dir = -1
            elif hi >= 4:
                self.step_dir = 1
            target = max(0, start + self.step_dir)
            if cmd & 0o20:                      # u: update the track register
                self.track = (self.track + self.step_dir) & 0o377
        self.head[d] = target
        self.busy_ns = STEP_NS[cmd & 3] * max(1, abs(target - start))
        self.status |= BUSY
        if cmd & 0o10:
            self.status |= HEAD_LOADED
        return True

    def _type2(self, kind):
        self._kind = kind
        self.type1 = False
        m = self._media()
        if m is None:
            self.status = NOT_READY
            return True
        if kind == "write" and m.protected:
            self.status = PROTECT
            return True
        lsn = None
        if self.track == self.head[self.drive]:
            lsn = m.logical(self.head[self.drive], self.side, self.sector)
        self.status = BUSY
        self.pending = (kind, lsn, SECTOR_START_NS)
        return True

    def _start_transfer(self, kind, lsn):
        if lsn is None:
            self._finish(RNF)
            return
        m = self._media()
        if kind == "read":
            words = m.words[lsn * SECTOR_WORDS:(lsn + 1) * SECTOR_WORDS]
            self.buf = bytearray()
            for w in words:
                self.buf.append(w & 0o377)
                self.buf.append(w >> 8)
        else:
            self.buf = bytearray(SECTOR_BYTES)
            self._lsn = lsn
        self.pos = 0

    def _commit_write(self):
        m = self._media()
        base = self._lsn * SECTOR_WORDS
        for i in range(SECTOR_WORDS):
            m.words[base + i] = self.buf[2 * i] | (self.buf[2 * i + 1] << 8)
        self._finish(0)

    def _finish(self, err):
        self.buf = None
        self.status = err  # busy and DRQ clear

    _kind = "read"
    _lsn = 0
