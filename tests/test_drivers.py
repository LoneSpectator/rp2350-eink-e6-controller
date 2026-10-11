from pathlib import Path
import contextlib
import io
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "firmware"))
from epaper import Epaper, FRAME_BYTES
from rtc import PCF85063
from app import shut_down
from activity_led import ActivityIndicator


class I2C:
    def __init__(self):
        self.registers = bytearray(32)

    def readfrom_mem(self, address, register, count):
        assert address == 0x51
        return bytes(self.registers[register:register + count])

    def writeto_mem(self, address, register, data):
        assert address == 0x51
        self.registers[register:register + len(data)] = data


class RtcTests(unittest.TestCase):
    def setUp(self):
        self.bus = I2C()
        self.rtc = PCF85063(self.bus)
        self.value = (2026, 12, 31, 23, 59, 58)

    def test_set_and_read_real_time(self):
        self.assertEqual(self.rtc.set_time(self.value), self.value)
        self.assertEqual(list(self.bus.registers[4:11]), [0x58, 0x59, 0x23, 0x31, 4, 0x12, 0x26])

    def test_invalid_rtc_is_not_reset(self):
        self.bus.registers[4] = 0x80
        before = bytes(self.bus.registers)
        with self.assertRaises(ValueError):
            self.rtc.read_time()
        self.assertEqual(before, bytes(self.bus.registers))

    def test_invalid_bcd_and_stopped_clock(self):
        self.rtc.set_time(self.value)
        self.bus.registers[5] = 0x6F
        with self.assertRaises(ValueError):
            self.rtc.read_time()
        self.rtc.set_time(self.value)
        self.bus.registers[0] |= 0x20
        with self.assertRaises(ValueError):
            self.rtc.read_time()

    def test_alarm_enable_clear_and_disable(self):
        self.bus.registers[1] = 0x41
        self.rtc.set_alarm((2027, 1, 1, 0, 0, 0))
        self.assertEqual(list(self.bus.registers[11:16]), [0, 0, 0, 1, 0x80])
        self.assertEqual(self.bus.registers[1], 0x81)
        self.bus.registers[1] |= 0x40
        self.rtc.clear_alarm()
        self.assertEqual(self.bus.registers[1], 0x81)
        self.rtc.disable_alarm()
        self.assertEqual(self.bus.registers[1], 1)


class Clock:
    def __init__(self):
        self.now = 0

    def ticks_ms(self):
        return self.now

    def ticks_diff(self, a, b):
        return a - b

    def sleep_ms(self, delay):
        self.now += delay


class Pin:
    def __init__(self, value=1):
        self.level = value

    def value(self, value=None):
        if value is not None:
            self.level = value
        return self.level


class Busy:
    def __init__(self, clock):
        self.clock = clock
        self.until = 0

    def value(self):
        return int(self.clock.now >= self.until)


class SPI:
    def __init__(self, dc, busy):
        self.dc, self.busy = dc, busy
        self.writes = []

    def write(self, data):
        self.writes.append((self.dc.value(), bytes(data)))
        if self.dc.value() == 0 and data == b"\x12":
            self.busy.until = self.busy.clock.now + 300


class EpaperTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.cs, self.dc, self.reset, self.power = Pin(), Pin(), Pin(), Pin(0)
        self.busy = Busy(self.clock)
        self.spi = SPI(self.dc, self.busy)
        self.activity_pin = Pin(0)
        self.activity = ActivityIndicator(self.activity_pin, clock=self.clock)
        self.screen = Epaper(self.spi, self.cs, self.dc, self.reset, self.busy, self.power,
                             timeout_ms=1000, clock=self.clock, activity=self.activity)

    def test_frame_transfer_refresh_and_sleep(self):
        frame = bytes((0x01,)) * FRAME_BYTES
        output = io.StringIO()
        original_sleep = self.clock.sleep_ms
        def sleep(delay):
            self.assertTrue(self.activity.refreshing)
            self.activity.card_begin()  # Logging may read/write during a refresh.
            self.activity.tick()
            self.assertEqual(self.activity_pin.value(), 1)
            self.activity.card_end()
            original_sleep(delay)
        self.clock.sleep_ms = sleep
        with contextlib.redirect_stdout(output):
            self.screen.display(frame)
        self.assertIn("[timing] panel_refresh: 300 ms", output.getvalue())
        index = self.spi.writes.index((0, b"\x10"))
        packets = []
        for kind, value in self.spi.writes[index + 1:]:
            if kind == 0:
                break
            packets.append(value)
        self.assertEqual(b"".join(packets), frame)
        self.assertIn((0, b"\x12"), self.spi.writes)
        self.assertEqual(self.spi.writes[-2:], [(0, b"\x07"), (1, b"\xa5")])
        self.assertEqual(self.power.value(), 0)
        self.assertEqual(self.cs.value(), 1)
        self.assertEqual(self.activity_pin.value(), 0)
        self.assertFalse(self.activity.refreshing)

    def test_invalid_frame_does_not_power_screen(self):
        with self.assertRaises(ValueError):
            self.screen.display(b"short")
        self.assertEqual(self.power.value(), 0)
        self.assertEqual(self.activity_pin.value(), 0)

    def test_busy_stuck_low_times_out(self):
        self.busy.until = 100000
        with self.assertRaisesRegex(OSError, "timeout"):
            self.screen.wait_idle()

    def test_busy_never_asserts_detected(self):
        with self.assertRaisesRegex(OSError, "did not assert"):
            self.screen.wait_idle(require_busy=True)

    def test_spi_failure_releases_cs(self):
        def failure(data):
            raise OSError("SPI failure")
        self.spi.write = failure
        with self.assertRaises(OSError):
            self.screen.command(0x10)
        self.assertEqual(self.cs.value(), 1)

    def test_refresh_failure_or_interrupt_extinguishes_act_and_cuts_screen_power(self):
        for mode in ("spi", "busy", "interrupt"):
            with self.subTest(mode=mode):
                if mode == "busy":
                    self.busy.until = 100000
                else:
                    def failure(data):
                        self.assertTrue(self.activity.refreshing)
                        self.assertEqual(self.activity_pin.value(), 1)
                        if mode == "interrupt": raise KeyboardInterrupt
                        raise OSError("SPI failure")
                    self.spi.write = failure
                expected = KeyboardInterrupt if mode == "interrupt" else OSError
                with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(expected):
                    self.screen.display(bytes(FRAME_BYTES))
                self.assertEqual(self.activity_pin.value(), 0)
                self.assertFalse(self.activity.refreshing)
                self.assertEqual(self.power.value(), 0)
                self.assertEqual(self.cs.value(), 1)
                self.setUp()


class ShutdownTests(unittest.TestCase):
    def test_next_press_before_cutoff_keeps_power_for_status(self):
        class Board:
            rtc_int = Pin(1)
            def set_working(self, working): pass
            class next_button:
                @staticmethod
                def pressed(): return True
            def usb(self): return False
            def sync(self): pass
            def power_off(self): raise AssertionError("NEXT press lost at power-off")
        rtc = PCF85063(I2C())
        rtc.set_time((2026, 10, 11, 9, 0, 0))
        self.assertFalse(shut_down(Board(), rtc, (2026, 10, 11, 10, 0, 0)))
        self.assertFalse(rtc.i2c.registers[1] & 0x80)

    def test_never_power_off_on_past_alarm_or_low_int(self):
        class Board:
            rtc_int = Pin(0)
            def set_working(self, working): pass
            def usb(self): return False
            def sync(self): pass
            def power_off(self): raise AssertionError("unsafe power-off")
        bus = I2C()
        rtc = PCF85063(bus)
        rtc.set_time((2026, 10, 11, 9, 0, 0))
        with self.assertRaises(OSError):
            shut_down(Board(), rtc, (2026, 10, 11, 10, 0, 0))
        Board.rtc_int = Pin(1)
        with self.assertRaises(OSError):
            shut_down(Board(), rtc, (2026, 10, 11, 8, 0, 0))
