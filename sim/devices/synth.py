"""Synthesizer-side devices of the original Synclavier II (M2.2).

Evidence (NED source, MIT, jbemond/Software; later releases, checked
against Release L ORK-LM's logged accesses -- docs/devices/):
  * SYNLITS:FCODLITS: CHA = D160 "WRITE CHANNEL #", FUN = D161 "WRITE
    FUNCTION CODE", DAT = D162 "WRITE DATA HERE"; commented out: SW = D160
    "SWITCH REGISTER - OLD PANEL", AD = D163 "AD CONVERTER - OLD PANEL".
    SOME-ORK: "inc.fm: set to 1 if d160-d163 are avail".
  * SYNRSOU 05-BUTT:076-OLDI ("low level scanning routines for original
    Synclavier II panel", 1986): the D130/D131 protocol below, the D160
    switch register (READ(SW) & 374, six switches from bit 2) and the D163
    A/D converter (WRITE(AD) = 2 + SHL(channel, 2); READ(AD); WRITE(AD) = 3
    starts the next conversion; channels 0 knob, 1 ribbon, 2 pitch wheel,
    3 pedal 1, 4 pedal 2).
  * 04-SEQ:162-SEQ2, 10-INT:144-TIM4: "CLOCK.DATA = READ("160") & 2"
    (external clock input); WRITE("163") = 1 "TOGGLE EXT CLOCK TO GENERATE
    15 MS PULSE".
  * 06-MAIN:390-VOLT, 308-STR8, 10-INT:144-TIM3: WRITE(D164) = n selects a
    DAC (0 LP filter CV, 1 HP CV, 2 BP CV, 3 Q CV, 4 keyboard pitch,
    5 keyboard gate, 6 keyboard trigger), WRITE(D165) = value.
  * FCODLITS (9/15/86): "A CHANNEL NUMBER (0-63 FOR QUAD SYNTH SYSTEMS) IS
    WRITTEN TO DEVICE 160. A FUNCTION CODE IS THEN WRITTEN TO DEVICE 161.
    THERE ARE 16 FUNCTION CODES ... AN 8-BIT DATA WORD IS THEN WRITTEN TO
    DEVICE 162". Even channel = modulator, odd = carrier of one voice.
    Functions: 0 increment, 1 note number, 2 octave number, 4 timbre bits,
    6 zero memory address register, 7 wave memory; even channels: 10 index
    interpolation divisor, 11 index adder, 12 index limit, 13 index shift
    count; odd channels: 10 envelope divisor, 11 envelope adder, 12
    envelope limit, 13 volume.
  * 08-INIT:600-INIT counts voices with "WRITE(CHA) = SHL(IVOICE,1); IF
    READ(CHA) THEN /* CHANNEL EXISTS */"; Release L ORK-LM does the same
    ("R0 TO D160; D160 TO LOA0; IM(1) TO TAND0", 107522, 112341): D160
    read bit 0 = the selected channel exists.
  * MONCAT:MON CLEAR.KEYBOARD: WRITE("131") = "105"; IF READ("130") = 1
    THEN /* OLD KEYBOARD */ -- that is a read of clavier octave 5.

D130 (DREG) / D131 (CREG), original keyboard and button panel:
    CREG = 100 + I (I = 0..5)   D130 reads clavier octave I: 12 key bits,
                                0 = key down (negative logic; idle 7777,
                                octave 5 has one key: idle 1)
    CREG = 10 + I, 110 + I      D130 reads panel I (0..7): 16 buttons,
                                1 = pressed
    CREG = 10 + I (no read bit) D130 write sets panel I's 16 lights
    CREG = I (0..2), DREG write, CREG = I + 40, CREG = I
                                latch a word into the 4-digit display
    CREG = 20, 260              stop / start the external write and A/D
                                cycle (no visible effect modelled)
Key number = 12 * octave + bit + 12 (12..72, C1..C6), as SCAN.ORK.FOR.NOTES.
"""
from ..bus import NO_SYN, Device

READ_BIT = 0o100
PANEL_BIT = 0o10
STROBE_BIT = 0o40
OCTAVE_KEYS = (12, 12, 12, 12, 12, 1)
LOWEST_KEY = 12


class OriginalKeyboard(Device):
    """D130/D131: original Synclavier II clavier, button panel, display."""
    numbers = (0o130, 0o131)

    def __init__(self, strict=True):
        self.strict = strict
        self.unknown_reads = 0
        self.creg = 0
        self.dreg = 0
        self.clavier = [(1 << n) - 1 for n in OCTAVE_KEYS]   # negative logic
        self.buttons = [0] * 8
        self.lights = [0] * 8
        self.display = [0] * 3
        self.d130_writes = []           # (creg, value) for anything unrecognised

    # -- host side -------------------------------------------------------
    def press_key(self, key, down=True):
        """key: 12..72 (C1..C6)."""
        octave, bit = divmod(key - LOWEST_KEY, 12)
        if not (0 <= octave < 6 and bit < OCTAVE_KEYS[octave]):
            raise ValueError("key %d outside C1..C6 (12..72)" % key)
        if down:
            self.clavier[octave] &= ~(1 << bit)
        else:
            self.clavier[octave] |= 1 << bit

    def press_button(self, pbn, down=True):
        """pbn: physical button number 0..127 (panel * 16 + bit)."""
        panel, bit = divmod(pbn, 16)
        if down:
            self.buttons[panel] |= 1 << bit
        else:
            self.buttons[panel] &= ~(1 << bit)

    def light(self, pbn):
        panel, bit = divmod(pbn, 16)
        return bool(self.lights[panel] >> bit & 1)

    # -- registers --------------------------------------------------------
    def read(self, dev):
        if dev == 0o130 and self.creg & READ_BIT:
            i = self.creg & 7
            if self.creg & PANEL_BIT:
                return self.buttons[i]
            if i < 6:
                return self.clavier[i]
        if self.strict:
            return NO_SYN
        self.unknown_reads += 1
        return 0

    def write(self, dev, value):
        if dev == 0o131:
            old, self.creg = self.creg, value
            i = value & 7
            # display latch: strobe bit set on address 0..2 (EXW pulse)
            if value & STROBE_BIT and not old & STROBE_BIT and i < 3 \
                    and not value & (PANEL_BIT | READ_BIT):
                self.display[i] = self.dreg
            return True
        self.dreg = value
        c = self.creg
        if c & PANEL_BIT and not c & READ_BIT and not c & 0o20:
            self.lights[c & 7] = value
        elif not c & (PANEL_BIT | READ_BIT | 0o20) and (c & 7) < 3:
            pass                        # display word, latched by the strobe
        else:
            self.d130_writes.append((c, value))
        return True


class FMInterface(Device):
    """D160-D163: FM voice interface plus the old panel's switch register,
    external clock and A/D converter."""
    numbers = (0o160, 0o161, 0o162, 0o163)

    ADC_CHANNELS = ("knob", "ribbon", "pitch wheel", "pedal 1", "pedal 2")

    FUNCTIONS = {0: "increment", 1: "note number", 2: "octave number", 4: "timbre bits",
                 6: "zero MAR", 7: "wave memory"}
    EVEN_FUNCTIONS = {0o10: "index divisor", 0o11: "index adder", 0o12: "index limit",
                      0o13: "index shift count"}
    ODD_FUNCTIONS = {0o10: "envelope divisor", 0o11: "envelope adder", 0o12: "envelope limit",
                     0o13: "volume"}

    def __init__(self, voices=8, log_len=100_000, strict=True):
        # CHOICE: 8 FM voices installed (16 channels); configurable
        self.voices = voices
        self.strict = strict
        self.unknown_reads = 0
        self.channel = 0
        self.function = 0
        self.writes = 0
        self.log = []                   # (channel, function, value) of D162 writes
        self.log_len = log_len
        self.channels = {}              # (channel, function) -> last value
        self.switches = 0               # six switches, bits 2..7 of D160
        self.ext_clock_in = False       # bit 1 of D160
        self.ext_clock_out = False      # toggled by WRITE(D163) = 1
        self.adc = [0] * 8              # values returned by D163 per channel
        self.adc_select = 0

    def read(self, dev):
        if dev == 0o160:
            exists = 1 if self.channel < 2 * self.voices else 0
            return (self.switches & 0o374) | (2 if self.ext_clock_in else 0) | exists
        if dev == 0o163:
            return self.adc[self.adc_select]
        if self.strict:
            return NO_SYN
        self.unknown_reads += 1
        return 0

    def write(self, dev, value):
        self.writes += 1
        if dev == 0o160:
            self.channel = value
        elif dev == 0o161:
            self.function = value
        elif dev == 0o162:
            if len(self.log) < self.log_len:
                self.log.append((self.channel, self.function, value))
            self.channels[(self.channel, self.function)] = value
        elif value == 1:
            self.ext_clock_out = not self.ext_clock_out
        elif value & 3 == 2:
            self.adc_select = (value >> 2) & 7
        # value 3: start the next conversion (instant here)
        return True


class ControlVoltages(Device):
    """D164/D165: keyboard filter/trigger board DACs (option o#d164)."""
    numbers = (0o164, 0o165)
    NAMES = ("LP filter", "HP filter", "BP filter", "Q", "pitch", "gate", "trigger")

    def __init__(self):
        self.select = 0
        self.dac = {}

    def read(self, dev):
        return NO_SYN

    def write(self, dev, value):
        if dev == 0o164:
            self.select = value
        else:
            self.dac[self.select] = value
        return True
