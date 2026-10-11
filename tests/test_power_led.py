import importlib
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "firmware"))
from power_led import PowerIndicator
from test_status import Pin


class Timer:
    PERIODIC = 1
    def __init__(self, identifier=-1):
        self.identifier = identifier
    def init(self, **settings):
        self.settings = settings
    def fire(self):
        self.settings["callback"](self)


class PowerLedTests(unittest.TestCase):
    def setUp(self):
        self.pwr, self.vbus, self.charge = Pin(0), Pin(1), Pin(0)
        self.timer = Timer()
        self.indicator = PowerIndicator(self.pwr, self.vbus, self.charge, self.timer)

    def test_active_work_is_steady_on_even_while_charging_or_on_battery(self):
        for usb, charge in ((1, 0), (1, 1), (0, 0), (0, 1)):
            self.vbus.value(usb)
            self.charge.value(charge)
            for _ in range(10):
                self.timer.fire()
                self.assertEqual(self.pwr.value(), 1)

    def test_idle_charge_blinks_at_one_hertz_and_work_interrupts_it_immediately(self):
        self.assertEqual(self.timer.settings["period"], 500)
        self.assertFalse(self.timer.settings["hard"])
        self.indicator.set_working(False)
        levels = [self.pwr.value()]
        for _ in range(4):
            self.timer.fire()
            levels.append(self.pwr.value())
        self.assertEqual(levels, [1, 0, 1, 0, 1])
        self.timer.fire()
        self.assertEqual(self.pwr.value(), 0)
        self.indicator.set_working(True)
        self.assertEqual(self.pwr.value(), 1)  # No wait for the next timer tick.
        self.timer.fire()
        self.assertEqual(self.pwr.value(), 1)

    def test_repeated_idle_updates_do_not_speed_up_or_restart_blink(self):
        self.indicator.set_working(False)
        for _ in range(100):
            self.indicator.set_working(False)
            self.assertEqual(self.pwr.value(), 1)
        self.timer.fire()
        for _ in range(100):
            self.indicator.set_working(False)
            self.assertEqual(self.pwr.value(), 0)

    def test_idle_full_charge_usb_removal_and_reconnection(self):
        self.indicator.set_working(False)
        self.charge.value(1)
        for _ in range(3):
            self.timer.fire()
            self.assertEqual(self.pwr.value(), 0)
        self.charge.value(0)
        self.vbus.value(0)
        self.timer.fire()
        self.assertEqual(self.pwr.value(), 0)  # CHARGE alone is insufficient.
        self.vbus.value(1)
        self.timer.fire()
        self.assertEqual(self.pwr.value(), 1)
        self.timer.fire()
        self.assertEqual(self.pwr.value(), 0)

    def test_real_board_shares_startup_indicator_and_extinguishes_before_cutoff(self):
        pins = {}
        class MachinePin(Pin):
            IN, OUT, PULL_UP, IRQ_FALLING = 0, 1, 2, 4
            def __new__(cls, identifier, *args, **kwargs):
                if identifier not in pins:
                    pins[identifier] = super().__new__(cls)
                return pins[identifier]
            def __init__(self, identifier, mode=None, pull=None, value=None):
                if not hasattr(self, "level"):
                    super().__init__(int(pull == self.PULL_UP))
                if value is not None:
                    self.value(value)
        machine = types.SimpleNamespace(Pin=MachinePin, Timer=Timer,
                                        ADC=lambda pin: None, I2C=lambda *a, **kw: None,
                                        SPI=lambda *a, **kw: None)
        with patch.dict(sys.modules, {"machine": machine}):
            board_module = importlib.import_module("board")
            indicator = PowerIndicator.for_hardware()
            self.assertEqual(indicator.timer.identifier, -1)
            board = board_module.Board(power_indicator=indicator)
            self.assertIs(board.power_led, pins[26])
            self.assertIs(board.power_indicator, indicator)
            self.assertEqual(pins[26].value(), 1)
            board.set_working(False)
            self.assertEqual(pins[26].value(), 0)
            board.set_working(True)
            levels = []
            def wait(delay):
                levels.append((pins[18].value(), pins[26].value()))
                indicator.timer.fire()
                levels.append((pins[18].value(), pins[26].value()))
            with patch.object(board_module, "time", types.SimpleNamespace(sleep_ms=wait)), \
                    patch.object(board_module.os, "sync", lambda: None):
                with self.assertRaisesRegex(OSError, "power latch"):
                    board.power_off()
            self.assertEqual(levels, [(0, 0), (0, 0)])
            self.assertFalse(indicator.working)
            # USB prevents cutoff; charge blinking remains available in idle.
            pins[24].value(1)
            pins[17].value(0)
            board.set_working(True)
            self.assertFalse(board.power_off())
            self.assertEqual(pins[26].value(), 1)
            board.set_working(False)
            self.assertEqual(pins[26].value(), 1)
            indicator.timer.fire()
            self.assertEqual(pins[26].value(), 0)
