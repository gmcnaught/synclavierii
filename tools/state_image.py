#!/usr/bin/env python3
"""Write a state image: the simulator's whole machine state, for the core's
boot loader to load from SD slot S2 instead of booting MONITOR from F0.

    state_image.py IMAGE OUT [--rtp ORK-LM]

Default: the state sim/rtp.py start_rtp() reaches for the real-time
program (MONITOR booted from 03-SYSTD, the RTP staged in external memory,
the CPU at the .LD-6 loader's ECOPY entry). Release L cannot load the
two-floppy RTP from floppies alone (it was a Winchester system), so this is
how the core starts it. Mount F0 = 03-SYSTD and F1 = the RTP's first floppy
(14-RTPO1 for ORK-LM) as the simulator had them; the floppy controller's
state is in the image, the media are the mounted files.

Format (512-byte blocks, 16-bit words big-endian, as the floppy images):
  block 0      header: words 0-3 "SYNCSTAT", 4 version (1), 5 external
               memory sectors, 6 number of entries N, 8-23 R0-R17,
               24 flags {pcs, ion, m, c, z}
  blocks 1..   N entries of 8 words, padded to a block: kind (0 device,
               1 voice engine), device select, address, 0, data (64 bits,
               high word first). Device entries are the 'V' values of
               sim/lockstep.py's trace header (wave memory excepted), voice
               entries its 'O' values: the load-port writes the lockstep
               bench makes, so the core starts where a trace does.
  16 blocks    wave memory, 32 x 256 bytes
  256 blocks   internal memory, 64K words
  S blocks     external memory, S sectors
"""
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

MAGIC = b"SYNCSTAT"
VERSION = 1
BLOCK = 512


def entries(cpu):
    """(kind, sel, addr, data) load-port writes for the devices and voices."""
    from sim.lockstep import _Audio, _device_header
    out = []
    h = _device_header(cpu)
    p = 0
    while p < len(h):
        k = h[p:p + 1]
        p += 1
        if k == b"X":
            p += 4 + struct.unpack_from("<I", h, p)[0] * 512
        elif k == b"F":
            p += 6 + struct.unpack_from("<H", h, p + 1)[0] * 512
        elif k == b"V":
            sel, addr, v = struct.unpack_from("<BHI", h, p)
            p += 7
            if sel != 6:                        # wave memory: whole, below
                out.append((0, sel, addr, v))
        else:
            raise ValueError("unexpected header section %r" % k)
    if cpu.fm is not None:
        o = _Audio(cpu.fm).header()
        rr, to_next, phase = struct.unpack_from("<QHB", o, 1)
        out.append((1, 0, 32, rr))
        out.append((1, 0, 33, phase << 14 | to_next))
        for c in range(16):
            acc, pre, point = struct.unpack_from("<HBB", o, 12 + 4 * c)
            out.append((1, 0, c, acc << 15 | pre << 8 | point))
    return out


def state_bytes(cpu):
    """The state image of a system (sim/system.py make_system(floppy=True,
    synth=True)) between instructions."""
    from sim.lockstep import _flags
    es = entries(cpu)
    xm = cpu.extmem
    if xm.sectors > 4096:
        raise ValueError("external memory over 4096 sectors")
    hdr = MAGIC + struct.pack(">HHHH", VERSION, xm.sectors, len(es), 0)
    hdr += struct.pack(">16HH", *cpu.r, _flags(cpu))
    out = bytearray(hdr.ljust(BLOCK, b"\0"))
    ent = bytearray()
    for kind, sel, addr, data in es:
        ent += struct.pack(">HHHHQ", kind, sel, addr, 0, data)
    out += ent.ljust(-(-len(ent) // BLOCK) * BLOCK, b"\0")
    for mem in cpu.fm.wave:
        out += bytes(mem)
    out += struct.pack(">65536H", *cpu.mem)
    out += struct.pack(">%dH" % (xm.sectors * 256), *xm.data)
    return bytes(out)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("image", help="Release L .simg")
    ap.add_argument("out")
    ap.add_argument("--rtp", default="ORK-LM")
    a = ap.parse_args(argv)
    from sim.rtp import rtp_parts, start_rtp
    from tools.ned_disk import load
    cpu, _dbg, lay = start_rtp(a.image, a.rtp)        # as the lockstep traces
    data = state_bytes(cpu)
    open(a.out, "wb").write(data)
    first = rtp_parts(load(a.image), a.rtp)[0][1].strip("/").split("/")[0]
    print("%s: %d blocks; mount F0 = 03-SYSTD, F1 = %s" % (a.out, len(data) // BLOCK, first))


if __name__ == "__main__":
    raise SystemExit(main())
