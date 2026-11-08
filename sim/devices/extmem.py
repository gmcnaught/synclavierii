"""D60-D63 external memory interface (docs/boot-and-loaders.md section 3).

Evidence: NED's FLPLOAD, WINLOAD and SCSILOAD loaders (MIT).
  * D60 = sector address, read/write. SCSILOAD even parks an unrelated value
    in D60 and reads it back ("STORE IN D60 TEMPORARILY"), so it holds 16 bits.
  * D61 = word pointer within the 256-word (400 octal) sector, read/write.
  * D63 = data port. Each read or write moves to the next word, carrying
    from D61 into D60: the loaders copy whole tracks and swap files through
    D63 after setting D60 once, then read D60/D61 to find where they ended.
  * Writing D60 starts at word 0 of that sector ("R0 to D60 send starting
    sector number", then D63 reads the sector from its start).
  * D62 exists (XPL-to-C translator has _read_62/_write_62) but its function
    is unknown, so it is not modelled: accessing it halts the CPU.
"""
from array import array

from ..bus import Device

SECTOR_WORDS = 256


class ExternalMemory(Device):
    numbers = (0o60, 0o61, 0o63)

    def __init__(self, sectors=1024):
        """sectors: size in 256-word sectors (1024 = 256K words = 512 KB)."""
        if not 0 < sectors <= 0x10000:
            raise ValueError("sectors must be 1..65536")
        self.sectors = sectors
        self.data = array("H", bytes(2 * sectors * SECTOR_WORDS))
        self.sector = 0
        self.word = 0

    def _advance(self):
        self.word = (self.word + 1) & 0o377
        if self.word == 0:
            self.sector = (self.sector + 1) & 0xFFFF

    def _index(self):
        # CHOICE: addresses beyond the installed memory read as 0 and ignore
        # writes (no evidence for wrap-around or a bus error).
        if self.sector >= self.sectors:
            return None
        return self.sector * SECTOR_WORDS + self.word

    def read(self, dev):
        if dev == 0o60:
            return self.sector
        if dev == 0o61:
            return self.word
        i = self._index()
        v = 0 if i is None else self.data[i]
        self._advance()
        return v

    def write(self, dev, value):
        if dev == 0o60:
            self.sector = value & 0xFFFF
            self.word = 0
        elif dev == 0o61:
            self.word = value & 0o377
        else:
            i = self._index()
            if i is not None:
                self.data[i] = value & 0xFFFF
            self._advance()
        return True

    # host-side helpers
    def load(self, sector, words):
        base = sector * SECTOR_WORDS
        for i, w in enumerate(words):
            self.data[base + i] = w & 0xFFFF

    def dump(self, sector, count):
        base = sector * SECTOR_WORDS
        return list(self.data[base:base + count])


