#!/usr/bin/env python3
"""HDL CPU (hdl/able_cpu.sv) in lockstep with the Python simulator (M4.3).

Needs Verilator (skipped otherwise). Random programs with random device
data and interrupts; with SYNCLAVIER_RELEASE_L set, also MONITOR's boot
and CATALOG.

Run:  python3 tests/hdl/test_lockstep.py
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from sim.lockstep import check, expected_wav, random_cpu, record  # noqa: E402

HAVE_VERILATOR = shutil.which("verilator") is not None


def _check(cpu, n, **kw):
    with tempfile.NamedTemporaryFile(suffix=".trace", delete=False) as f:
        path = f.name
    try:
        got = record(cpu, path, n, **kw)
        ok, text = check(path)
    finally:
        os.unlink(path)
    assert ok, text
    return got


def test_random_programs():
    if not HAVE_VERILATOR:
        print("  skip test_random_programs (verilator not found)")
        return
    for seed in range(60):
        assert _check(random_cpu(1000 + seed), 3000) == 3000   # Model B: ADC/SBB are no-ops


DEVICE_PROGRAM = """
        PCI TO R16
        DATA ENTRY
        PCI TO R5           ; input buffer for the interrupt handler
        DATA 4000
        IM(-10) TO D1       ; R17 is the PC, interrupts on
        PCI TO R4
        DATA 2000           ; 1024 passes
LOOP:   R4 TO D5            ; multiply: D5:D4 = R4 * 1234 + 0
        PCI TO D6
        DATA 1234
        D4 TO R0
        D5 TO R1
        R1 TO D5            ; divide (R4:R1) / 17: quotients above 16 bits
        R4 TO D4
        IM(17) TO D7
        D5 TO R2
        D4 TO R3
        R4 TO D60           ; external memory: sector R4 (1024 is beyond the end)
        PCI TO D61
        DATA 370
        R2 TO D63           ; 12 words across the sector boundary
        R3 TO D63
        R4 TO D63
        R0 TO D63
        R1 TO D63
        R2 TO D63
        R3 TO D63
        R4 TO D63
        R0 TO D63
        R1 TO D63
        R2 TO D63
        R3 TO D63
        R4 TO D60
        PCI TO D61
        DATA 376
        D63 TO R0           ; read back across the sector boundary
        D63 TO R1
        D63 TO R2
        D62 TO R2
        D60 TO R3           ; sector R4 + 1
        D61 TO R6
        R4 TO D50           ; send a character without waiting
        R4 TO R3            ; count down (arithmetic only on R0-R3)
        IM(1) TO SUB3
        R3 TO R4            ; register load keeps the flags
        PCI TO ATNZ         ; absolute transfer (LOOP is beyond relative range)
        DATA LOOP
        D50 TO R0           ; held until input arrives
        D50 TO R1
        D6 TO R0            ; D6 cannot be read: no SYN, halt
RETURN: IM(-10) TO D1
ENTRY:  D3 TO R7
        IM(0) TO D3         ; acknowledge the clock
        D51 TO R0
        IM(2) TO AND0
        RE(TTI) TO RTNZ
        IM(0) TO D51        ; acknowledge transmit
        RE(RETURN) TO RTRA
TTI:    D50 TO MR5I
        RE(RETURN) TO RTRA
"""


def test_system_devices_program():
    """The HDL devices (D3, D4567, D50/D51, D60-D63) against Python on a
    program that uses them all with interrupts, a held read and a halt."""
    if not HAVE_VERILATOR:
        print("  skip test_system_devices_program (verilator not found)")
        return
    from sim.asm import assemble
    from sim.system import make_system
    cpu = make_system()
    words, _ = assemble(DEVICE_PROGRAM)
    cpu.load(words)
    fed = []

    def on_wait(cpu):           # the handler may take characters too: feed again
        if len(fed) == 3:
            return False
        fed.append(1)
        cpu.terminal.feed("xyz")
        return True
    with tempfile.NamedTemporaryFile(suffix=".trace", delete=False) as f:
        path = f.name
    try:
        n = record(cpu, path, 200_000, max_wait=4000, on_wait=on_wait)   # > 1 character time
        ok, text = check(path, top="system")
    finally:
        os.unlink(path)
    assert ok, text
    assert cpu.halted and cpu.halted.device == 0o6, cpu.halted
    assert n > 30_000 and cpu.rtc.ticks >= 5 and fed


FLOPPY_PROGRAM = """
        IM(0) TO D104       ; drive 0, side 0
        IM(1) TO D100       ; restore
        WAITBUSY
        IM(3) TO D103       ; seek to cylinder 3
        PCI TO D100
        DATA 21
        WAITBUSY
        IM(2) TO D102       ; write sector 2 from 10000
        PCI TO D100
        DATA 240
        PCI TO R4
        DATA 10000
        PCI TO R5
        DATA 400
WL:     D100 TO R0          ; wait for DRQ
        IM(2) TO TAND0
        RE(WL) TO RTZE
        MR4 TO D103         ; low byte first
        MR4I TO R0
        IM(0) TO BSOR0      ; then the high byte
        R0 TO D103
        R5 TO R3
        IM(1) TO SUB3
        R3 TO R5
        RE(WL) TO RTNZ
        WAITBUSY
        IM(2) TO D102       ; read it back into 12000
        PCI TO D100
        DATA 210
        PCI TO R4
        DATA 12000
        PCI TO R5
        DATA 400
RL:     D100 TO R0
        IM(2) TO TAND0
        RE(RL) TO RTZE
        D103 TO R2
        D103 TO R1
        IM(0) TO BSOR1
        R2 TO OR1
        R1 TO MR4I
        R5 TO R3
        IM(1) TO SUB3
        R3 TO R5
        RE(RL) TO RTNZ
        WAITBUSY
        IM(11) TO D102      ; sector 9: record not found
        PCI TO D100
        DATA 210
        WAITBUSY
        D100 TO R6
        IM(1) TO D104       ; drive 1 (write protected): write
        PCI TO D100
        DATA 240
        D100 TO R7
        IM(0) TO D104
        PCI TO D100         ; step in, then step out with track update
        DATA 101
        WAITBUSY
        PCI TO D100
        DATA 161
        WAITBUSY
        D101 TO R10
        PCI TO D100         ; force interrupt: index pulses in the status
        DATA 320
        PCI TO R5
        DATA 2000
IX:     D100 TO R11
        R5 TO R3
        IM(1) TO SUB3
        R3 TO R5
        RE(IX) TO RTNZ
        D104 TO R0          ; D100 has no drive ID: no SYN, halt
"""


def _expand_waits(src):
    """WAITBUSY -> an inline loop polling D100 until not busy."""
    out, k = [], 0
    for line in src.splitlines():
        if line.strip() == "WAITBUSY":
            k += 1
            out += ["WB%d:   D100 TO R0" % k, "        IM(1) TO TAND0", "        RE(WB%d) TO RTNZ" % k]
        else:
            out.append(line)
    return "\n".join(out)


def test_system_floppy_program():
    """The HDL floppy controller against Python: restore, seek, write a
    sector, read it back, record not found, write protect, steps, index
    pulses, and the D104 read that has no SYN."""
    if not HAVE_VERILATOR:
        print("  skip test_system_floppy_program (verilator not found)")
        return
    import random as _random
    from sim.asm import assemble
    from sim.devices.floppy import Media
    from sim.system import make_system
    rng = _random.Random(5)
    cpu = make_system(floppy=True)
    cpu.floppy.insert(0, Media([rng.randrange(0x10000) for _ in range(40 * 256)]))
    cpu.floppy.insert(1, Media([0] * (40 * 256), protected=True))
    words, labels = assemble(_expand_waits(FLOPPY_PROGRAM))
    cpu.load(words)
    data = [rng.randrange(0x10000) for _ in range(256)]
    cpu.load(data, 0o10000)
    with tempfile.NamedTemporaryFile(suffix=".trace", delete=False) as f:
        path = f.name
    try:
        n = record(cpu, path, 400_000)
        ok, text = check(path, top="system")
    finally:
        os.unlink(path)
    assert ok, text
    assert cpu.halted and cpu.halted.device == 0o104, cpu.halted
    assert cpu.mem[0o12000:0o12400] == data            # written and read back
    lsn = 3 * 5 + 2 - 1
    assert cpu.floppy.media[0].words[lsn * 256:(lsn + 1) * 256] == data
    assert cpu.r[6] & 0o20 and cpu.r[7] & 0o100      # RNF, write protect
    assert n > 10_000


SYNTH_PROGRAM = """
        IM(3) TO D160       ; channel 3 (carrier of voice 1)
        IM(10) TO D161      ; divisor 370 (8 clocks per pulse)
        PCI TO D162
        DATA 370
        IM(11) TO D161      ; adder 177 (half a step per pulse)
        PCI TO D162
        DATA 177
        IM(12) TO D161      ; limit 200: ramp up
        PCI TO D162
        DATA 200
        IM(0) TO R4
UP:     IM(1) TO ADD0       ; count polls until the limit is reached
        D160 TO R1
        IM(1) TO TAND1
        RE(UP) TO RTNZ
        R0 TO R4
        IM(0) TO D162       ; limit 0: ramp down, then poll again
        IM(0) TO R0
DOWN:   IM(1) TO ADD0
        D160 TO R1
        IM(1) TO TAND1
        RE(DOWN) TO RTNZ
        IM(4) TO D161       ; wave memory 9 through channel 20 (absent: ignored)
        PCI TO D160
        DATA 20
        PCI TO D162
        DATA 51
        IM(6) TO D161
        IM(0) TO D162
        IM(7) TO D161
        IM(5) TO D162
        PCI TO D160         ; channel 20 (16): beyond 8 voices
        DATA 20
        D160 TO R5          ; bit 0 clear
        IM(5) TO D160       ; wave memory 9 through channel 5
        IM(4) TO D161
        PCI TO D162
        DATA 51
        IM(6) TO D161
        IM(0) TO D162
        IM(7) TO D161
        IM(5) TO D162
        IM(6) TO D162
        IM(12) TO D163      ; A/D channel 2
        D163 TO R6
        IM(1) TO D163       ; toggle the external clock
        PCI TO D131         ; keyboard: wait for a key in octave 3
        DATA 103
KEY:    D130 TO R2
        IM(-1) TO XOR2
        RE(KEY) TO RTZE
        PCI TO D131         ; panel 6 buttons
        DATA 116
        D130 TO R3
        PCI TO D131         ; panel 2 lights
        DATA 12
        R2 TO D130
        IM(1) TO D131       ; display word 1: data, then the strobe
        R0 TO D130
        PCI TO D131
        DATA 41
        IM(1) TO D131
        D161 TO R7          ; no SYN (strict): halt
"""


def test_system_synth_devices_program():
    """D130/D131 and D160-D165 in HDL against Python: interpolator ramps
    polled through D160 bit 0, wave memory loads, A/D and clock, keys and
    buttons from the host, lights, display, and a D161 read that halts."""
    if not HAVE_VERILATOR:
        print("  skip test_system_synth_devices_program (verilator not found)")
        return
    from sim.asm import assemble
    from sim.devices.synth import button_number
    from sim.system import make_system
    cpu = make_system(synth=True)
    words, _ = assemble(SYNTH_PROGRAM)
    cpu.load(words)
    kb = cpu.keyboard
    acts = [(3_000_000, lambda c: kb.press_button(button_number("timb.3"))),
            (6_000_000, lambda c: kb.press_key(52))]
    with tempfile.NamedTemporaryFile(suffix=".trace", delete=False) as f:
        path = f.name
    try:
        n = record(cpu, path, 400_000, actions=acts)
        ok, text = check(path, top="system")
    finally:
        os.unlink(path)
    assert ok, text
    assert cpu.halted and cpu.halted.device == 0o161, cpu.halted
    assert cpu.r[4] > 20 and cpu.r[0] > 20                  # both ramps took many polls
    assert cpu.fm.wave[9][:2] == bytearray([5, 6]) and cpu.r[3] == 1 << 11
    assert kb.lights[2] == cpu.r[2] and kb.display[1] == cpu.r[0] and cpu.r[5] == 0 and n > 100


VOICE_PROGRAM = """
        IM(17) TO D160      ; load wave memory 4 through channel 17 (15)
        IM(4) TO D161
        PCI TO D162
        DATA 44
        IM(6) TO D161
        IM(0) TO D162
        IM(7) TO D161
        IM(0) TO R0
RAMP:   R0 TO D162          ; 0, 3, ... 252 (85 points; the rest stay 0)
        IM(3) TO ADD0
        R0 TO R3
        PCI TO TSUB3
        DATA 375
        RE(RAMP) TO RTNC
        IM(1) TO D160       ; voice 0 carrier: pitch, wave 4, envelope, VOL
        IM(2) TO D161
        IM(1) TO D162       ; ONU 1
        IM(1) TO D161
        PCI TO D162         ; NNU
        DATA 300
        IM(0) TO D161
        PCI TO D162         ; INC
        DATA 176
        IM(4) TO D161
        PCI TO D162
        DATA 44
        IM(13) TO D161
        PCI TO D162         ; VOL
        DATA 360
        IM(10) TO D161
        PCI TO D162
        DATA 374
        IM(11) TO D161
        PCI TO D162
        DATA 377
        IM(12) TO D161
        PCI TO D162         ; envelope to 240
        DATA 360
        IM(0) TO D160       ; modulator: ratio 2, pan right of centre, shift 2
        IM(2) TO D161
        IM(2) TO D162
        IM(1) TO D161
        PCI TO D162
        DATA 300
        IM(0) TO D161
        PCI TO D162
        DATA 176
        IM(13) TO D161
        PCI TO D162
        DATA 302
        IM(10) TO D161
        PCI TO D162
        DATA 360
        IM(11) TO D161
        PCI TO D162
        DATA 100
        IM(12) TO D161
        PCI TO D162         ; index ramps to 200
        DATA 310
        IM(7) TO D160       ; voice 3: other pitch, all left, memory 4, no envelope set
        IM(2) TO D161
        IM(2) TO D162
        IM(1) TO D161
        PCI TO D162
        DATA 240
        IM(0) TO D161
        PCI TO D162
        DATA 112
        IM(4) TO D161
        PCI TO D162
        DATA 44
        IM(13) TO D161
        PCI TO D162
        DATA 200
        IM(12) TO D161
        PCI TO D162
        DATA 200
        IM(6) TO D160
        IM(13) TO D161
        IM(0) TO D162       ; pan 0, shift 0
        PCI TO R4           ; play for a while
        DATA 30000
P1:     R4 TO R3
        IM(1) TO SUB3
        R3 TO R4
        RE(P1) TO RTNZ
        IM(1) TO D160       ; carrier: new pitch and octave while sounding
        IM(1) TO D161
        PCI TO D162
        DATA 360
        IM(2) TO D161
        IM(3) TO D162
        IM(0) TO D160       ; modulator: lower octave
        IM(2) TO D161
        IM(0) TO D162
        PCI TO R4
        DATA 30000
P2:     R4 TO R3
        IM(1) TO SUB3
        R3 TO R4
        RE(P2) TO RTNZ
        IM(1) TO D160       ; release
        IM(12) TO D161
        IM(0) TO D162
        PCI TO R4
        DATA 20000
P3:     R4 TO R3
        IM(1) TO SUB3
        R3 TO R4
        RE(P3) TO RTNZ
        D161 TO R7          ; no SYN: halt
"""


def test_system_voice_engine():
    """HDL voice engine against sim/voice.py sample for sample: FM with an
    index ramp and shift, pan, VOL, a loaded wave memory, pitch and octave
    changes while sounding, a release."""
    if not HAVE_VERILATOR:
        print("  skip test_system_voice_engine (verilator not found)")
        return
    from sim.asm import assemble
    from sim.system import make_system
    cpu = make_system(synth=True)
    words, _ = assemble(VOICE_PROGRAM)
    cpu.load(words)
    with tempfile.NamedTemporaryFile(suffix=".trace", delete=False) as f:
        path = f.name
    try:
        n = record(cpu, path, 2_000_000, audio=True)
        ok, text = check(path, top="system", wav=path + ".hdl.wav")
        nonzero = _nonzero_samples(path)
        frames = expected_wav(path, path + ".py.wav")
        hdl_wav, py_wav = open(path + ".hdl.wav", "rb").read(), open(path + ".py.wav", "rb").read()
    finally:
        for p in (path, path + ".hdl.wav", path + ".py.wav"):
            if os.path.exists(p):
                os.unlink(p)
    assert ok, text
    assert frames > 5000 and hdl_wav == py_wav       # audio_out.sv = render() + write_wav()
    assert cpu.halted and cpu.halted.device == 0o161, cpu.halted
    assert nonzero > 5000 and n > 100_000, (nonzero, n)


def _nonzero_samples(path):
    """Audio samples in a trace that are not (0, 0)."""
    import struct
    b = open(path, "rb").read()
    p = 8 + 33 + 131072
    while True:
        k = b[p:p + 1]
        p += 1
        if k == b"B":
            break
        if k == b"X":
            p += 4 + struct.unpack_from("<I", b, p)[0] * 512
        elif k == b"F":
            p += 6 + struct.unpack_from("<H", b, p + 1)[0] * 512
        elif k == b"V":
            p += 7
        elif k == b"O":
            p += 11 + 64
    sizes = {b"P": 2, b"R": 3, b"W": 3, b"Q": 2, b"I": 4, b"S": 41, b"H": 1, b"E": 0,
             b"w": 4, b"K": 4, b"A": 16}
    count = 0
    while p < len(b):
        k = b[p:p + 1]
        p += 1
        if k == b"T":
            p += 6 + struct.unpack_from("<H", b, p + 4)[0]
            continue
        if k == b"A" and struct.unpack_from("<qq", b, p) != (0, 0):
            count += 1
        p += sizes[k]
    return count


def test_sine_rom_matches_python():
    from tools.gen_sine_rom import PATH, text
    assert open(PATH).read() == text(), "run python3 tools/gen_sine_rom.py"


def test_release_l_monitor_boot_and_catalog():
    image = os.environ.get("SYNCLAVIER_RELEASE_L")
    if not image or not HAVE_VERILATOR:
        print("  skip test_release_l_monitor_boot_and_catalog (needs SYNCLAVIER_RELEASE_L and verilator)")
        return
    from sim.boot import boot_from_image
    cpu, _ = boot_from_image(image, "03-SYSTD", f1="18-UTILS")
    lines = ["CATALOG\r"]

    def on_wait(cpu):
        if lines:
            cpu.terminal.feed(lines.pop(0))
            return True
        return False
    with tempfile.NamedTemporaryFile(suffix=".trace", delete=False) as f:
        path = f.name
    try:
        n = record(cpu, path, 5_000_000, on_wait=on_wait)
        for top in ("cpu", "system"):
            ok, text = check(path, top=top)
            assert ok, (top, text)
    finally:
        os.unlink(path)
    assert n > 1_000_000 and "Catalog contains 7 entries" in cpu.terminal.text()


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print("%d tests OK" % len(tests))
