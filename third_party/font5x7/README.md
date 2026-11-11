# 5x7 font (public domain)

`5x7-ascii.bdf` is the ASCII 32–126 subset of `5x7.bdf` from the X.Org
"misc-misc" fonts (`https://gitlab.freedesktop.org/xorg/font/misc-misc`,
file `5x7.bdf`, header: `COPYRIGHT "Public domain font. Share and enjoy."`,
`$ucs-fonts: 5x7.bdf,v 1.38 2006-01-05 mgk25`).

`tools/gen_font.py` turns it into `hdl/core/font5x7.svh` and the Python
VT640 model's glyphs: the characters SYN-5.3 writes in Tektronix alpha mode
(music notation note heads `o` and `#`, labels).
