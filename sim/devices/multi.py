"""D32/D33 multichannel distributor ("Xpand system", 8 or 16 outputs, M19).

Register map and evidence: docs/devices/d32-multichannel.md.

  D32  write: subsystem select. 0o20 = the distributor's presence port,
       0o21 = its routing port (SYNLITS:GLOBLITS "DEVICE 32 DIGITAL IO
       MULTIPLEXOR"; 600-INIT:953, 1008). read: 0 [CHOICE: SYN-5.3 never
       reads it].
  D33  write (0o21 selected): bits 7-0 input, bits 13-8 output (0-based),
       bit 14 on: the input is switched to that output (on) or switched off
       (off: the output field does not matter) [OBS 600-INIT:1011, 1025,
       1087, 1108; 144-TIM3:856-859; 301-SUB1:618-621]. Each input feeds at
       most one output [INF: "disconnect" writes give only the input].
       Bit 15 is ignored [CHOICE]. Writes with another subsystem selected
       are ignored.
       read: bit 0 = 1 with 0o20 selected (the distributor is there,
       600-INIT:955); with 0o21 selected, bit 0 = signal present: the input
       of the last D33 write is switched to an output that exists (< the
       card's outputs) and the voice side wired to that input is sounding
       (`live`) [CHOICE: a level detector on the addressed output; the probe
       connects one input at a time, 600-INIT:1086-1116]. Other bits 0.

Wiring of the 256 inputs [CHOICE; the probe constrains only the low two
bits: an FM voice v is looked for at inputs 4i + ((v + 1) & 3)
(600-INIT:1086), a poly channel c at 4i + (c & 3) (600-INIT:1342)]:
input m = 4k + r,
  k  0-15: FM voice 4 (k >> 1) + ((r + 3) & 3), side k & 1 (0 left, 1 right)
  k 16-63: poly voice p = 4 ((k - 16) >> 1) + r (bin p >> 5, channel
           p & 31), side (k - 16) & 1; poly voices from 96 up have no input
           (32 FM + 96 poly voices x 2 sides = 256 inputs, a 9600's full
           complement [INF]).
Mono voice cards have no left DAC: their left inputs never sound.

`live` [CHOICE: from registers, not from the signal, so it does not depend
on time]: an FM voice side sounds when its volume (odd channel FC 13) and
envelope limit (odd channel FC 12) are non-zero and its pan (even channel
FC 13 & 0o374) gives that side more than 4/256 (left: pan != 252, right:
pan != 0, the probe's "all left" 0 and "all right" 252, 600-INIT:1050,
1126); a poly voice side when its envelope limit (FC 36) and that side's
destination volume (FC 41 right, FC 43 left) are non-zero.

Audio: `pair` 0 = the stereo mix (unchanged); n = 1..outputs/2 = output pair
2n - 1, 2n (1-based, as SYN-5.3 shows them): each voice side contributes to
the pair's left or right if its input is switched to output 2n - 2 or
2n - 1 (0-based). `fm_tags(v)` / `poly_tags(p)` give (left, right) outputs
or None for the mix code in sim/voice.py and sim/devices/poly.py.
"""
from ..bus import Device

SEL_PRESENT = 0o20
SEL_PORT = 0o21
ON = 0x4000
INPUTS = 256
FM_VOICES = 32           # voices with inputs
POLY_VOICES = 96


def wiring(m):
    """Input m -> ("fm", voice, side) or ("poly", voice, side) or None."""
    k, r = m >> 2, m & 3
    if k < 16:
        return ("fm", 4 * (k >> 1) + ((r + 3) & 3), k & 1)
    k -= 16
    return ("poly", 4 * (k >> 1) + r, k & 1)


def fm_input(v, side):
    """The input wired to FM voice v's side (0 left, 1 right)."""
    return 4 * (2 * (v >> 2) + side) + ((v + 1) & 3)


def poly_input(p, side):
    """The input wired to poly voice p (32 x bin + channel), or None."""
    if p >= POLY_VOICES:
        return None
    return 4 * (16 + 2 * (p >> 2) + side) + (p & 3)


class Distributor(Device):
    numbers = (0o32, 0o33)

    def __init__(self, outputs=16, fm=None, poly=None, pair=0):
        if outputs not in (8, 16):
            raise ValueError("outputs: 8 or 16")
        self.outputs = outputs
        self.fm = fm             # devices.synth.FMInterface (registers)
        self.poly = poly         # devices.poly.PolySynth
        self.pair = pair         # 0: stereo mix; n: outputs 2n-1, 2n
        self.select = 0
        self.last = 0            # input of the last D33 write
        self.route = [None] * INPUTS   # input -> output (0-based) or None
        self.writes = []         # (select, value) of D33 writes, for tests

    # ------------------------------------------------------------ registers
    def read(self, dev):
        if dev == 0o33:
            if self.select == SEL_PRESENT:
                return 1
            if self.select == SEL_PORT:
                return int(self.route[self.last] is not None and self.live(self.last))
        return 0

    def write(self, dev, value):
        value &= 0xFFFF
        if dev == 0o32:
            self.select = value & 0xFF
        elif self.select == SEL_PORT:
            if len(self.writes) < 100_000:
                self.writes.append(value)
            m, out = value & 0xFF, (value >> 8) & 0o77
            self.last = m
            self.route[m] = out if value & ON and out < self.outputs else None
        return True

    # ------------------------------------------------------------- inputs
    def live(self, m):
        kind, v, side = wiring(m)
        if kind == "fm":
            fm = self.fm
            if fm is None or v >= fm.voices:
                return False
            vol = fm.channels.get((2 * v + 1, 0o13), 0) & 0o377
            lim = fm.channels.get((2 * v + 1, 0o12), 0) & 0o377
            pan = fm.channels.get((2 * v, 0o13), 0) & 0o374
            return bool(vol and lim and (pan != 0o374 if side == 0 else pan != 0))
        voice = self.poly_voice(v)
        if voice is None or (side == 0 and self.poly.mono):
            return False
        return bool(voice.elim and (voice.ldest if side == 0 else voice.rdest))

    def poly_voice(self, p):
        """PolyVoice of poly voice p (32 x bin + channel), None if absent."""
        poly = self.poly
        if poly is None or not hasattr(poly, "bin_voices"):
            return None
        b, c = p >> 5, p & 31
        if b >= poly.nbins or c >= poly.bin_voices[b]:
            return None
        return poly.voice[b * poly.nvoices + c]

    # --------------------------------------------------------------- audio
    def fm_tags(self, v):
        return self.route[fm_input(v, 0)], self.route[fm_input(v, 1)]

    def poly_tags(self, p):
        """p = 32 x bin + channel."""
        ml, mr = poly_input(p, 0), poly_input(p, 1)
        if ml is None:
            return None, None
        return self.route[ml], self.route[mr]

    def assignments(self):
        """{input: output} of the inputs switched on."""
        return {m: o for m, o in enumerate(self.route) if o is not None}


def route_pair(left, right, tags, pair, mono=False):
    """(left, right) of one voice for the selected output pair (pair >= 1):
    its left and right sides go where their inputs are switched."""
    tl, tr = tags
    a, b = 2 * pair - 2, 2 * pair - 1
    if mono:
        left, tl = 0, None
    out_l = (left if tl == a else 0) + (right if tr == a else 0)
    out_r = (left if tl == b else 0) + (right if tr == b else 0)
    return out_l, out_r
