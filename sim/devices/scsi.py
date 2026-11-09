"""D24 SCSI host adaptor (devices 024-027) and a SCSI disk target (M7.3).

Evidence (NED source, MIT, jbemond/Software, Release 5.3 tree):
  * -XPL:SCSILITS: D24 = selection port (write with S$SelectEnable 10000 and
    board bits 7400 to select a D24; read back the select bits, revision in
    bits 15-13) and data port (bits 7-0: the SCSI data bus); D25 = signal
    bus (ATN 1, BSY 2, ACK 4, RST 10, MSG 20, SEL 40, C/D 100, REQ 200, I/O
    400; arbitrate bits 1000/5000; interrupt bits 7000); D26 = read/write
    one byte with the REQ/ACK handshake; D27 = two bytes as a word, first
    byte in bits 15-8. D51 bit 40000 is set when a D24 is present.
  * LOADER:SCSILOAD (the Winchester boot program) uses it all: wait for bus
    free on D25, assert BSY and ID 6 (100) on D24, check that ID 7 (200) is
    not on the bus, assert SEL, put ID 6 + target bit on D24, assert ATN,
    release BSY, wait for the target's BSY, release SEL, wait for REQ,
    release ATN, send IDENTIFY (200 + LUN) with D26, then the 10-byte
    EXTENDED READ (D26 opcode 50, D26 LUN, D27 LBA high, D27 LBA low, D26
    0, D27 count, D26 control), then reads the data phase with D27 (256
    per sector) and the status/message pair with one D27 read (status in
    bits 11-8, STAMSK 7400).

  * MONITOR 5.3 (SCSI data-in) reads 255 words with D27 and one byte with
    D26, then takes the last byte by hand: D24 read (the byte the target
    is driving), ACK asserted with D25, wait for REQ to drop, ACK released.

Model: the initiator's D24 data bits and D25 signal bits are latched; the
target's signals (BSY, MSG, C/D, I/O, REQ) follow the bus phase. D25 reads
the OR of both, without REQ while the initiator holds ACK. D24 reads the
initiator's data bits OR, in a target-driven phase (data in, status,
message in), the byte the target is offering. A D26/D27 transfer completes
at once (the target always answers REQ); one with no REQ on the bus reads
377 and is otherwise ignored. ACK asserted by hand on D25 while REQ is up
completes one byte: the target's byte is consumed, or D24's byte is taken
in an initiator-driven phase. Selection happens on the D25 write that leaves SEL asserted and
BSY released with the target's bit on the data bus. Commands: TEST UNIT
READY, REZERO, REQUEST SENSE, READ(6/10), WRITE(6/10), SEEK, INQUIRY, MODE
SELECT, RESERVE, RELEASE, MODE SENSE, START/STOP, PREVENT/ALLOW, READ
CAPACITY, VERIFY; others give CHECK CONDITION, ILLEGAL REQUEST.
Blocks are 512 bytes = one 256-word NED sector; the image file is the
sectors in order with big-endian words (a `.simg`), so SCSI bytes are the
file's bytes.
"""
from ..bus import Device

BLOCK = 512

ATN, BSY, ACK, RST, MSG, SEL, CD, REQ, IO = 1, 2, 4, 0o10, 0o20, 0o40, 0o100, 0o200, 0o400
SIGNALS = 0o777

FREE, MSG_OUT, COMMAND, DATA_IN, DATA_OUT, STATUS, MSG_IN = range(7)
PHASE_SIGNALS = {
    FREE: 0,
    MSG_OUT: BSY | MSG | CD | REQ,
    COMMAND: BSY | CD | REQ,
    DATA_IN: BSY | IO | REQ,
    DATA_OUT: BSY | REQ,
    STATUS: BSY | CD | IO | REQ,
    MSG_IN: BSY | MSG | CD | IO | REQ,
}

GOOD, CHECK_CONDITION = 0x00, 0x02


class ScsiDisk:
    """A direct-access SCSI target on an image file (or bytes)."""

    def __init__(self, data, read_only=False):
        self.data = bytearray(data)
        if len(self.data) % BLOCK:
            self.data.extend(bytes(BLOCK - len(self.data) % BLOCK))
        self.read_only = read_only
        self.sense_key = 0
        self.writes = 0

    @classmethod
    def from_file(cls, path, read_only=False):
        with open(path, "rb") as f:
            return cls(f.read(), read_only)

    @property
    def blocks(self):
        return len(self.data) // BLOCK

    def execute(self, cdb):
        """Run a command. Returns (status, data_in bytes, data_out length,
        completion for data out or None)."""
        op = cdb[0]
        self.last_sense, self.sense_key = self.sense_key, 0
        if op in (0x00, 0x01, 0x0B, 0x16, 0x17, 0x1B, 0x1E, 0x2F):
            return GOOD, b"", 0, None
        if op == 0x03:                                     # REQUEST SENSE
            n = cdb[4] or 4
            sense = bytearray(18)
            sense[0], sense[2], sense[7] = 0x70, self.last_sense, 10
            return GOOD, bytes(sense[:n]), 0, None
        if op == 0x12:                                     # INQUIRY
            n = cdb[4]
            inq = bytearray(36)
            inq[2], inq[3], inq[4] = 1, 1, 31
            inq[8:16] = b"MiSTer  "
            inq[16:32] = b"SYNCLAVIER W0   "
            inq[32:36] = b"1.0 "
            return GOOD, bytes(inq[:n]), 0, None
        if op == 0x25:                                     # READ CAPACITY
            last = self.blocks - 1
            return GOOD, last.to_bytes(4, "big") + BLOCK.to_bytes(4, "big"), 0, None
        if op == 0x1A:                                     # MODE SENSE(6)
            n = cdb[4]
            page = bytearray(12)
            page[0], page[3] = 11, 8
            page[5:8] = self.blocks.to_bytes(3, "big")
            page[9:12] = BLOCK.to_bytes(3, "big")
            return GOOD, bytes(page[:n]), 0, None
        if op == 0x15:                                     # MODE SELECT(6)
            return GOOD, b"", cdb[4], lambda data: GOOD
        if op in (0x08, 0x0A, 0x28, 0x2A):
            if op in (0x08, 0x0A):
                lba = ((cdb[1] & 0x1F) << 16) | (cdb[2] << 8) | cdb[3]
                n = cdb[4] or 256
            else:
                lba = int.from_bytes(cdb[2:6], "big")
                n = int.from_bytes(cdb[7:9], "big")
            if lba + n > self.blocks:
                return self._check(0x05)
            a, b = lba * BLOCK, (lba + n) * BLOCK
            if op in (0x08, 0x28):
                return GOOD, bytes(self.data[a:b]), 0, None
            if self.read_only:
                return self._check(0x07)                   # DATA PROTECT

            def done(data, a=a, b=b):
                self.data[a:b] = data[:b - a]
                self.writes += 1
                return GOOD
            return GOOD, b"", b - a, done
        return self._check(0x05)                           # ILLEGAL REQUEST

    def _check(self, key):
        self.sense_key = key
        return CHECK_CONDITION, b"", 0, None


class ScsiHost(Device):
    """D24 board 0 (devices 024-027) with targets {scsi id: ScsiDisk}."""

    numbers = (0o24, 0o25, 0o26, 0o27)

    def __init__(self, targets=None, initiator=6):
        self.targets = dict(targets or {})
        self.initiator = initiator
        self.select_bits = 0     # D24 board select bits (7400) after a select write
        self.data_out = 0        # initiator's data bus
        self.sig_out = 0         # initiator's signals
        self.acked = False       # ACK asserted by hand on D25 (REQ hidden)
        self._free()
        self.log = []            # (target, cdb) of each command, for tests

    def _free(self):
        self.phase = FREE
        self.target = None
        self.cdb = bytearray()
        self.data_in = b""
        self.out_len = 0
        self.out_buf = bytearray()
        self.out_done = None
        self.status = GOOD

    # ----------------------------------------------------------- registers

    def read(self, dev):
        if dev == 0o24:
            return self.select_bits | (self.data_out & 0o377) | self._peek()
        if dev == 0o25:
            sig = PHASE_SIGNALS[self.phase]
            if self.acked:
                sig &= ~REQ
            return (self.sig_out | sig) & SIGNALS
        if dev == 0o26:
            return self._get()
        hi = self._get()
        return (hi << 8) | self._get()

    def write(self, dev, value):
        if dev == 0o24:
            if value & 0o10000:                  # select a D24 board
                self.select_bits = value & 0o400  # only board 0 exists
            else:
                self.data_out = value & 0o377
        elif dev == 0o25:
            ack_edge = (value & ACK) and not (self.sig_out & ACK)
            self.sig_out = value & SIGNALS
            if value & RST:
                self._free()
            elif self.phase == FREE:
                self._selection()
            elif ack_edge and not self.acked:
                if self.phase in (DATA_IN, STATUS, MSG_IN):
                    self._get()
                else:
                    self._put(self.data_out)
                self.acked = True
            if not value & ACK:
                self.acked = False
        elif dev == 0o26:
            self._put(value & 0o377)
        else:
            self._put((value >> 8) & 0o377)
            self._put(value & 0o377)
        return True

    # ------------------------------------------------------------ the bus

    def _selection(self):
        if (self.sig_out & SEL) and not (self.sig_out & BSY):
            for tid, disk in self.targets.items():
                if self.data_out & (1 << tid):
                    self.target = disk
                    self.target_id = tid
                    self.phase = MSG_OUT if self.sig_out & ATN else COMMAND
                    return

    def _put(self, b):
        if self.phase == MSG_OUT:
            if b & 0x80:                         # IDENTIFY
                self.phase = COMMAND
            elif b in (0x06, 0x0C):              # ABORT, BUS DEVICE RESET
                self._free()
        elif self.phase == COMMAND:
            self.cdb.append(b)
            group = self.cdb[0] >> 5
            need = 6 if group == 0 else 10 if group in (1, 2) else 12
            if len(self.cdb) == need:
                self._execute()
        elif self.phase == DATA_OUT:
            self.out_buf.append(b)
            if len(self.out_buf) == self.out_len:
                self.status = self.out_done(bytes(self.out_buf))
                self.phase = STATUS

    def _peek(self):
        """The byte the target drives onto the data bus (0 if none)."""
        if self.phase == DATA_IN:
            return self.data_in[self.pos]
        if self.phase == STATUS:
            return self.status
        return 0

    def _get(self):
        if self.phase == DATA_IN:
            b = self.data_in[self.pos]
            self.pos += 1
            if self.pos == len(self.data_in):
                self.phase = STATUS
            return b
        if self.phase == STATUS:
            self.phase = MSG_IN
            return self.status
        if self.phase == MSG_IN:
            self._free()
            return 0x00                          # COMMAND COMPLETE
        return 0o377

    def _execute(self):
        cdb = bytes(self.cdb)
        self.log.append((self.target_id, cdb))
        status, data, out_len, done = self.target.execute(cdb)
        self.status = status
        if data:
            self.data_in, self.pos = data, 0
            self.phase = DATA_IN
        elif out_len:
            self.out_len, self.out_buf, self.out_done = out_len, bytearray(), done
            self.phase = DATA_OUT
        else:
            self.phase = STATUS
