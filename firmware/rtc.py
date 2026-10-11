"""PCF85063 calendar/alarm. Never resets a valid retained clock at boot."""
from calendar_time import days, validate, weekday


def bcd(value):
    return (value // 10) * 16 + value % 10


def decimal(value):
    if value & 15 > 9 or value >> 4 > 9:
        raise ValueError("invalid RTC BCD")
    return (value >> 4) * 10 + (value & 15)


class PCF85063:
    ADDRESS = 0x51

    def __init__(self, i2c):
        self.i2c = i2c

    def _read(self, register, count=1):
        return self.i2c.readfrom_mem(self.ADDRESS, register, count)

    def _write(self, register, value):
        data = bytes((value,)) if isinstance(value, int) else value
        self.i2c.writeto_mem(self.ADDRESS, register, data)

    def read_time(self):
        # One contiguous read avoids mixing date/time on a second rollover.
        data = self._read(0x04, 7)
        if data[0] & 0x80:
            raise ValueError("RTC oscillator-stop flag set; set real time over USB")
        if self._read(0)[0] & 0x20:
            raise ValueError("RTC is stopped; set real time over USB")
        value = (2000 + decimal(data[6]), decimal(data[5] & 0x1F),
                 decimal(data[3] & 0x3F), decimal(data[2] & 0x3F),
                 decimal(data[1] & 0x7F), decimal(data[0] & 0x7F))
        return validate(value)

    def set_time(self, value):
        y, m, d, h, minute, second = validate(tuple(value))
        self.disable_alarm()
        # Preserve the crystal capacitance selection, enter STOP while writing.
        control = self._read(0)[0] & 1
        self._write(0, control | 0x20)
        self._write(0x04, bytes((bcd(second), bcd(minute), bcd(h), bcd(d),
                                 weekday(days(y, m, d)), bcd(m), bcd(y - 2000))))
        self._write(0, control)
        return self.read_time()

    def clear_alarm(self):
        self._write(1, self._read(1)[0] & ~0x40)

    def disable_alarm(self):
        self._write(1, self._read(1)[0] & ~0xC0)

    def set_alarm(self, value):
        _, _, d, h, minute, second = validate(tuple(value))
        self.disable_alarm()
        # Seconds/minutes/hours/day compared; weekday comparison disabled.
        data = bytes((bcd(second), bcd(minute), bcd(h), bcd(d), 0x80))
        self._write(0x0B, data)
        if self._read(0x0B, 5) != data:
            raise OSError("RTC alarm register verification failed")
        self._write(1, (self._read(1)[0] & ~0x40) | 0x80)
        if not self._read(1)[0] & 0x80:
            raise OSError("RTC alarm enable verification failed")
