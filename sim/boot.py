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


def floppy_media(W, name):
    """Media for the floppy sub-catalog `name` of a .simg (words W).

    Each Release L floppy is one type-7 sub-catalog; its sectors, from the
    catalog sector on, are the floppy's logical sectors 0, 1, 2...
    """
    from tools.ned_disk import walk
    from .devices.floppy import Media
    for p, typ, start, length, words in walk(W):
        if p == "/" + name and typ == 7:
            return Media(W[start * SECTOR_WORDS:(start + length) * SECTOR_WORDS])
    raise KeyError(name)


def boot_from_image(image, floppy="03-SYSTD", f1=None, **system_kw):
    """Return (cpu, layout) ready to boot MONITOR from a Release L image.

    image: path to a .simg; floppy: the sub-catalog holding MONITOR/.LD-6,
    also inserted in F0; f1: optional sub-catalog to insert in F1.
    """
    from tools.ned_disk import load, read_file
    W = load(image)
    program = read_file(W, floppy + "/MONITOR")
    loader = read_file(W, floppy + "/.LD-6")
    cpu = make_system(floppy=True, synth=True, **system_kw)
    cpu.floppy.insert(0, floppy_media(W, floppy))
    if f1:
        cpu.floppy.insert(1, floppy_media(W, f1))
    return cpu, boot(cpu, program, loader)


def main(argv=None):
    import argparse
    import sys
    from .trace import STOP_INPUT, Debugger

    ap = argparse.ArgumentParser(description="Boot Release L MONITOR (M1.6)")
    ap.add_argument("image", help="Release L .simg (user-supplied)")
    ap.add_argument("--floppy", default="03-SYSTD", help="boot floppy (also in F0)")
    ap.add_argument("--f1", help="floppy to insert in F1, e.g. 18-UTILS")
    ap.add_argument("--max", type=int, default=200_000_000,
                    help="step budget per run segment")
    ap.add_argument("--input", default=None,
                    help="script of characters to type (\\r for Return); exit when used up")
    ap.add_argument("--break", dest="bps", action="append", default=[],
                    metavar="OCT", help="breakpoint address (octal); repeatable")
    a = ap.parse_args(argv)

    out = sys.stdout
    cpu, layout = boot_from_image(
        a.image, a.floppy, a.f1,
        output=lambda b: (out.write(chr(b & 0o177)), out.flush()))
    print("boot: MEM.SIZ=%06o LOC.LOAD=%06o config=%06o length=%06o"
          % (layout["mem_siz"], layout["loc_load"], layout["config"], layout["length"]))
    dbg = Debugger(cpu)
    dbg.breakpoints.update(int(b, 8) for b in a.bps)
    # Script lines are typed one at a time, each when the program next waits
    # for input (MONITOR discards typeahead during its cold boot).
    script = None
    if a.input is not None:
        text = a.input.encode().decode("unicode_escape")
        script = [ln + "\r" for ln in text.split("\r")]
        if script and script[-1] == "\r":
            script.pop()
    interactive = script is None and sys.stdin.isatty()
    while True:
        stop = dbg.run(a.max, until_input=True)
        if stop != STOP_INPUT:
            break
        if script:
            cpu.terminal.feed(script.pop(0))
            continue
        if not interactive:
            break
        try:
            line = input()
        except EOFError:
            break
        cpu.terminal.feed(line + "\r")
    print("\n" + "=" * 60)
    print("stop: %s" % (stop or "step budget used up"))
    if stop != STOP_INPUT:
        print(dbg.report())
    return 1 if stop == "halted" else 0


if __name__ == "__main__":
    raise SystemExit(main())
