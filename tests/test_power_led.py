import contextlib
import importlib
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "firmware"))
from power_led import PowerIndicator
import app
import sign_log
from test_status import Clock, Pin


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

    def test_running_firmware_keeps_pwr_on_between_schedule_checks(self):
        for usb in (True, False):
            with self.subTest(usb=usb), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / "config.json").write_text(json.dumps({"battery_sleep": False}))
                (root / "cron").write_text("* * * * * /a.e6")
                (root / "a.e6").write_bytes(
                    struct.pack("<4sHHI4x", b"E6P1", 800, 480, 192000) + b"\x55" * 192000)
                clock = Clock()
                self.vbus.value(int(usb))
                indicator = self.indicator
                board = types.SimpleNamespace(
                    i2c=None, activity=Pin(0), screen_power=Pin(0), rtc_int=Pin(1),
                    next_button=types.SimpleNamespace(poll=lambda: None, pending=lambda: False),
                    usb=lambda: usb, battery_voltage=lambda: 3.75, mount_sd=lambda: None,
                    set_working=indicator.set_working)
                displays, reads, waits = [], [], []
                rtc = types.SimpleNamespace(
                    read_time=lambda: reads.append(clock.now) or (2026, 10, 11, 9, clock.now // 60000, 0),
                    disable_alarm=lambda: None)
                def sleep(delay):
                    self.assertTrue(indicator.working)
                    self.timer.fire()
                    self.assertEqual(self.pwr.value(), 1)
                    waits.append(clock.now)
                    clock.sleep_ms(delay)
                    if clock.now >= 60100:
                        raise KeyboardInterrupt
                runtime_clock = types.SimpleNamespace(sleep_ms=sleep, ticks_ms=clock.ticks_ms,
                                                      ticks_diff=clock.ticks_diff)
                modules = {"board": types.SimpleNamespace(Board=lambda: board),
                           "rtc": types.SimpleNamespace(PCF85063=lambda bus: rtc),
                           "epaper": types.SimpleNamespace(Epaper=types.SimpleNamespace(for_board=lambda b:
                               types.SimpleNamespace(display=lambda frame: displays.append(len(frame)))))}
                with patch.dict(sys.modules, modules), patch.object(app, "ROOT", temporary), \
                        patch.object(app, "time", runtime_clock), \
                        patch.object(sign_log, "LOG", sign_log.Logger()), \
                        contextlib.redirect_stdout(io.StringIO()):
                    app.run(bytearray(192000), rtc_wake=True)
                self.assertEqual(displays, [192000])  # Same content across the minute boundary.
                self.assertGreaterEqual(max(reads), 60000)
                self.assertGreater(len(waits), 600)
                self.assertFalse(indicator.working)  # Ctrl-C stops the application.
                indicator.set_working(True)

    def test_usb_startup_wait_is_lit_and_ctrl_c_enters_stopped_charging_mode(self):
        source = (Path(__file__).resolve().parents[1] / "firmware/main.py").read_text()
        for interrupted in (False, True):
            with self.subTest(interrupted=interrupted):
                self.indicator.set_working(True)
                calls = []
                def sleep(delay):
                    self.assertEqual(delay, 5000)
                    self.assertTrue(self.indicator.working)
                    for _ in range(10):
                        self.timer.fire()
                        self.assertEqual(self.pwr.value(), 1)
                    if interrupted:
                        raise KeyboardInterrupt
                def run(*args, **kwargs):
                    self.assertTrue(self.indicator.working)
                    self.assertIs(kwargs["power_indicator"], self.indicator)
                    calls.append(True)
                def machine_pin(*args, **kwargs):
                    return self.vbus
                machine_pin.IN = 0
                modules = {"framebuffer": types.SimpleNamespace(FRAME=None),
                           "machine": types.SimpleNamespace(Pin=machine_pin),
                           "time": types.SimpleNamespace(sleep_ms=sleep),
                           "app": types.SimpleNamespace(run=run)}
                with patch.dict(sys.modules, modules), \
                        patch.object(PowerIndicator, "for_hardware", return_value=self.indicator), \
                        contextlib.redirect_stdout(io.StringIO()):
                    if interrupted:
                        with self.assertRaises(KeyboardInterrupt):
                            exec(compile(source, "firmware/main.py", "exec"), {})
                    else:
                        exec(compile(source, "firmware/main.py", "exec"), {})
                self.assertEqual(calls, [] if interrupted else [True])
                self.assertFalse(self.indicator.working)
                self.timer.fire()
                self.assertEqual(self.pwr.value(), 0)  # Charging resumes blinking after exit.

    def test_real_board_shares_startup_indicator_and_extinguishes_before_cutoff(self):
        pins = {}
        class MachinePin(Pin):
            IN, OUT, PULL_UP, IRQ_FALLING, IRQ_RISING = 0, 1, 2, 4, 8
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
