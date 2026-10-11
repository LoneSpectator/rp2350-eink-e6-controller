import contextlib
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "firmware"))
import app
import sign_log
from calendar_time import from_seconds, to_seconds
from content import render_file
from status_page import NextButton, StatusSession, estimate_charge, status_text
from power_led import PowerIndicator


class Clock:
    def __init__(self, now=0):
        self.now = now
        self.stop = False

    def ticks_ms(self):
        return self.now % (1 << 30)

    def ticks_diff(self, a, b):
        return (a - b + (1 << 29)) % (1 << 30) - (1 << 29)

    def sleep_ms(self, delay):
        if self.stop:
            raise KeyboardInterrupt
        self.now += delay


class Pin:
    def __init__(self, level=1):
        self.level = level
        self.handler = None

    def value(self, level=None):
        if level is not None:
            self.level = level
        return self.level

    def irq(self, handler, trigger):
        self.handler = handler


class StatusTests(unittest.TestCase):
    def test_button_debounce_boot_press_and_press_during_busy_work(self):
        clock, pin = Clock(), Pin(0)
        button = NextButton(pin, 4, clock)
        self.assertTrue(button.pressed())
        self.assertFalse(button.pressed())
        pin.handler(pin)
        self.assertTrue(button.pressed())
        clock.now += 10
        pin.handler(pin)
        self.assertFalse(button.pressed())
        clock.now += 100
        pin.handler(pin)
        clock.now += 30000  # Latched until rendering completes.
        self.assertTrue(button.pressed())
        self.assertFalse(button.pressed())

    def test_timer_starts_after_display_restarts_and_survives_tick_wrap(self):
        clock = Clock((1 << 30) - 500)
        session = StatusSession(clock, clock.ticks_ms())
        boot, uptime = session.sample((2026, 10, 11, 23, 59, 59))
        self.assertEqual(uptime, 0)
        clock.now += 30000  # Rendering/panel refresh, before the 60s timer.
        session.shown(60)
        clock.now += 59000
        self.assertFalse(session.expired())
        session.shown(60)  # Another NEXT press resets the timer.
        clock.now += 60000
        self.assertTrue(session.expired())
        self.assertEqual(session.sample((2027, 1, 1, 0, 0, 0))[0], boot)
        self.assertEqual(session.uptime_ms(), 149000)

    def test_charge_estimate_clamps_and_status_contains_required_values(self):
        self.assertEqual(estimate_charge(2.8), 0)
        self.assertEqual(estimate_charge(4.5), 100)
        self.assertEqual(estimate_charge(3.75), 50)
        levels = [estimate_charge(value / 100) for value in range(280, 451)]
        self.assertEqual(levels, sorted(levels))
        text = status_text((2026, 10, 11, 21, 30, 0), (2026, 10, 10, 20, 0, 0),
                           91800, 3.75, 60)
        for value in ("2026-10-11 21:30:00", "2026-10-10 20:00:00", "1d 01:30:00",
                      "3.75 V", "50%"):
            self.assertIn(value, text)
        self.assertEqual(len(text.splitlines()[1:]), 5)

    def test_usb_and_battery_status_restore_latest_schedule_after_sixty_seconds(self):
        for usb in (True, False):
            with self.subTest(usb=usb), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / "fonts").mkdir()
                source = Path(__file__).resolve().parents[1] / "examples/tf-card"
                shutil.copyfile(source / "fonts/sign.e6f", root / "fonts/sign.e6f")
                (root / "a.txt").write_text("OPEN 营业中", encoding="utf-8")
                (root / "b.txt").write_text("CLOSED 已结束", encoding="utf-8")
                (root / "cron").write_text("0 9 * * * /a.txt\n1 9 * * * /b.txt")
                settings = {"rotation": 0, "text": {"scale": 1}, "logging": {"debug": True}}
                (root / "config.json").write_text(json.dumps(settings))
                clock = Clock()
                baseline = to_seconds((2026, 10, 11, 9, 0, 0))
                class Board:
                    activity, screen_power, rtc_int = Pin(0), Pin(0), Pin(1)
                    i2c = None
                    next_button = types.SimpleNamespace(pressed=lambda: False)
                    off_times = []
                    def __init__(self):
                        self.power_indicator = PowerIndicator(Pin(0), Pin(int(usb)), Pin(int(not usb)))
                    def set_working(self, working): self.power_indicator.set_working(working)
                    def usb(self): return usb
                    def battery_voltage(self): return 3.75
                    def mount_sd(self): pass
                    def sync(self): pass
                    def power_off(self):
                        self.off_times.append(clock.now)
                        raise KeyboardInterrupt
                board = Board()
                class RTC:
                    target = None
                    def __init__(self, bus): pass
                    def read_time(self): return from_seconds(baseline + clock.now // 1000)
                    def disable_alarm(self): pass
                    def set_alarm(self, target): self.target = target
                class Display:
                    frames = []
                    first_completed = None
                    def display(self, frame):
                        self.assert_working = board.power_indicator.working
                        self.assert_lit = board.power_indicator.pin.value() == 1
                        if not self.assert_working or not self.assert_lit:
                            raise AssertionError("PWR must be steady on during status and restoration")
                        self.frames.append(bytes(frame))
                        clock.now += 300
                        if len(self.frames) == 1:
                            self.first_completed = clock.now
                        else:
                            self.assert_restored = clock.now >= self.first_completed + 60000
                            clock.stop = True
                display = Display()
                waiting_levels = []
                original_sleep = clock.sleep_ms
                def sleep(delay):
                    before = clock.now // 500
                    original_sleep(delay)
                    for _ in range(clock.now // 500 - before):
                        board.power_indicator.tick()
                    if display.first_completed is not None:
                        self.assertFalse(board.power_indicator.working)
                        waiting_levels.append(board.power_indicator.pin.value())
                clock.sleep_ms = sleep
                modules = {"board": types.SimpleNamespace(Board=lambda: board),
                           "rtc": types.SimpleNamespace(PCF85063=RTC),
                           "epaper": types.SimpleNamespace(Epaper=types.SimpleNamespace(for_board=lambda b: display))}
                with patch.dict(sys.modules, modules), patch.object(app, "ROOT", temporary), \
                        patch.object(app, "time", clock), patch.object(sign_log, "LOG", sign_log.Logger()), \
                        contextlib.redirect_stdout(io.StringIO()):
                    app.run(bytearray(192000), boot_ms=0, key_at_boot=True, rtc_wake=True)
                self.assertEqual(len(display.frames), 2)
                self.assertTrue(display.assert_restored)
                expected = render_file(str(root / "b.txt"), str(root / "fonts/sign.e6f"),
                                       settings["text"], rotation=0)
                self.assertEqual(display.frames[1], expected)
                self.assertEqual(app.load_state(temporary)["path"], "/b.txt")
                if usb:
                    self.assertEqual(board.off_times, [])
                    self.assertEqual(set(waiting_levels), {0, 1})
                else:
                    self.assertEqual(len(board.off_times), 1)
                    self.assertGreaterEqual(board.off_times[0], display.first_completed + 60000)
                    self.assertEqual(set(waiting_levels), {0})

    def test_transient_state_forces_same_path_restoration_and_remembers_prior_file(self):
        from test_content import Display, tiny_font
        from scheduler import Schedule
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tiny_font(root / "font.e6f")
            (root / "a.txt").write_text("A中", encoding="utf-8")
            config = dict(app.DEFAULTS)
            config["font"] = "/font.e6f"
            display = Display()
            controller = app.Controller(temporary, config, display)
            schedule = Schedule.parse("* * * * * /a.txt")
            now = (2026, 10, 11, 10, 0, 0)
            controller.update(schedule, now)
            app.save_state(temporary, "@status", "temporary", "/a.txt")
            self.assertTrue(controller.update(schedule, now))
            app.save_state(temporary, "@status", "temporary", "/a.txt")
            config["default"] = None
            self.assertTrue(controller.update(Schedule.parse(""), now, "/a.txt"))
            self.assertEqual(display.count, 3)
            self.assertEqual((root / ".display-state.json").read_text().splitlines()[1][:4], "    ")
