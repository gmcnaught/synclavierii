#!/usr/bin/env python3
"""Build NED's Music Printing program (the Synclavier Music Engraving System,
`*SPLT-7`, PF3 in SYN-5.3) from NED's source and install it on a W0 image.

    music_printing.py build SOFTWARE OUTDIR     # SOFTWARE: a checkout of jbemond/Software
    music_printing.py install W0.IMG OUTDIR

`build` compiles NED's XPL compiler (`Code/Sources/XPLProcessors`, the
"XPL Compiler" Xcode target, with clang++ and four stubs for SCSI helpers a
command-line compile never calls), then the XPL libraries (`Able/XPL/COMALL`)
and Music Printing (`Able/MPLT/COMPILE`) the way NED's release build
(`Projects/AbleBrowser/Sync3Builder`) does. It works on a copy of the source
in OUTDIR/src and changes one line there: `PS_PRINTER_WRITE_ONLY` (MPLT/LITS)
is 1 instead of `interp_is_running`, so the program sends its PostScript
without waiting for printer replies, as it does under Synclavier3; the core's
printer port is a capture file that never answers (docs/devices/d40-printer.md
section 3.4). OUTDIR/mplt then holds the six files the release puts in
W0:.SYSTEM: .SPLT-7 (program) and .SAUX-7, .SCWT-7, .SFRM-7, .SLIB-7 (data),
.SPRO-7 (the PostScript font prolog, text).

`install` writes them into W0.IMG's .SYSTEM. Synclavier3's W0 already has
all six (its .SPLT-7 is built for the interpreter: it waits for a printer
reply); files with the same contents are left alone and .SPLT-7 is
replaced in place.

Nothing built here is committed (tests/test_repo_hygiene.py): NED's software
is MIT-licensed source; users build their own copy.
"""
import os
import shutil
import struct
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tools.ned_disk import SECTOR_WORDS, add_file, load_bytes, walk  # noqa: E402

COMPILER_SOURCES = [
    "Code/Sources/XPLProcessors/XPLCompiler.cpp", "Code/Sources/XPLProcessors/sgen.cpp",
    "Code/Sources/XPLProcessors/pass1.cpp", "Code/Sources/AbleRunTime/XPLRunTimeOSX.cpp",
    "Code/Sources/XPLProcessors/pass2.cpp", "Code/Sources/XPLProcessors/pass3.cpp",
    "Code/Sources/CF Wrapper Classes/SynclavierFileReference.mm",
    "Code/Sources/CF Wrapper Classes/SyncMutex.cpp", "Code/Sources/XPLProcessors/XPLCompilerTool.cpp",
    "Code/Sources/AbleRunTime/XPL.cpp", "Code/Sources/AbleRunTime/CustomPrintf.cpp",
]
PREFIX = "Projects/XPLProcessors/XPLCompilerPrefix.h"

STUBS = r'''// SCSI and InterChange helpers XPLRunTimeOSX refers to; a command-line
// compile reads and writes macOS files only (tools/music_printing.py).
#include <string.h>
#include "XPL.h"
#include "XPLRuntime.h"
#include "syslits.h"
#include "ScsiLib.h"
#include "Utility.h"
#include "MacSCSIOSx.h"
#include "InterChange.h"
#include "SynclavierFileReference.h"
#include "SyncMutex.h"
SyncMutex SyncScsiSegmentizerMutex;
scsi_error_code interrogate_device(scsi_device *) { return (scsi_error_code) 1; }
scsi_error_code issue_read_extended(scsi_device *, byte *, uint32, uint32) { return (scsi_error_code) 1; }
scsi_error_code issue_write_extended(scsi_device *, byte *, uint32, uint32) { return (scsi_error_code) 1; }
chip_error_code finalize_mac_scsi_port_scsi_chip() { return (chip_error_code) 0; }
void zero_mem(byte *the_data, uint32 the_length) { memset(the_data, 0, the_length); }
int InterChangeLibEqualFSSpecs(SyncFSSpec *, SyncFSSpec *) { return 0; }
'''

WRITE_ONLY_OLD = b"dcl PS_PRINTER_WRITE_ONLY\tlit 'interp_is_running';"
WRITE_ONLY_NEW = b"dcl PS_PRINTER_WRITE_ONLY\tlit '1';"

# (W0:.SYSTEM name, file in OUTDIR/mplt, NED file type: 0 text, 1 exec, 3 data)
FILES = [(".SPLT-7", "*SPLT-7.sprg", 1), (".SAUX-7", "*SAUX-7.sdat", 3),
         (".SCWT-7", "*SCWT-7.sdat", 3), (".SFRM-7", "*SFRM-7.sdat", 3),
         (".SLIB-7", "*SLIB-7.sdat", 3), (".SPRO-7", "*SPRO-7.txt", 0)]


def build_compiler(src, out):
    """NED's XPL compiler (the 'XPL Compiler' target) as OUT/XPLCompiler."""
    obj = os.path.join(out, "obj")
    os.makedirs(obj, exist_ok=True)
    incs = []
    for root, _dirs, _files in os.walk(os.path.join(src, "Code")):
        incs += ["-I", root]
    stub = os.path.join(src, "Code", "Sources", "music_printing_stubs.cpp")
    with open(stub, "w") as f:
        f.write(STUBS)
    objs = []
    for rel in COMPILER_SOURCES + ["Code/Sources/music_printing_stubs.cpp"]:
        o = os.path.join(obj, os.path.basename(rel).rsplit(".", 1)[0] + ".o")
        lang = ["-x", "objective-c++", "-fobjc-arc"] if rel.endswith(".mm") else []
        cmd = (["clang++"] + lang + ["-std=gnu++11", "-w", "-include", os.path.join(src, PREFIX)]
               + incs + ["-c", os.path.join(src, rel), "-o", o])
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode:
            raise SystemExit("compiling %s failed:\n%s" % (rel, r.stderr[-3000:]))
        objs.append(o)
    exe = os.path.join(out, "XPLCompiler")
    r = subprocess.run(["clang++", "-o", exe] + objs + ["-framework", "CoreFoundation",
                                                        "-framework", "Foundation",
                                                        "-framework", "CoreServices"],
                       capture_output=True, text=True)
    if r.returncode:
        raise SystemExit("linking the XPL compiler failed:\n" + r.stderr[-3000:])
    return exe


def build(software, out):
    out = os.path.abspath(out)
    src = os.path.join(out, "src")
    if os.path.exists(src):
        shutil.rmtree(src)
    shutil.copytree(os.path.join(software, "Code"), os.path.join(src, "Code"))
    shutil.copytree(os.path.join(software, "Projects", "XPLProcessors"),
                    os.path.join(src, "Projects", "XPLProcessors"))
    shutil.copytree(os.path.join(software, "Able"), os.path.join(src, "Able"))
    lits = os.path.join(src, "Able", "MPLT", "LITS")
    data = open(lits, "rb").read()
    if data.count(WRITE_ONLY_OLD) != 1:
        raise SystemExit("MPLT/LITS: PS_PRINTER_WRITE_ONLY declaration not found")
    open(lits, "wb").write(data.replace(WRITE_ONLY_OLD, WRITE_ONLY_NEW))
    print("compiler ...")
    exe = build_compiler(src, out)
    xpl = os.path.join(out, "xpl")
    for d in ("-XPL", "MPLT/RELOC", "W0 MPLT Files", "tmp"):
        os.makedirs(os.path.join(xpl, d), exist_ok=True)
    able = os.path.join(src, "Able")
    script = '''set -e
cd "$AbleFldr"
com () {{ "{exe}" -md "$AbleFldr" -od "$XPLFolder" -q "$@" || exit 1; }}
source "$AbleFldr/XPL/COMALL"
source "$AbleFldr/MPLT/COMPILE"
'''.format(exe=exe)
    print("XPL libraries and Music Printing ...")
    r = subprocess.run(["bash", "-c", script], env=dict(os.environ, AbleFldr=able, XPLFolder=xpl),
                       capture_output=True, text=True)
    if r.returncode:
        raise SystemExit("XPL build failed:\n" + (r.stdout + r.stderr)[-3000:])
    mplt = os.path.join(out, "mplt")
    os.makedirs(mplt, exist_ok=True)
    shutil.copy(os.path.join(xpl, "W0 MPLT Files", "*SPLT-7.sprg"), mplt)
    for _name, fname, _typ in FILES[1:]:
        shutil.copy(os.path.join(able, "W0 MPLT Files", fname), mplt)
    for _name, fname, _typ in FILES:
        print("%s: %d bytes" % (os.path.join(mplt, fname), os.path.getsize(os.path.join(mplt, fname))))


def able_text(data):
    """A macOS text file (CR line ends) as an NED text file, as AbleDiskTool
    ExportAbleTextFile writes it: per line its number, the characters two to
    a word (the first in the low byte), then the last odd character or a 0."""
    out, line, saved, word, sol, eol = [], 1, False, 0, True, False
    for ch in data:
        if sol:
            out.append(line)
            line += 1
            sol = False
        if ch == 13:
            out.append(word if saved else 0)
            saved = eol = False
            sol = True
        else:
            eol = True
            if not saved:
                saved, word = True, ch
            else:
                out.append(word | ch << 8)
                saved = False
    if saved:
        out.append(word)
    elif eol:
        out.append(0)
    return struct.pack(">%dH" % len(out), *[w & 0xFFFF for w in out])


def install(disk, files):
    """Put `files` [(name, data bytes, type)] into W0:.SYSTEM of `disk` (a
    bytearray, changed in place) with ned_disk.add_file: a file already
    there with the same contents is left alone, one with the same name is
    overwritten in place when the new data fits its sectors (Synclavier3's
    W0 has all six; only .SPLT-7 differs), else a new entry is used.
    Returns [(name, action)]."""
    W = load_bytes(disk)
    have = {p.rsplit("/", 1)[1]: (s, ln, w) for p, t, s, ln, w in walk(W) if p.startswith("/.SYSTEM/")}
    done = []
    for name, data, typ in files:
        if name in have:
            s, ln, w = have[name]
            old = bytes(disk[s * SECTOR_WORDS * 2:(s + ln) * SECTOR_WORDS * 2])
            if old[:len(data)] == data and not any(old[len(data):]):
                done.append((name, "unchanged"))
                continue
        add_file(disk, "/.SYSTEM/" + name, data, typ=typ, replace=True)
        done.append((name, "replaced" if name in have else "added"))
    return done


def mplt_files(outdir):
    """The six files from `build`'s OUTDIR (or its mplt directory)."""
    d = os.path.join(outdir, "mplt") if os.path.isdir(os.path.join(outdir, "mplt")) else outdir
    files = []
    for name, fname, typ in FILES:
        data = open(os.path.join(d, fname), "rb").read()
        files.append((name, able_text(data) if typ == 0 else data, typ))
    return files


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build the compiler and Music Printing")
    b.add_argument("software", help="checkout of jbemond/Software (all of Able/, Code/, Projects/)")
    b.add_argument("outdir")
    i = sub.add_parser("install", help="install Music Printing on a W0 image")
    i.add_argument("image")
    i.add_argument("outdir", help="build's OUTDIR")
    a = ap.parse_args(argv)
    if a.cmd == "build":
        build(a.software, a.outdir)
        return 0
    disk = bytearray(open(a.image, "rb").read())
    for name, action in install(disk, mplt_files(a.outdir)):
        print("W0:.SYSTEM:%-8s %s" % (name, action))
    open(a.image, "wb").write(disk)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
