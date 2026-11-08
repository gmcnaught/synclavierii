"""I/O bus and device interface.

Codes 000-177 on the internal address bus select I/O devices. A device that
is not present never returns SYN, so the real machine hangs; the simulator
halts the CPU and reports the device number (docs/plan.md section 3).

Device 001 (PSW/PCW) is part of the CPU and never reaches the bus.
"""

NO_SYN = None  # returned by a read when no device answers


class Device:
    """Base class for I/O devices.

    A device may answer several device numbers (for example D4567 serves
    004-007); it receives the number it was addressed by.
    """

    #: device numbers this device answers to
    numbers = ()

    def read(self, dev):
        """Return a 16-bit value, or NO_SYN."""
        return NO_SYN

    def write(self, dev, value):
        """Accept a 16-bit value. Return False for NO_SYN."""
        return False

    def tick(self, ns):
        """Advance device time by ns nanoseconds."""

    def irq_bits(self):
        """PSW bits 4-15 this device is driving (0 = no interrupt request)."""
        return 0


class Bus:
    def __init__(self):
        self.devices = {}  # number -> Device
        self._unique = []

    def attach(self, device, numbers=None):
        numbers = device.numbers if numbers is None else numbers
        for n in numbers:
            if not 0 <= n < 0o200:
                raise ValueError("device number %o out of range" % n)
            if n == 1:
                raise ValueError("device 001 (PSW/PCW) belongs to the CPU")
            if n in self.devices:
                raise ValueError("device %o already attached" % n)
            self.devices[n] = device
        if device not in self._unique:
            self._unique.append(device)
        return device

    def read(self, dev):
        d = self.devices.get(dev)
        return NO_SYN if d is None else d.read(dev)

    def write(self, dev, value):
        d = self.devices.get(dev)
        return False if d is None else d.write(dev, value)

    def tick(self, ns):
        for d in self._unique:
            d.tick(ns)

    def irq_bits(self):
        bits = 0
        for d in self._unique:
            bits |= d.irq_bits()
        return bits & 0xFFF0
