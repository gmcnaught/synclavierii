#!/usr/bin/env python3
"""Tests for the synthesizer-side devices (sim/devices/synth.py, M2.2).

The programs follow NED's 05-BUTT:076-OLDI drivers and MONITOR's
CLEAR.KEYBOARD, with the register sequences seen in Release L ORK-LM.

Run:  python3 tests/sim/test_synth.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from sim.devices.synth import ControlVoltages, FMInterface, OriginalKeyboard  # noqa: E402


def scan(kb):
    """SCAN.ORK.FOR.NOTES: CREG 20, then 100+I / READ(DREG) for I = 0..5."""
    kb.write(0o131, 0o20)
    bits = []
    for i in range(6):
        kb.write(0o131, i | 0o100)
        bits.append(kb.read(0o130))
    kb.write(0o131, 6)
    kb.write(0o131, 0o20)
    kb.write(0o131, 0o260)
    return bits


def test_clavier_idle_and_negative_logic():
    kb = OriginalKeyboard()
    assert scan(kb) == [0o7777] * 5 + [1]
    kb.write(0o131, 0o105)                   # MONITOR: CHECK KEYBOARD TYPE
    assert kb.read(0o130) == 1               # original keyboard
    kb.press_key(48)                         # C4: octave 3, bit 0 (key = 12*I + K + 12)
    kb.press_key(72)                         # C6: octave 5's single key
    assert scan(kb) == [0o7777] * 3 + [0o7776, 0o7777, 0]
    kb.press_key(48, down=False)
    assert scan(kb)[3] == 0o7777
    for bad in (11, 73):
        try:
            kb.press_key(bad)
        except ValueError:
            continue
        raise AssertionError(bad)


def test_panel_buttons_lights_and_display():
    kb = OriginalKeyboard()
    kb.press_button(3 * 16 + 5)
    kb.write(0o131, 0o20)                    # SCAN.NEW.ORK.BUTTONS, panel 3
    kb.write(0o131, 3 | 0o10)
    kb.write(0o131, 3 | 0o110)
    assert kb.read(0o130) == 1 << 5
    kb.write(0o131, 3 | 0o10)                # address without read: lights
    kb.write(0o130, 0o100001)
    assert kb.lights[3] == 0o100001 and kb.light(3 * 16) and kb.light(3 * 16 + 15)
    for i, word in enumerate((0o100001, 0o34000, 0)):   # LOAD.ORK.DISPLAY
        kb.write(0o131, i)
        kb.write(0o130, word)
        kb.write(0o131, i | 0o40)            # EXW strobe
        kb.write(0o131, i)
    assert kb.display == [0o100001, 0o34000, 0]
    kb.write(0o131, 0o20)                    # LOAD.ORK.DISPLAY's end: 20, then
    kb.write(0o131, 0o260)                   # 260 (start A/D): no latch
    assert kb.display == [0o100001, 0o34000, 0]
    assert kb.d130_writes == []


def test_unknown_keyboard_reads():
    kb = OriginalKeyboard()
    kb.write(0o131, 3)                       # no read bit
    assert kb.read(0o130) is None            # strict: halt
    kb = OriginalKeyboard(strict=False)
    kb.write(0o131, 3)
    assert kb.read(0o130) == 0 and kb.unknown_reads == 1


def test_fm_channels_and_voice_detection():
    fm = FMInterface(voices=8)
    # 600-INIT / ORK-LM: probe one channel per 8-voice card
    top = 0
    for ch in range(0, 0o400, 0o20):
        fm.write(0o160, ch)
        if fm.read(0o160) & 1:
            top = ch + 0o20
    assert top == 16 and top // 2 == 8
    fm.write(0o160, 3)                       # odd channel: carrier
    fm.write(0o161, 0o13)                    # VOL
    fm.write(0o162, 200)
    assert fm.channels[(3, 0o13)] == 200 and fm.log[-1] == (0, 3, 0o13, 200)
    fm.write(0o160, 0o5407)                  # ORK-LM channel word: splice memory 13, channel 7
    fm.write(0o162, 1)
    assert fm.channel == 7 and fm.channels[(7, 0o13)] == 1 and fm.log[-1][1] == 0o5407
    assert FMInterface.ODD_FUNCTIONS[0o13] == "volume"


def test_fm_limit_status_and_wave_memory():
    fm = FMInterface(voices=8)
    fm.write(0o160, 1)
    for fn, v in ((0o10, 0o377), (0o11, 0o377), (0o12, 0)):   # silence: ELIM 0
        fm.write(0o161, fn)
        fm.write(0o162, v)
    assert fm.read(0o160) & 1 == 0           # function 12 selected, counter at 0 = limit
    fm.write(0o161, 0)
    assert fm.read(0o160) & 1 == 1           # other function: channel exists
    fm.write(0o161, 0o12)
    fm.write(0o162, 250)                     # attack to 250 at full rate
    assert fm.read(0o160) & 1 == 1
    fm.tick(1_000_000)                       # 1 ms = 192 steps
    assert fm.read(0o160) & 1 == 1 and fm.interp[1].value == 192
    fm.tick(1_000_000)
    assert fm.read(0o160) & 1 == 0 and fm.interp[1].value == 250
    fm.write(0o160, 0o20)                    # absent channel
    assert fm.read(0o160) & 1 == 0
    # wave memory: ZMA, TIM = 32 + n, then successive MEM bytes
    fm.write(0o160, 0o17)
    for fn, v in ((6, 0), (4, 0o44)):
        fm.write(0o161, fn)
        fm.write(0o162, v)
    fm.write(0o161, 7)
    for i in range(257):
        fm.write(0o162, i)
    assert fm.wave[4][:3] == bytes([0, 1, 2])  # byte 0 rewritten by the 257th write (256 & 255)
    assert fm.wave[4][255] == 255 and fm.mar[0o17] == 1


def test_switches_clock_and_adc():
    fm = FMInterface(voices=0)
    fm.write(0o160, 0)
    fm.switches = 0o14                       # switches 0 and 1 (bits 2, 3)
    fm.ext_clock_in = True
    assert fm.read(0o160) == 0o16            # READ(SW) & 374 = 14; & 2 = clock
    fm.adc[:5] = [10, 20, 30, 40, 50]
    got = []
    for ch in (0, 1, 4, 3, 2):               # SCAN.ORK.ANALOG.INPUTS order
        fm.write(0o163, 2 + (ch << 2))
        got.append(fm.read(0o163))
    fm.write(0o163, 3)                       # start next conversion
    assert got == [10, 20, 50, 40, 30]
    fm.write(0o163, 1)                       # toggle external clock out
    fm.write(0o163, 1)
    fm.write(0o163, 1)
    assert fm.ext_clock_out


def test_button_table():
    from sim.devices.synth import ORK_BUTTONS, button_number
    assert len(ORK_BUTTONS) == 128 and len(set(ORK_BUTTONS)) == 128
    assert button_number("bank.0") == 96 and button_number("timb.0") == 104
    assert button_number("start") == 32 and button_number("17") == 17


def test_control_voltages():
    cv = ControlVoltages()
    for sel, v in ((0, 250), (1, 0), (2, 250), (3, 4224)):   # 390-VOLT
        cv.write(0o164, sel)
        cv.write(0o165, v)
    assert cv.dac == {0: 250, 1: 0, 2: 250, 3: 4224}
    assert cv.read(0o164) is None


# -- velocity/pressure keyboard (docs/devices/d130-velocity-keyboard.md) ----

def vpk_request(kb, req):
    """PULSE_EXWR (GLOBLITS:99) in mode 1: CREG 1, DREG = req, 41, 1, 101."""
    kb.write(0o131, 1)
    kb.write(0o130, req)
    for c in (0o41, 1, 0o101):
        kb.write(0o131, c)
    v = kb.read(0o130)
    kb.write(0o131, 1)
    return v


def vpk_kcr(kb):
    """144-TIM3: DREG 0, CREG 0, 40, 0, 100; read; CREG 0."""
    kb.write(0o130, 0)
    for c in (0, 0o40, 0, 0o100):
        kb.write(0o131, c)
    v = kb.read(0o130)
    kb.write(0o131, 0)
    return v


def vpk_write(kb, mode, addr, data):
    """Mode 2 (display) / 3 (lights): CREG m, DREG addr<<8|data, m+40, m."""
    kb.write(0o131, mode)
    kb.write(0o130, addr << 8 | data)
    kb.write(0o131, mode + 0o40)
    kb.write(0o131, mode)


def test_vpk_detection():
    from sim.devices.synth import VelocityKeyboard
    kb = VelocityKeyboard()
    kb.write(0o131, 0o105)                   # KEYBOARD.CHECK: 1 would be an ORK
    assert kb.read(0o130) != 1
    kb.write(0o131, 0o005)
    assert vpk_kcr(kb) == 0o077777           # powered, nothing changed
    assert vpk_kcr(kb) == 0o077777


def test_vpk_keys_velocity_pressure():
    from sim.devices.synth import VELOCITY_TTIME, VelocityKeyboard, sync_ttime_map
    tt = sync_ttime_map(3)
    assert [tt[t] for t in (20, 21, 30, 60, 100, 130)] == [225, 212, 127, 30, 7, 3]
    assert VELOCITY_TTIME[127] == 20 and tt[VELOCITY_TTIME[1]] == 3
    kb = VelocityKeyboard()
    kb.press_midi_note(60, velocity=127)     # middle C: NED key 36, index 27
    kcr = vpk_kcr(kb)
    assert kcr == 0o077777 & ~(1 << 1)       # superoctave 1 changed (negative logic)
    bits = vpk_request(kb, 0o417 | 1 << 4)   # activity word, 1 = down
    assert bits == 1 << (27 - 16)
    assert vpk_kcr(kb) == 0o077777           # reported: no further change
    assert vpk_request(kb, 0o000 | 27) & 0o1777 == 20      # transit time
    kb.set_pressure(36, 90)
    assert vpk_request(kb, 0o200 | 27) == 90
    kb.press_midi_note(60, down=False)
    assert vpk_kcr(kb) & 2 == 0
    assert vpk_request(kb, 0o417 | 1 << 4) == 0


def test_vpk_analog_and_switches():
    from sim.devices.synth import VelocityKeyboard
    kb = VelocityKeyboard()
    assert [vpk_request(kb, 0o200 | n) for n in range(88, 96)] == [128, 0, 255, 255, 128, 0, 0, 255]
    kb.set_analog("mod wheel", 200)
    kb.switches = 0o4                        # glide
    assert vpk_request(kb, 0o200 | 93) == 200
    assert vpk_request(kb, 0o200 | 89) == 0o4 << 8


def test_vpk_buttons_lights_display():
    from sim.devices.synth import VelocityKeyboard, vpk_button_number
    kb = VelocityKeyboard()
    assert vpk_button_number("timb.0") == 104 and vpk_button_number("stop") == 33
    kb.press_button(vpk_button_number("stop"))           # bank 8, bit 1
    assert vpk_request(kb, 0o600) == 1 << 7              # SAR: bank 8
    assert vpk_request(kb, 0o600 | 8) == 2
    vpk_write(kb, 3, kb.light_address(104), 1)
    vpk_write(kb, 3, kb.light_address(33), 2)
    assert kb.light(104) == 1 and kb.light(33) == 2 and kb.light(0) == 0
    for i, ch in enumerate(b" SYNCLAVIER"):
        vpk_write(kb, 2, 1 + i, ch)
    vpk_write(kb, 2, 32, 1)
    assert kb.display_text()[0].startswith("  SYNCLAVIER") and kb.dp[32] == 1


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print("%d tests OK" % len(tests))
