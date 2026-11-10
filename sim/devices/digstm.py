"""Digital sample-to-memory (M18): the Synclavier3 interpreter's native
routines 64-76 (-XPL/INTRPRTR "Digital STM interface"), with an audio file
as the digital input. Spec: docs/devices/digital-stm.md.

Calls [OBS syn53.dis, -XPL/INTRPRTR]: `PCI TO RTNV` followed by the routine
number (octal 100-114) as data, arguments in R0-R2, result in R0. RTNV is a
relative transfer *never*: a no-op on the instrument. sim/cpu.py calls
`DigitalStm.call(cpu, n)` for n = 64-76 when `cpu.native` is set; every other
routine number stays a no-op.

SYN-5.3 offers the digital record device only when D51 bit 0x8000 (D57 may
be read; set on every Model D system, sim/system.py) and D57 bit 0x4000
(D57_DIG_STM_EXISTS, AbleInterpreter.h) are set (STDRSOUD:337-353,
STDRSOUF:207-209); boot_from_w0(dig_stm=...) sets the D57 bit.

  64 start        the input starts: frames arrive at the rate setting from
                  now on, counted in simulated time [CHOICE: the source
                  rewinds to its first frame at each start, so a recording
                  captures the file from its beginning]
  65 samples      R0 = frames arrived and not yet imported or tossed,
                  0..32767 [INF: SYN-5.3 compares it with 256 for mono and
                  stereo alike, STRECSOU:483 "256 samples (512 if stereo)"]
  66 underflowed  R0 = 1 if an import or toss since the last start found
                  fewer than 256 frames arrived, else 0 [CHOICE: a file
                  source loses nothing; SYN-5.3 imports only after samples()
                  says 256 are there, so this stays 0]
  67 stop         the input stops (frames stop arriving)
  68 do_import    256 frames to poly memory through D157 writes, as the CPU's
                  own writes (SYN-5.3 has just set the write address with
                  psmwrite(base,sec#,0), FC 18): 256 words mono, 512 words
                  stereo (left, right interleaved); then lmax/rmax
  69 lmax         R0 = max |sample| of the left (mono) channel in the last
                  import or toss (unsigned: |-32768| = 32768) [INF: plotted
                  as shr(max, 9) "0 to 64", STRECSOU:359]
  70 rmax         R0 = the same for the right channel (0 when mono)
  71 toss_data    as do_import without the writes (level check)
  72 latch(0, stereo, rate)  R0 = 0 and the input is reserved, stereo =
                  R1 bit 0, rate setting = R2 (1..1023, kHz x 10); R0 = 1
                  without a source ("Digital STM is not installed or is in
                  use by another application", STRECSOA:61)
  73 release      the input is freed (and stops)
  74 get_rate     R0 = the rate setting, kHz x 10 as stm.record.rate (441 =
                  44.1 kHz) [OBS STDRSOUD:372-404: compared with and copied
                  into stm.record.rate; typed rates 400-505]; it starts as
                  the source's rate (480 without a source)
  75 set_rate(rate)  rate setting = R0 (1..1023) [CHOICE: the frames then
                  arrive at that rate; samples are not resampled]
  76 get_chan     R0 = 0 [CHOICE: no channel choice]
Routines without a result leave R0 as it was [CHOICE].

Channels: a stereo source recorded mono gives its left channel; a mono
source recorded stereo gives the same word on both [CHOICE]. Frames after
the end of the source are 0 (silence; the input keeps running).

Time: frames arrive from start at `rate` x 100 per second of simulated
time: each instruction's time adds ns x rate to an accumulator; at
10 000 000 one frame has arrived (exactly as the HDL, hdl/core/dig_stm.sv,
counts each tick). Evaluated lazily from cpu.time_ns at each call (the time
before the calling instruction's own tick).
"""
import struct

MAGIC = b"SYNCSTM1"
HEADER_WORDS = 256
FRAME_UNIT = 10_000_000      # ns x (rate in 100 Hz) per frame
MAX_BLOCKS = 65535           # data blocks the core addresses (16-bit block numbers)

R_START, R_SAMPLES, R_UNDERFLOWED, R_STOP, R_IMPORT, R_LMAX, R_RMAX, R_TOSS, \
    R_LATCH, R_RELEASE, R_GET_RATE, R_SET_RATE, R_GET_CHAN = range(64, 77)
FIRST, LAST = R_START, R_GET_CHAN
D57_DIG_STM = 0x4000         # AbleInterpreter.h D57_DIG_STM_EXISTS
DEFAULT_RATE = 480


class Source:
    """A sample source: `samples` (signed 16-bit ints, interleaved when
    channels = 2), `channels` 1 or 2, `rate` in units of 100 Hz."""

    def __init__(self, samples, channels, rate, rate_hz=None):
        if channels not in (1, 2):
            raise ValueError("channels: 1 or 2")
        self.channels = channels
        self.rate = rate
        self.rate_hz = rate_hz if rate_hz is not None else rate * 100
        self.frames = len(samples) // channels
        self.words = [s & 0xFFFF for s in samples[:self.frames * channels]]

    def word(self, frame, chan):
        """Sample word of `frame`, channel `chan` (0 left, 1 right)."""
        if frame >= self.frames:
            return 0
        c = chan if self.channels == 2 else 0
        return self.words[frame * self.channels + c]

    # ---------------------------------------------------- file (tools/stm_source.py)
    def to_bytes(self):
        """The S5 file: a 512-byte header block, then the samples as
        big-endian words, padded with zeros to whole 512-byte blocks.

        Header (big-endian words): 0-3 "SYNCSTM1", 4 version 1, 5 channels,
        6 rate (100 Hz units, kHz x 10), 7-8 frames (high word first),
        9-10 the original rate in Hz."""
        hdr = MAGIC + struct.pack(">HHHII", 1, self.channels, self.rate, self.frames, self.rate_hz)
        data = struct.pack(">%dH" % len(self.words), *self.words)
        data += bytes(-len(data) % 512)
        return hdr.ljust(512, b"\0") + data

    @classmethod
    def from_bytes(cls, b):
        if b[:8] != MAGIC:
            raise ValueError("not a digital STM source (magic %r)" % b[:8])
        version, ch, rate, frames, hz = struct.unpack_from(">HHHII", b, 8)
        if version != 1:
            raise ValueError("source version %d" % version)
        n = frames * ch
        words = struct.unpack_from(">%dH" % n, b, 512)
        return cls([w - 0x10000 if w & 0x8000 else w for w in words], ch, rate, hz)

    @classmethod
    def from_file(cls, path):
        return cls.from_bytes(open(path, "rb").read())


class DigitalStm:
    """Native routines 64-76 for one CPU. `source`: a Source or None (no
    file: latch fails). `poly`: the D154-D157 device the imports write to
    (set by boot_from_w0; cpu.poly otherwise)."""

    def __init__(self, source=None):
        self.source = source
        self.poly = None
        self.rate = source.rate if source is not None else DEFAULT_RATE
        self.latched = False
        self.stereo = 0
        self.running = False
        self.t_mark = 0              # time the accumulator was brought up to
        self.acc = 0
        self.arrived = 0             # frames since start
        self.consumed = 0            # frames imported or tossed since start
        self.underflow = 0
        self.lmax = self.rmax = 0
        self.calls = {}              # routine -> count (diagnostics)
        self.imports = 0
        self._mounted = False        # a source mounted since the last call

    def mount(self, source):
        """A (new) source file in S5, or None: it takes effect at the next
        call, which first counts the frames up to now at the old rate; the
        rate setting becomes the source's (as the core reads the header at
        the first call after a mount)."""
        self._pending = source
        self._mounted = True

    def idle(self):
        """True in the power-on state (nothing latched or running), the
        only state the core's handler can start a trace in."""
        return not (self.latched or self.running or self.arrived or self.consumed
                    or self.underflow or self.lmax or self.rmax or self.stereo)

    def _advance(self, now):
        if self.running:
            self.acc += (now - self.t_mark) * self.rate
            self.arrived = (self.arrived + self.acc // FRAME_UNIT) & 0xFFFFFFFF
            self.acc %= FRAME_UNIT
        self.t_mark = now

    def _avail(self):
        a = (self.arrived - self.consumed) & 0xFFFFFFFF
        return a - (1 << 32) if a & 0x80000000 else a

    def _block(self, poly):
        """Import (poly given) or toss 256 frames."""
        if self._avail() < 256:
            self.underflow = 1
        lmax = rmax = 0
        f0 = self.consumed
        src = self.source
        for j in range(256 << self.stereo):
            i, c = j >> self.stereo, j & self.stereo
            w = src.word(f0 + i, c) if src is not None else 0
            m = (-w) & 0xFFFF if w & 0x8000 else w
            if c:
                rmax = max(rmax, m)
            else:
                lmax = max(lmax, m)
            if poly is not None:
                poly.write(0o157, w)
        self.lmax, self.rmax = lmax, rmax
        self.consumed = (self.consumed + 256) & 0xFFFFFFFF

    def call(self, cpu, n):
        """Native routine n (64-76), arguments in cpu.r[0..2]."""
        self.calls[n] = self.calls.get(n, 0) + 1
        self._advance(cpu.time_ns)
        if self._mounted:
            self._mounted = False
            self.source = self._pending
            if self.source is not None:
                self.rate = self.source.rate
        r = cpu.r
        res = None
        if n == R_START:
            self.running = True
            self.acc = self.arrived = self.consumed = 0
            self.underflow = 0
        elif n == R_SAMPLES:
            res = max(0, min(0x7FFF, self._avail()))
        elif n == R_UNDERFLOWED:
            res = self.underflow
        elif n == R_STOP:
            self.running = False
        elif n == R_IMPORT:
            self._block(self.poly if self.poly is not None else cpu.poly)
            self.imports += 1
        elif n == R_LMAX:
            res = self.lmax
        elif n == R_RMAX:
            res = self.rmax
        elif n == R_TOSS:
            self._block(None)
        elif n == R_LATCH:
            if self.source is None:
                res = 1
            else:
                self.latched = True
                self.stereo = r[1] & 1
                self._set_rate(r[2])
                res = 0
        elif n == R_RELEASE:
            self.latched = False
            self.running = False
        elif n == R_GET_RATE:
            res = self.rate
        elif n == R_SET_RATE:
            self._set_rate(r[0])
        elif n == R_GET_CHAN:
            res = 0
        if res is not None:
            r[0] = res & 0xFFFF

    def _set_rate(self, v):
        if 1 <= v <= 1023:
            self.rate = v
