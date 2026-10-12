import importlib
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "firmware"))
from activity_led import ActivityIndicator, IndicatedBlockDevice
from test_status import Clock, Pin
from test_power_led import Timer


class ActivityLedTests(unittest.TestCase):
    def setUp(self):
        self.clock, self.pin, self.timer = Clock(), Pin(), Timer()
        self.activity = ActivityIndicator(self.pin, self.timer, self.clock)

    def test_card_blink_and_idle_off(self):
        self.assertEqual(self.pin.value(), 0)
        self.assertEqual(self.timer.settings["period"], 100)
        self.assertFalse(self.timer.settings["hard"])
        self.activity.card_begin()
        levels = [self.pin.value()]
        for _ in range(4):
            self.clock.now += 100
            self.timer.fire()
            levels.append(self.pin.value())
        self.assertEqual(levels, [1, 0, 1, 0, 1])
        self.activity.card_end()
        for _ in range(4):
            self.clock.now += 100
            self.timer.fire()
            self.assertEqual(self.pin.value(), 0)

    def test_short_sector_reads_share_a_blink_cycle_and_long_idle_restarts_it(self):
        self.activity.card_begin()
        self.assertEqual(self.pin.value(), 1)
        self.clock.now += 90
        self.activity.card_end()
        self.clock.now += 20
        self.activity.card_begin()
        self.assertEqual(self.pin.value(), 0)  # Do not light every short read solid.
        self.clock.now += 90
        self.timer.fire()
        self.assertEqual(self.pin.value(), 0)
        self.clock.now += 10
        self.timer.fire()
        self.assertEqual(self.pin.value(), 1)
        self.activity.card_end()
        self.clock.now += 5000
        self.activity.card_begin()
        self.assertEqual(self.pin.value(), 1)
        self.activity.card_end()
        self.assertEqual(self.pin.value(), 0)

    def test_nested_card_io_and_refresh_priority(self):
        self.activity.card_begin()
        self.activity.card_begin()
        self.activity.card_end()
        self.assertEqual(self.activity.card_depth, 1)
        self.clock.now += 100
        self.timer.fire()
        self.assertEqual(self.pin.value(), 0)
        self.activity.set_refreshing(True)
        for _ in range(6):
            self.clock.now += 100
            self.timer.fire()
            self.assertEqual(self.pin.value(), 1)
        self.activity.card_end()
        self.assertEqual(self.pin.value(), 1)
        self.activity.set_refreshing(False)
        self.assertEqual(self.pin.value(), 0)

    def test_blink_survives_tick_wrap(self):
        self.clock.now = (1 << 30) - 50
        self.activity = ActivityIndicator(self.pin, self.timer, self.clock)
        self.activity.card_begin()
        self.clock.now += 100
        self.timer.fire()
        self.assertEqual(self.pin.value(), 0)
        self.clock.now += 100
        self.timer.fire()
        self.assertEqual(self.pin.value(), 1)
        self.activity.card_end()
        self.assertEqual(self.pin.value(), 0)

    def test_block_reads_writes_and_errors_always_release_activity(self):
        outer = self
        class Device:
            fail = False
            def readblocks(self, block, buffer):
                outer.assertEqual(outer.activity.card_depth, 1)
                outer.assertEqual(outer.pin.value(), 1)
                if self.fail:
                    raise OSError("card failure")
                buffer[:] = b"\x55" * len(buffer)
                return 0
            def writeblocks(self, block, buffer):
                return self.readblocks(block, buffer)
            def ioctl(self, operation, argument):
                outer.assertEqual(outer.activity.card_depth, 0)
                return 512 if operation == 5 else 1024
        wrapped = IndicatedBlockDevice(Device(), self.activity)
        buffer = bytearray(512)
        for method in (wrapped.readblocks, wrapped.writeblocks):
            for fail in (False, True):
                wrapped.device.fail = fail
                if fail:
                    with self.assertRaisesRegex(OSError, "card failure"):
                        method(7, buffer)
                else:
                    self.assertEqual(method(7, buffer), 0)
                    self.assertEqual(buffer, b"\x55" * 512)
                self.assertEqual(self.activity.card_depth, 0)
                self.assertEqual(self.pin.value(), 0)
        self.assertEqual(wrapped.ioctl(5, 0), 512)
        self.assertEqual(wrapped.ioctl(4, 0), 1024)

    def test_real_board_wraps_mount_and_card_initialization_failure(self):
        class MachinePin(Pin):
            IN, OUT, PULL_UP, IRQ_FALLING, IRQ_RISING = 0, 1, 2, 4, 8
            def __init__(self, identifier, *args, **kwargs):
                super().__init__(kwargs.get("value", 1))
        machine = types.SimpleNamespace(Pin=MachinePin, ADC=lambda pin: None,
                                        I2C=lambda *a, **kw: None, SPI=lambda *a, **kw: None,
                                        Timer=Timer)
        class Device:
            def readblocks(self, block, buffer): return 0
            def writeblocks(self, block, buffer): return 0
            def ioctl(self, operation, argument): return 1024
        def mount(device, path):
            self.assertEqual(path, "/sd")
            self.assertIsInstance(device, IndicatedBlockDevice)
            self.assertEqual(self.activity.card_depth, 1)
            device.readblocks(0, bytearray(512))
            device.writeblocks(0, bytearray(512))
            self.assertEqual(self.activity.card_depth, 1)
        modules = {"machine": machine, "sdcard": types.SimpleNamespace(SDCard=lambda *a, **kw: Device()),
                   "vfs": types.SimpleNamespace(VfsFat=lambda device: device, mount=mount)}
        with patch.dict(sys.modules, modules):
            board_module = importlib.import_module("board")
            board = board_module.Board()
            board.activity_indicator = self.activity
            board.mount_sd()
            self.assertIs(board.sd.activity, self.activity)
            self.assertEqual(self.activity.card_depth, 0)
            self.assertEqual(self.pin.value(), 0)
            def failure(*args, **kwargs): raise OSError("no card")
            modules["sdcard"].SDCard = failure
            with self.assertRaisesRegex(OSError, "no card"):
                board.mount_sd()
            self.assertEqual(self.activity.card_depth, 0)
            self.assertEqual(self.pin.value(), 0)
