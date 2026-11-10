"""D154-D157 poly sampling synthesizer (M7.7), as Release 5.3 drives it.

Specification and evidence: docs/poly-synth.md (section numbers below).
`bins` bins (default 1), each with `voices` voices and `sectors` sectors of
16-bit poly memory of its own (default 32 voices and 65536 sectors = 32 MB,
one 32 MB page: a 3200; a 6400 has 2 bins (5.3 manual: "move sound files
from poly bin 1 to poly bin 2"), a 9600 3 [INF]). Bins from `bins` up are
absent (their channel numbers do not read back). The last bin may hold
fewer voices (`last_voices`, M16: voice cards came in steps of 4); its
channels from there up keep nothing, like channels above the voice count.
`mono`: mono voice cards (a 3200's, options bit `o#pvoice`): SYN-5.3 then
pans hard right, and the right sum goes to both outputs [CHOICE].

  D155 PSC  write: channel (low 8 bits latched: bin 7-6, channel 5-0).
            read: the latched channel when its bin is present, else 0;
            bit 8 (new D/A controller) is 0.
  D156 PSF  write: function code. read: the current function code.
  D157 PSD  write: data for (channel, FC), then FC moves to its successor
            (SUCCESSOR, section 1.3). read: see `_read_data`. Poly memory
            reads and writes go to the bin of the latched channel [CHOICE:
            one function code and one address counter for all bins;
            SYN-5.3 writes PSC and the address before each transfer,
            PSMREAD/PSMWRITE, POLYSOU:91-132].
  D154 PSX  extended data (D/A controller FCs 64/65 only): accepted.

Voice model (sections 3.1-3.7) [INF, CHOICES marked]:
  * a rate generator clocked at F0 = 101 010.1 Hz (9900 ns) adds INC
    (written INC-1) to a 9-bit accumulator; when it reaches MOD (written
    256-MOD) it drops by MOD and that is one step (at most one per tick);
  * a step moves the sample position by PI words; when position + PSWL
    (negative length) reaches 0 the voice loops back by PSLL (negative loop
    length) if the loop bit is set and PSLL != 0, else its on bit clears
    (PSRON reads 0). Comparing the position (not a separate counter) makes
    a PSWL rewrite on a sounding voice take effect (audition while loading);
  * PSON bit 0 rising resets the position to 0 (start of the table);
  * every 40 us (25 kHz) the envelope counter and the volume ramps step
    while the envelope or a volume is still moving [CHOICE: settled
    counters hold, so stepping on demand and stepping continuously agree]
    (sections 3.5, 3.6): ECNT counts to 4096 and reloads EMOD; then EACU +=
    EINC and on its wrap EVAL moves toward ELIM by EDEL; each current volume
    moves toward its destination by max(1, |difference| >> 9);
  * an odd voice whose even neighbour has FC 59 (even stereo master) set
    plays the word after its master's position (interleaved stereo frames);
  * output of a voice [CHOICE: the mix is not in the source]: the word at
    its current address (base + position; 0 when off) x EVAL / 4096 x
    volume / 4096 per side; the voices are summed.
"""
from array import array

from ..bus import Device

F0_TICK_NS = 9900          # 101 010.1 Hz rate generator (section 3.2)
ENV_TICK_NS = 40_000       # 25 kHz envelope / volume clock (sections 3.5, 3.6)
SECTOR_WORDS = 256

PSWL, PSBA, PSLL, PSPI, PSINC, PSMOD, PSON, PSRON, PSNUMV = 0, 2, 4, 6, 8, 9, 10, 11, 12
PSWMA, PSRMA = 16, 20
PSECNT, PSEMOD, PSEACU, PSEINC, PSELIM, PSEVAL, PSEDEL = 32, 33, 34, 35, 36, 37, 38
PSRCVOL, PSRDVOL, PSLCVOL, PSLDVOL = 40, 41, 42, 43
PSADEVSM = 59

#: FC after a PSD write (section 1.3); FCs not listed stay.
SUCCESSOR = {0: 1, 1: 2, 2: 3, 3: 4, 4: 5, 5: 6, 6: 7, 7: 8, 8: 9, 9: 10,
             16: 17, 17: 18, 20: 21, 21: 22,
             33: 35, 35: 38, 38: 32, 32: 34, 34: 36, 36: 37,
             40: 42, 42: 41, 41: 43,
             25: 0, 26: 0, 27: 28}

ENV_REGS = {PSECNT: "ecnt", PSEMOD: "emod", PSEACU: "eacu", PSEINC: "einc",
            PSELIM: "elim", PSEVAL: "eval", PSEDEL: "edel",
            PSRCVOL: "rcur", PSRDVOL: "rdest", PSLCVOL: "lcur", PSLDVOL: "ldest"}


def two_word(w1, w2, signed):
    """28-bit value from PSD words (section 1.4): w1 = bits 23-8, w2 = page
    bits 27-24 in [11:8] and bits 7-0 in [7:0]."""
    v = ((w2 >> 8) & 0xF) << 24 | (w1 & 0xFFFF) << 8 | (w2 & 0xFF)
    if signed and v & (1 << 27):
        v -= 1 << 28
    return v


class PolyVoice:
    def __init__(self):
        self.words = [0] * 8         # FC 0-7 as written
        self.wl = self.ba = self.ll = self.pi = 0
        self.inc_w = 255             # written INC-1 (INC 256)
        self.mod_w = 0               # written 256-MOD (MOD 256)
        self.on = 0
        self.master = 0              # FC 59
        self.pos = 0
        self.acc = 0
        self.ecnt = self.emod = self.eacu = self.einc = 0
        self.elim = self.eval = self.edel = 0
        self.rcur = self.rdest = self.lcur = self.ldest = 0
        self.out = 0                 # current sample (signed)
        self.slave = False           # follows the even voice below (FC 59)

    def set_word(self, fc, value):
        self.words[fc] = value & 0xFFFF
        if fc & 1:
            w1, w2 = self.words[fc - 1], self.words[fc]
            if fc == 1:
                self.wl = two_word(w1, w2, True)
            elif fc == 3:
                self.ba = two_word(w1, w2, False)
            elif fc == 5:
                self.ll = two_word(w1, w2, True)
            else:
                self.pi = two_word(w1, w2, False)

    def settled(self):
        return (self.eval == self.elim and self.rcur == self.rdest
                and self.lcur == self.ldest)

    def env_tick(self):
        self.ecnt += 1
        if self.ecnt >= 4096:
            self.ecnt = self.emod & 0xFFF
            self.eacu += self.einc & 0xFFF
            if self.eacu >= 4096:
                self.eacu -= 4096
                d = self.edel & 0xFFF
                if self.eval < self.elim:
                    self.eval = min(self.elim, self.eval + d)
                elif self.eval > self.elim:
                    self.eval = max(self.elim, self.eval - d)
        self.rcur = _ramp(self.rcur, self.rdest)
        self.lcur = _ramp(self.lcur, self.ldest)


def _ramp(cur, dest):
    if cur == dest:
        return cur
    step = max(1, abs(dest - cur) >> 9)
    return cur + step if dest > cur else cur - step


class PolySynth(Device):
    """D154-D157 with `bins` bins of `voices` voices and `sectors` sectors.
    Voice i is bin i // voices, channel i % voices of that bin."""

    numbers = (0o154, 0o155, 0o156, 0o157)

    def __init__(self, voices=32, sectors=65536, sample_rate=None, bins=1,
                 last_voices=None, mono=False):
        if not 4 <= voices <= 32 or voices % 4:
            raise ValueError("voices: 4..32 in steps of 4")
        if last_voices is None:
            last_voices = voices
        if not 4 <= last_voices <= voices or last_voices % 4:
            raise ValueError("last_voices: 4..voices in steps of 4")
        if sectors % 256:
            raise ValueError("sectors: a multiple of 256 (the size probe's step)")
        if not 1 <= bins <= 4:
            raise ValueError("bins: 1..4")
        self.nvoices = voices        # per bin (voice i is bin i // voices)
        self.nbins = bins
        self.bin_voices = [voices] * (bins - 1) + [last_voices]
        self.mono = mono
        self.sectors = sectors       # per bin
        self.bin_words = sectors * SECTOR_WORDS
        self.mem = array("H", bytes(2 * bins * self.bin_words))   # bin b from b * bin_words
        self.voice = [PolyVoice() for _ in range(voices * bins)]
        self.channel = 0
        self.fc = 0
        self.addr_hi = 0
        self.addr = 0                # memory address counter (within the bin)
        self.time_ns = 0
        self.done_ns = 0             # voices advanced to here
        self.rate_tick = 0           # next rate-generator tick number
        self.env_tick = 0
        #: optional 48 kHz (or `sample_rate`) stereo output: list of (l, r)
        self.sample_rate = sample_rate
        self.samples = [] if sample_rate else None
        self.sample_k = 0
        self.writes = 0

    # ------------------------------------------------------------ registers
    def _bin(self):
        """The latched channel's bin, or None when that bin is absent."""
        b = self.channel >> 6
        return b if b < self.nbins else None

    def _cur(self):
        # CHOICE: channels at or above the voice count ("ghost/refresh
        # channels", POLYSOU:1101) keep nothing: writes dropped, reads 0
        b, c = self._bin(), self.channel & 63
        return self.voice[b * self.nvoices + c] if b is not None and c < self.bin_voices[b] else None

    def read(self, dev):
        if dev == 0o155:
            return self.channel if self._bin() is not None else 0
        if dev == 0o156:
            return self.fc
        if dev == 0o157:
            return self._read_data()
        return 0

    def _read_data(self):
        fc = self.fc
        if fc == PSNUMV:                         # the latched channel's bin
            b = self._bin()
            n = self.bin_voices[b] if b is not None else self.nvoices
            return n // 4 | 0x10 | (0x20 if n > 16 else 0)
        if fc == 22:
            v = self._mem_read(self.addr, self._bin())
            self.addr += 1
            return v
        v = self._cur()
        if v is None:
            return 0
        self.advance()
        if fc == PSRON:
            return v.on
        if fc in ENV_REGS:
            return getattr(v, ENV_REGS[fc]) & 0xFFFF
        if fc < 8:
            return v.words[fc]
        if fc == PSINC:
            return v.inc_w
        if fc == PSMOD:
            return v.mod_w
        if fc == PSON:
            return v.on
        return 0

    def write(self, dev, value):
        value &= 0xFFFF
        if dev == 0o155:
            self.channel = value & 0xFF
        elif dev == 0o156:
            self.fc = value & 0x7F
        elif dev == 0o157:
            self.writes += 1
            self._write_data(value)
            self.fc = SUCCESSOR.get(self.fc, self.fc)
        return True

    def _write_data(self, value):
        fc = self.fc
        if fc in (PSWMA, PSRMA):
            self.addr_hi = value
            return
        if fc in (PSWMA + 1, PSRMA + 1):
            self.addr = two_word(self.addr_hi, value, False)
            return
        if fc == PSWMA + 2:
            self._mem_write(self.addr, value, self._bin())
            self.addr += 1
            return
        v = self._cur()
        if v is None:
            return
        self.advance()               # changes take effect from now on
        if fc < 8:
            v.set_word(fc, value)
        elif fc == PSINC:
            v.inc_w = value & 0xFF
        elif fc == PSMOD:
            v.mod_w = value & 0xFF
        elif fc == PSON:
            if value & 1 and not v.on & 1:
                v.pos = 0
                v.acc = 0
                v.out = self._sample(v.ba, self._bin())
            v.on = value & 3
            if not v.on & 1:
                v.out = 0
        elif fc in ENV_REGS:
            setattr(v, ENV_REGS[fc], value & 0xFFF)
        elif fc == PSADEVSM:
            v.master = value & 1

    def _mem_read(self, a, b=0):
        if b is None or not 0 <= a < self.bin_words:
            return 0
        return self.mem[b * self.bin_words + a]

    def _mem_write(self, a, value, b=0):
        if b is not None and 0 <= a < self.bin_words:
            self.mem[b * self.bin_words + a] = value

    def _sample(self, a, b):
        s = self._mem_read(a, b)
        return s - 0x10000 if s & 0x8000 else s

    # ---------------------------------------------------------------- time
    def tick(self, ns):
        self.time_ns += ns

    def advance(self):
        """Run the voices up to the current time."""
        t_end = self.time_ns
        voices = self.voice
        for i, v in enumerate(voices):     # odd voice of an even stereo master
            v.slave = bool(i & 1 and voices[i - 1].master)
        sounding = [(i, v) for i, v in enumerate(voices) if v.on & 1]
        moving = [v for v in voices if not v.settled()]
        if not sounding and not moving and self.samples is None:
            # nothing changes: skip the clocks
            self.rate_tick = t_end // F0_TICK_NS + 1
            self.env_tick = t_end // ENV_TICK_NS + 1
            self.done_ns = t_end
            return
        while True:
            t_rate = self.rate_tick * F0_TICK_NS
            t_env = self.env_tick * ENV_TICK_NS
            t_smp = (self.sample_k * 1_000_000_000 // self.sample_rate
                     if self.samples is not None else 1 << 62)
            t = min(t_rate, t_env, t_smp)
            if t > t_end:
                break
            if t == t_smp:
                self.samples.append(self._mix())
                self.sample_k += 1
            elif t == t_rate:
                self.rate_tick += 1
                for i, v in sounding:
                    if v.on & 1 and not v.slave:
                        self._rate(v, i // self.nvoices)
            else:
                self.env_tick += 1
                for v in voices:
                    if not v.settled():
                        v.env_tick()
        self.done_ns = t_end

    def _rate(self, v, b):
        inc = (v.inc_w & 0xFF) + 1
        mod = 256 - (v.mod_w & 0xFF)
        acc = v.acc + inc
        if acc < mod:
            v.acc = acc & 0x1FF
            return
        v.acc = (acc - mod) & 0x1FF       # a 9-bit accumulator [CHOICE]
        v.pos += v.pi
        if v.pos + v.wl >= 0:
            if v.on & 2 and v.ll != 0:
                v.pos += v.ll
                if v.pos < 0:
                    v.pos = 0
            else:
                v.on &= ~1
                v.out = 0
                return
        v.out = self._sample(v.ba + v.pos, b)

    def _mix(self):
        left = right = 0
        for i in range(len(self.voice)):
            v = self.voice[i]
            b = i // self.nvoices
            if i & 1 and self.voice[i - 1].master:
                m = self.voice[i - 1]
                s = self._sample(m.ba + m.pos + 1, b) if m.on & 1 else 0
            else:
                s = self._sample(v.ba + v.pos, b) if v.on & 1 else 0
            if s == 0 or v.eval == 0:
                continue
            e = s * v.eval
            left += e * v.lcur >> 24
            right += e * v.rcur >> 24
        if self.mono:
            return right, right
        return left, right

    # ---------------------------------------------------------- host side
    def sounding(self):
        """Channels (64 x bin + channel) whose on bit is set (after advancing
        to now)."""
        self.advance()
        n = self.nvoices
        return [64 * (i // n) + i % n for i in range(len(self.voice)) if self.voice[i].on & 1]

    @staticmethod
    def layout(total):
        """(bins, last_voices) for `total` poly voices, 4..128 in steps of 4:
        bins fill 32 voices each, in order; the last takes the rest (M16)."""
        if not 4 <= total <= 128 or total % 4:
            raise ValueError("poly voices: 4..128 in steps of 4")
        bins = (total + 31) // 32
        return bins, total - 32 * (bins - 1)
