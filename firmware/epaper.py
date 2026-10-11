"""MicroPython port of Waveshare EPD_7in3e.c, normal full-refresh sequence.

Adapted from Waveshare team, MIT notice in ../licenses/waveshare-MIT.txt.
Source commit: fc2b261e985934bf67d99aa26358e463deb0aa65.
"""
import time

WIDTH, HEIGHT = 800, 480
FRAME_BYTES = WIDTH * HEIGHT // 2
INIT = (
    (0xAA, b"\x49\x55\x20\x08\x09\x18"),
    (0x01, b"\x3f"), (0x00, b"\x5f\x69"),
    (0x03, b"\x00\x54\x00\x44"), (0x05, b"\x40\x1f\x1f\x2c"),
    (0x06, b"\x6f\x1f\x17\x49"), (0x08, b"\x6f\x1f\x1f\x22"),
    (0x30, b"\x03"), (0x50, b"\x3f"), (0x60, b"\x02\x00"),
    (0x61, b"\x03\x20\x01\xe0"), (0x84, b"\x01"), (0xE3, b"\x2f"),
)


class Epaper:
    def __init__(self, spi, cs, dc, reset, busy, power, timeout_ms=120000,
                 clock=None):
        self.spi, self.cs, self.dc = spi, cs, dc
        self.reset, self.busy, self.power = reset, busy, power
        self.timeout_ms = timeout_ms
        self.clock = clock or time
        self.cs.value(1)

    @classmethod
    def for_board(cls, board):
        from machine import Pin, SPI
        spi = SPI(1, baudrate=8000000, polarity=0, phase=0,
                  sck=Pin(10), mosi=Pin(11), miso=Pin(28))
        return cls(spi, Pin(9, Pin.OUT, value=1), Pin(8, Pin.OUT),
                   Pin(12, Pin.OUT, value=1), Pin(13, Pin.IN), board.screen_power)

    def _write(self, data, is_data):
        self.dc.value(is_data)
        self.cs.value(0)
        try:
            self.spi.write(data)
        finally:
            self.cs.value(1)

    def command(self, command, data=None):
        self._write(bytes((command,)), 0)
        if data is not None:
            self._write(data, 1)

    def wait_idle(self, require_busy=False):
        clock = self.clock
        started = clock.ticks_ms()
        if require_busy:
            while self.busy.value():
                if clock.ticks_diff(clock.ticks_ms(), started) >= 1000:
                    raise OSError("EPD BUSY did not assert after refresh")
                clock.sleep_ms(1)
        else:
            clock.sleep_ms(10)
        while not self.busy.value():
            if clock.ticks_diff(clock.ticks_ms(), started) >= self.timeout_ms:
                raise OSError("EPD BUSY timeout")
            clock.sleep_ms(10)

    def initialize(self):
        self.power.value(1)
        self.clock.sleep_ms(50)
        for level, delay in ((1, 20), (0, 2), (1, 20)):
            self.reset.value(level)
            self.clock.sleep_ms(delay)
        self.wait_idle()
        self.clock.sleep_ms(30)
        for command, data in INIT:
            self.command(command, data)
        self.command(0x04)
        self.wait_idle()

    def display(self, frame):
        if len(frame) != FRAME_BYTES:
            raise ValueError("EPD frame must be exactly 192000 bytes")
        self.initialize()
        self.command(0x10)
        view = memoryview(frame)
        for offset in range(0, len(view), 4096):
            self._write(view[offset:offset + 4096], 1)
        self.command(0x04)
        self.wait_idle()
        self.command(0x06, b"\x6f\x1f\x17\x49")
        self.command(0x12, b"\x00")
        self.wait_idle(require_busy=True)
        self.command(0x02, b"\x00")
        self.wait_idle()
        self.command(0x07, b"\xa5")
        self.clock.sleep_ms(10)
        self.power.value(0)
