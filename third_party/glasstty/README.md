# Glass TTY VT220 (Unlicense)

`glass-tty-vt220.txt` is the dot matrix of `Glass_TTY_VT220.ttf` from
svofski's Glass TTY (`https://github.com/svofski/glasstty`, commit
2bed112c6844db70fbd857ab138d3fc283439102, font version 001.3, git blob
8ebdd7bba9c82d418979af7bc9d84acd1fee0ffb), a reproduction of the DEC
VT220's character ROM: a 7 x 9 matrix in a 10 x 10 cell, capitals 7 rows,
descenders 2 rows below the baseline; codes 0x01-0x1F hold the DEC special
graphics (VT100 line drawing). Licence: the Unlicense (`LICENSE`, copied
from the repository).

`tools/glass_extract.py` wrote the text file from the TTF (the TTF draws
runs of stretched dots; the stretch is removed). `tools/gen_font.py`
turns it into `hdl/core/fontglass.svh` and the Python model's glyphs: the
text plane in VT640 mode (`hdl/core/term_display.sv`, `tools/vt100.py`).
