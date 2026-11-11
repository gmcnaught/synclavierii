# 6x10 font (public domain)

`6x10-ascii.bdf` is the ASCII 32–126 subset of `6x10.bdf` from the X.Org
"misc-misc" fonts (`https://gitlab.freedesktop.org/xorg/font/misc-misc`,
file `6x10.bdf`, header: `COPYRIGHT "Public domain terminal emulator font.
Share and enjoy."`). Every glyph is a 5 x 7 dot matrix (capitals 7 rows,
descenders 2 rows below the baseline) in a 6 x 10 cell.

`tools/gen_font.py` turns it into `hdl/core/font6x10.svh` and the Python
VT640 model's glyphs: the characters SYN-5.3 and Music Printing write in
Tektronix alpha mode (music notation note heads `O` and `O` BS `#`, labels,
Music Printing's text).
