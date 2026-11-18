#!/usr/bin/env python3
"""The MGLs shipped with a release (mister/mgl/, attached by
.github/workflows/release.yml) load the released core and mount each image
in an S slot of CONF_STR whose extension matches.

Run:  python3 tests/test_mgl.py
"""
import glob
import os
import re
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def conf_str():
    """Core name and {slot index: extension} from mister/Synclavier.sv."""
    src = open(os.path.join(ROOT, "mister", "Synclavier.sv")).read()
    name = re.search(r'^\s*"([A-Za-z0-9]+);', src, re.M).group(1)
    slots = {int(n): ext.upper()
             for n, ext in re.findall(r'^\s*"S(\d+),([A-Za-z0-9]+),', src, re.M)}
    return name, slots


def mgls():
    paths = sorted(glob.glob(os.path.join(ROOT, "mister", "mgl", "*.mgl")))
    assert paths, "no MGLs in mister/mgl"
    return paths


def test_core_name():
    name, _ = conf_str()
    assert name == "Synclavier", name
    build = open(os.path.join(ROOT, "mister", "build.sh")).read()
    assert '"$OUTDIR/%s_20$d.rbf"' % name in build, \
        "build.sh must name the RBF <core>_YYYYMMDD.rbf"


def test_mgls():
    name, slots = conf_str()
    for p in mgls():
        root = ET.parse(p).getroot()
        assert root.tag == "mistergamedescription", p
        assert root.findtext("rbf") == "_Computer/" + name, p
        files = root.findall("file")
        assert files, p
        for f in files:
            assert f.get("type") == "s", (p, f.attrib)
            idx = int(f.get("index"))
            assert idx in slots, (p, idx)
            ext = os.path.splitext(f.get("path"))[1][1:].upper()
            assert ext == slots[idx], (p, f.get("path"), slots[idx])
            assert int(f.get("delay")) >= 1, (p, f.attrib)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print("%d tests OK" % len(tests))
