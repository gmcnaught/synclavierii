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


C_CMOPT = 17                # configuration table: computer and music options
O_PROCT = 0o3400            # options word: processor type field (0 A, 1 B, 2 C, 3 D)


def set_processor(program, model):
    """Copy of an XPL program whose configured processor type is `model`
    ("A".."D"), as CONFIGUR would set it. Release L's system disks are
    configured for Model C (options 141031 / 141011)."""
    program = list(program)
    i = config_pointer(program) + C_CMOPT
    program[i] = (program[i] & ~O_PROCT) | ("ABCD".index(model) << 8)
    return program


def boot(cpu, program, loader, staging_sector=0):
    """Set up cpu to boot program (e.g. MONITOR) through loader (.LD-6).

    cpu needs external memory (D60-D63). Returns a dict describing the
    layout. Run the CPU afterwards; the loader starts the program at 0.
    """
    if cpu.extmem is None:
        raise ValueError("boot needs external memory (D60-D63)")
    msiz = mem_size(program)
    loc_load = msiz - 1024
    slot = loader[:LOADER_SLOT_WORDS] if len(loader) > 768 else loader
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


def insert_floppy(cpu, image, drive, name):
    """Put floppy `name` of a .simg into drive 0 (F0) or 1 (F1), as a user
    swapping disks would. Writes stay in memory."""
    from tools.ned_disk import load
    cpu.floppy.insert(drive, floppy_media(load(image), name))


def boot_from_image(image, floppy="03-SYSTD", f1=None, processor="B", **system_kw):
    """Return (cpu, layout) ready to boot MONITOR from a Release L image.

    image: path to a .simg; floppy: the sub-catalog holding MONITOR/.LD-6,
    also inserted in F0; f1: optional sub-catalog to insert in F1.
    processor: the processor type written into MONITOR's configuration
    (default "B", matching the simulated CPU; None keeps the disk's value).
    MONITOR copies its configuration to high core and the loader copies
    that into every program it starts, so this is what programs see.
    """
    from tools.ned_disk import load, read_file
    W = load(image)
    program = read_file(W, floppy + "/MONITOR")
    if processor:
        program = set_processor(program, processor)
    loader = read_file(W, floppy + "/.LD-6")
    cpu = make_system(floppy=True, synth=True, **system_kw)
    cpu.floppy.insert(0, floppy_media(W, floppy))
    if f1:
        cpu.floppy.insert(1, floppy_media(W, f1))
    return cpu, boot(cpu, program, loader)


C_CMOPT = 17                # configuration table: options (bit 100: D44 mouse present)
C_PTYPE = 18                # ... terminal type: 021400 VT640, 101400 Macintosh (Synclavier3's)
C_STRDEV = 0o30             # configuration table: storage device table (4-word entries)
C_STREND = 0o100            # ... up to here; an entry of 177777 ends it


def keep_devices(program, n):
    """Copy of an XPL program whose configured storage device table keeps
    only its first n entries (as CONFIGUR would remove drives). Synclavier3's
    W0 MONITOR lists W0 (SCSI target 5), F0, a second SCSI disk (target 4)
    and an optical drive (target 1)."""
    program = list(program)
    c = config_pointer(program)
    for i in range(C_STRDEV + 4 * n, C_STREND):
        program[c + i] = 0o177777
    return program


LD7_SLOT_WORDS = 768        # .LD-7: three 768-word loaders (LOADER:MRGLOAD)
LD7_SCSI_SLOT = 2           # FLPLOAD., WINLOAD., SCSILOA. in that order


def set_terminal(program, terminal, mouse=False):
    """Copy of an XPL program with configuration words 17/18 set for the
    terminal (docs/devices/vt640-graphics-terminal.md section 2): "vt640"
    (021400) or "vt100" (001400); mouse sets the D44 mouse bit. The loader
    copies MONITOR's table into every program it starts."""
    program = list(program)
    c = config_pointer(program)
    program[c + C_PTYPE] = {"vt640": 0o21400, "vt100": 0o1400}[terminal]
    if mouse:
        program[c + C_CMOPT] |= 0o100
    return program


O_PVOICE = 0o200            # options: mono (3200) poly voice cards (-XPL/SYSLITS)


def boot_from_w0(image, ext_sectors=8192, target=5, devices=2, disk_mb=None, poly=None,
                 w1=None, terminal=None, mouse=False, mono=False, **system_kw):
    """Return (cpu, layout) ready to boot MONITOR from a Release 5.3-style W0:
    image (a hard-disk .simg, e.g. Synclavier3's "W0 Disk Image.simg").

    A Model D system with the D24 SCSI host and the image as a SCSI disk
    (target `target`); the SCSI loader slot of .SYSTEM/.LD-7 at LOC.LOAD,
    MONITOR copied in through the loader's ECOPY entry as for floppies.
    devices: storage device table entries to keep (keep_devices).
    disk_mb: pad the disk to this size (free space after the image's files;
    READ CAPACITY reports it). poly: a devices.poly.PolySynth (D51 poly bit
    set); default the no-voices stub (stubs.PolyNoVoices). w1: a second
    disk image at SCSI target 4 (W1:; the device table then keeps 3 entries:
    W0, F0, W1), as cpu.w1. terminal: None keeps the image's terminal type
    (Synclavier3's: Macintosh); "vt640" configures a VT640 graphics terminal
    (cpu.terminal.vt640 set: the core draws Tektronix graphics). mouse: a
    D44/D45/D54 mouse (devices.mouse.Mouse, cpu.mouse) and the configuration
    bit that tells SYN-5.3 it is there. mono: mono poly voice cards (a
    3200's): MONITOR's options word gets o#pvoice, which the loader copies
    into SYN-5.3, and the PolySynth sends its right sum to both outputs.
    cpu.cmopt_xaddr is the external-memory word address of that options
    word (MONITOR is staged at sector 0); the state image records it so the
    core's OSD can set the bit at load. Writes go
    to the in-memory copies of the
    images (cpu.w0, cpu.w1), never the files.
    """
    from tools.ned_disk import load, read_file
    from .devices.scsi import ScsiDisk
    W = load(image)
    if w1 is not None:
        devices = max(devices, 3)
    program = keep_devices(read_file(W, "MONITOR"), devices)
    if terminal or mouse:
        program = set_terminal(program, terminal or "vt640", mouse)
    if mono:
        program[config_pointer(program) + C_CMOPT] |= O_PVOICE
        if poly is not None:
            poly.mono = True
    if mouse:
        from .devices.mouse import Mouse
        system_kw["mouse"] = Mouse()
    ld7 = read_file(W, ".SYSTEM/.LD-7")
    slot = ld7[LD7_SCSI_SLOT * LD7_SLOT_WORDS:(LD7_SCSI_SLOT + 1) * LD7_SLOT_WORDS]
    disk = ScsiDisk.from_file(image)
    if disk_mb:
        disk.data.extend(bytes(max(0, disk_mb * 1024 * 1024 - len(disk.data))))
    if poly is None:
        cpu = make_system(ext_sectors=ext_sectors, scsi={target: disk}, model="D",
                          synth=True, floppy=True, **system_kw)
        from .devices.stubs import PolyNoVoices
        cpu.poly = cpu.bus.attach(PolyNoVoices())
    else:
        cpu = make_system(ext_sectors=ext_sectors, scsi={target: disk}, model="D",
                          synth=True, floppy=True, poly=poly, **system_kw)
    # D57: Model D, D40Q, M64K (MONITOR CHECK.MEM.SIZ needs both boards for 63K)
    cpu.d57 = 0o7
    cpu.w0 = disk
    cpu.terminal.vt640 = terminal == "vt640"
    cpu.cmopt_xaddr = config_pointer(program) + C_CMOPT
    cpu.w1 = None
    if w1 is not None:
        cpu.w1 = cpu.scsi.targets[4] = ScsiDisk.from_file(w1)
    return cpu, boot(cpu, program, slot)


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
