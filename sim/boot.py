"""High-level boot (milestone M1.6 step A): start Release L MONITOR without
the boot ROM or a floppy controller.

What the real machine does (docs/boot-and-loaders.md):
  Load button -> boot ROM (not available) reads the high-memory loader
  `.LD-x` into LOC.LOAD = MEM.SIZ - 1024 and enters its FBOOT entry, which
  reads the floppy catalog, loads MONITOR at 0 and jumps to it.

What this module does instead:
  1. Places the floppy slot of `.LD-6` (its first 512 words) at
     LOC.LOAD = MEM.SIZ - 1024. [HYP for Release L: LOC.LOAD is
     MEM.SIZ - 1024 in SYSLITS and FLPLOAD (-7); the -6 offset is assumed.]
  2. Copies MONITOR into external memory (it never has to come from a disk).
  3. Enters the loader's own ECOPY entry (offset 4: "external memory to
     core copy", R0 = sector, R1 = destination, R2 = length). From there
     the real loader code runs: it copies MONITOR to 0, checks the XPL
     configuration pointer, skips the high-core configuration copy because
     the magic number is absent (a cold boot), and jumps to location 0.

MEM.SIZ comes from MONITOR's own configuration table: word 1 of every XPL
program points to it and entry 16 (C#MEMSIZ) is the memory size in
sectors. MONITOR's runtime takes its variable and stack areas from the same
table and does no memory sizing of its own.

The rest (catalog, .LD-x reload) is MONITOR's cold boot (NED MONCAT:MON,
COLD.BOOT), which needs disk access: step B (D100 floppy) or a disk HLE.
"""
from .system import make_system

SECTOR_WORDS = 256
XPL_FIRST_WORD = 0o100377   # PCI TO LOA0: the first instruction of every XPL program
C_MEMSIZ = 16               # configuration table: memory size in sectors
LOADER_SLOT_WORDS = 512     # .LD-6 has three 512-word loaders (floppy, IMI, SCSI)
LOADER_ECOPY = 4            # entry 4: external memory to core copy


def config_pointer(program):
    if program[0] != XPL_FIRST_WORD:
        raise ValueError("not an XPL program (word 0 is %06o)" % program[0])
    return program[1]


def mem_size(program):
    """MEM.SIZ in words from the program's configuration table."""
    sectors = program[config_pointer(program) + C_MEMSIZ]
    if not 0 < sectors <= 256:
        raise ValueError("configured memory size %o sectors is invalid" % sectors)
    return sectors * SECTOR_WORDS


def boot(cpu, program, loader, staging_sector=0):
    """Set up cpu to boot program (e.g. MONITOR) through loader (.LD-6).

    cpu needs external memory (D60-D63). Returns a dict describing the
    layout. Run the CPU afterwards; the loader starts the program at 0.
    """
    if cpu.extmem is None:
        raise ValueError("boot needs external memory (D60-D63)")
    msiz = mem_size(program)
    loc_load = msiz - 1024
    slot = loader[:LOADER_SLOT_WORDS]
    cpu.load(slot, loc_load)
    cpu.extmem.load(staging_sector, program)
    cpu.reset()
    cpu.r[0] = staging_sector
    cpu.r[1] = 0                 # destination: location 0
    cpu.r[2] = len(program)
    cpu.pc = loc_load + LOADER_ECOPY
    return {"mem_siz": msiz, "loc_load": loc_load,
            "config": config_pointer(program), "length": len(program)}


def boot_from_image(image, floppy="01-BOOTD", **system_kw):
    """Return (cpu, layout) ready to boot MONITOR from a Release L image.

    image: path to a .simg; floppy: the sub-catalog holding MONITOR/.LD-6.
    """
    from tools.ned_disk import load, read_file
    W = load(image)
    program = read_file(W, floppy + "/MONITOR")
    loader = read_file(W, floppy + "/.LD-6")
    cpu = make_system(**system_kw)
    return cpu, boot(cpu, program, loader)


def main(argv=None):
    import argparse
    import sys
    from .trace import Debugger

    ap = argparse.ArgumentParser(description="Boot Release L MONITOR (M1.6 step A)")
    ap.add_argument("image", help="Release L .simg (user-supplied)")
    ap.add_argument("--floppy", default="01-BOOTD")
    ap.add_argument("--max", type=int, default=20_000_000, help="instruction budget")
    ap.add_argument("--input", default="", help="characters to type (\\r for Return)")
    ap.add_argument("--break", dest="bps", action="append", default=[],
                    metavar="OCT", help="breakpoint address (octal); repeatable")
    a = ap.parse_args(argv)

    out = sys.stdout
    cpu, layout = boot_from_image(
        a.image, a.floppy,
        output=lambda b: (out.write(chr(b & 0o177)), out.flush()))
    print("boot: MEM.SIZ=%06o LOC.LOAD=%06o config=%06o length=%06o"
          % (layout["mem_siz"], layout["loc_load"], layout["config"], layout["length"]))
    if a.input:
        cpu.terminal.feed(a.input.encode().decode("unicode_escape"))
    dbg = Debugger(cpu)
    dbg.breakpoints.update(int(b, 8) for b in a.bps)
    stop = dbg.run(a.max)
    print("\n" + "=" * 60)
    print("stop: %s" % (stop or "instruction budget used up"))
    print(dbg.report())
    return 0 if stop != "halted" else 1


if __name__ == "__main__":
    raise SystemExit(main())
