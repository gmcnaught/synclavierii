#!/usr/bin/env python3
"""Type on the MiSTer through a virtual uinput keyboard (runs on the MiSTer:
python3, 32-bit ARM; after scripts/mister/mister_run.sh copies it there).
Same approach as maldita.castilla-cps3/scripts/mister_keys.py.

    mister_keys.py ARG...    each ARG is typed in order:
        text:KEYS   the characters (letters, digits, space, punctuation below;
                    upper case and shifted symbols with Shift; \\r or \\n = Enter)
        CHORD       key names joined by + (F12, ENTER, ESC, LEFTSHIFT+...)
        sleep:S     wait S seconds
        mouse:DX,DY move a virtual mouse (Linux axes: +Y is down), in steps
        click[:S]   left button down for S seconds (default 0.3), then up
"""
import fcntl
import os
import struct
import sys
import time

# Linux input event codes
NAMED = {'ESC': 1, 'BACKSPACE': 14, 'TAB': 15, 'ENTER': 28, 'LEFTCTRL': 29, 'LEFTSHIFT': 42,
         'SPACE': 57, 'F1': 59, 'F2': 60, 'F3': 61, 'F12': 88, 'UP': 103, 'DOWN': 108,
         'LEFT': 105, 'RIGHT': 106, 'F4': 62, 'KPENTER': 96}
ROWS = {'1234567890': 2, 'qwertyuiop': 16, 'asdfghjkl': 30, 'zxcvbnm': 44}
CHAR = {}
for row, start in ROWS.items():
    for i, ch in enumerate(row):
        CHAR[ch] = (start + i, False)
        if ch.isalpha():
            CHAR[ch.upper()] = (start + i, True)
for ch, code in {'-': 12, '=': 13, '[': 26, ']': 27, ';': 39, "'": 40, '`': 41, '\\': 43,
                 ',': 51, '.': 52, '/': 53, ' ': 57, '\r': 28, '\n': 28, '\t': 15}.items():
    CHAR[ch] = (code, False)
for ch, base in {'!': '1', '@': '2', '#': '3', '$': '4', '%': '5', '^': '6', '&': '7', '*': '8',
                 '(': '9', ')': '0', '_': '-', '+': '=', '{': '[', '}': ']', ':': ';', '"': "'",
                 '~': '`', '|': '\\', '<': ',', '>': '.', '?': '/'}.items():
    CHAR[ch] = (CHAR[base][0], True)

UI_SET_EVBIT, UI_SET_KEYBIT, UI_DEV_CREATE, UI_DEV_DESTROY = 0x40045564, 0x40045565, 0x5501, 0x5502
UI_SET_RELBIT = 0x40045566
EV_SYN, EV_KEY, EV_REL = 0, 1, 2
REL_X, REL_Y, BTN_LEFT = 0, 1, 0x110


def make_mouse():
    fd = os.open('/dev/uinput', os.O_WRONLY | os.O_NONBLOCK)
    fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
    fcntl.ioctl(fd, UI_SET_KEYBIT, BTN_LEFT)
    fcntl.ioctl(fd, UI_SET_EVBIT, EV_REL)
    fcntl.ioctl(fd, UI_SET_RELBIT, REL_X)
    fcntl.ioctl(fd, UI_SET_RELBIT, REL_Y)
    os.write(fd, struct.pack('80sHHHHi', b'synclavier-mouse', 3, 0x1234, 0x567a, 1, 0) + b'\0' * (256 * 4))
    fcntl.ioctl(fd, UI_DEV_CREATE)
    time.sleep(2)
    return fd


def ev(fd, t, c, v):
    s, us = divmod(time.time(), 1)
    os.write(fd, struct.pack('llHHi', int(s), int(us * 1e6), t, c, v))


def press(fd, codes):
    for c in codes:
        ev(fd, EV_KEY, c, 1)
        ev(fd, EV_SYN, 0, 0)
        time.sleep(0.03)
    time.sleep(0.08)
    for c in reversed(codes):
        ev(fd, EV_KEY, c, 0)
        ev(fd, EV_SYN, 0, 0)
        time.sleep(0.03)
    time.sleep(0.12)


def main():
    fd = os.open('/dev/uinput', os.O_WRONLY | os.O_NONBLOCK)
    fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
    for c in set(NAMED.values()) | {c for c, _ in CHAR.values()}:
        fcntl.ioctl(fd, UI_SET_KEYBIT, c)
    os.write(fd, struct.pack('80sHHHHi', b'synclavier-keys', 3, 0x1234, 0x5679, 1, 0) + b'\0' * (256 * 4))
    fcntl.ioctl(fd, UI_DEV_CREATE)
    time.sleep(2)                                   # Main_MiSTer picks up the new device
    mouse = None
    for arg in sys.argv[1:]:
        if arg.startswith('mouse:') or arg.startswith('click'):
            if mouse is None:
                mouse = make_mouse()
            if arg.startswith('mouse:'):
                dx, dy = (int(v) for v in arg[6:].split(','))
                while dx or dy:
                    sx = max(-40, min(40, dx))
                    sy = max(-40, min(40, dy))
                    ev(mouse, EV_REL, REL_X, sx)
                    ev(mouse, EV_REL, REL_Y, sy)
                    ev(mouse, EV_SYN, 0, 0)
                    dx -= sx
                    dy -= sy
                    time.sleep(0.02)
            else:
                hold = float(arg[6:]) if arg.startswith('click:') else 0.3
                ev(mouse, EV_KEY, BTN_LEFT, 1)
                ev(mouse, EV_SYN, 0, 0)
                time.sleep(hold)
                ev(mouse, EV_KEY, BTN_LEFT, 0)
                ev(mouse, EV_SYN, 0, 0)
                time.sleep(0.5)
        elif arg.startswith('text:'):
            for ch in arg[5:].encode().decode('unicode_escape'):
                code, shift = CHAR[ch]
                press(fd, [NAMED['LEFTSHIFT'], code] if shift else [code])
        elif arg.startswith('sleep:'):
            time.sleep(float(arg[6:]))
        else:
            press(fd, [NAMED[k] for k in arg.split('+')])
            time.sleep(1)
    time.sleep(1)
    fcntl.ioctl(fd, UI_DEV_DESTROY)
    os.close(fd)
    if mouse is not None:
        fcntl.ioctl(mouse, UI_DEV_DESTROY)
        os.close(mouse)


if __name__ == '__main__':
    main()
