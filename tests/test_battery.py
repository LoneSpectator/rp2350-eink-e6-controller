import contextlib
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
import app
import sign_log
from battery_warning import empty_battery_frame, low_charge, overlay_low_battery
from content import Canvas
from scheduler import Schedule
from test_content import tiny_font
from test_status import Clock, Pin


def pixel(frame, x, y):
    value = frame[(y * 800 + x) // 2]
    return value & 15 if x & 1 else value >> 4


class BatteryTests(unittest.TestCase):
    def test_warning_below_ten_percent_and_rotation_over_picture(self):
        self.assertFalse(low_charge(None))
        self.assertFalse(low_charge(3.5))  # Exactly 10% must not show a badge.
        self.assertTrue(low_charge(3.4))
        first = bytearray(b"\x55" * 192000)  # Blue photo background.
        second = bytearray(first)
        self.assertIs(overlay_low_battery(first, 0), first)
        self.assertEqual(pixel(first, 720, 428), 3)
        self.assertEqual(pixel(first, 715, 423), 1)
        # All pixels outside the backing remain unchanged, including neighbors
        # sharing packed bytes with the red terminal's odd-width edge.
        for y in range(480):
            for x in range(800):
                if not (714 <= x < 790 and 422 <= y < 470):
                    self.assertEqual(pixel(first, x, y), 5)
        overlay_low_battery(second, 180)
        logical = Canvas(buffer=bytearray(first))
        logical.data[:] = first  # Canvas initializes the supplied buffer white.
        logical.rotate180()
        self.assertEqual(second, logical.data)

    def test_battery_crossing_refreshes_same_text_and_image_without_dirtying_cache(self):
        for extension in ("txt", "md", "e6", "bmp"):
            with self.subTest(extension=extension), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                tiny_font(root / "font.e6f")
                path = root / ("a." + extension)
                if extension in ("txt", "md"):
                    path.write_text("A中", encoding="utf-8")
                elif extension == "e6":
                    path.write_bytes(struct.pack("<4sHHI4x", b"E6P1", 800, 480, 192000) +
                                     b"\x55" * 192000)
                else:
                    from PIL import Image
                    Image.new("RGB", (800, 480), "blue").save(path)
                config = dict(app.DEFAULTS)
                config.update(font="/font.e6f", rotation=0, text={"scale": 1})
                frames = []
                display = types.SimpleNamespace(display=lambda data: frames.append(bytes(data)))
                schedule = Schedule.parse("* * * * * /" + path.name)
                now = (2026, 10, 11, 10, 0, 0)
                controller = app.Controller(temporary, config, display, bytearray(192000))
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertTrue(controller.update(schedule, now, voltage=3.75))
                    cache = Path(str(path) + ".e6cache")
                    clean_cache = cache.read_bytes() if cache.exists() else None
                    # A new controller mimics the next RTC wake from power-off.
                    controller = app.Controller(temporary, config, display, bytearray(192000))
                    self.assertTrue(controller.update(schedule, now, voltage=3.4))
                    self.assertFalse(controller.update(schedule, now, voltage=3.4))
                    self.assertTrue(controller.update(schedule, now, voltage=3.75))
                    self.assertFalse(controller.update(schedule, now, voltage=3.75))
                self.assertEqual(len(frames), 3)
                self.assertEqual(pixel(frames[1], 720, 428), 3)
                self.assertNotEqual(frames[0], frames[1])
                self.assertEqual(frames[0], frames[2])
                if clean_cache is not None:
                    self.assertEqual(cache.read_bytes(), clean_cache)

    def test_final_warning_finishes_before_poweroff_and_does_not_repeat(self):
        with tempfile.TemporaryDirectory() as root, contextlib.redirect_stdout(io.StringIO()):
            events = []
            config = dict(app.DEFAULTS)
            Path(root, "old.e6").write_bytes(
                struct.pack("<4sHHI4x", b"E6P1", 800, 480, 192000) + b"\x55" * 192000)
            app.save_state(root, "/old.e6", "old")
            frame = bytearray(192000)
            class Board:
                activity, screen_power = Pin(0), Pin(0)
                def usb(self): return False
                def power_off(self): events.append("power-off")
            rtc = types.SimpleNamespace(disable_alarm=lambda: events.append("disable-alarm"))
            def display(data):
                self.assertIs(data, frame)
                self.assertEqual(app.load_state(root)["digest"], "pending")
                self.assertTrue(all(value >> 4 in (1, 3) and value & 15 in (1, 3)
                                    for value in data))
                self.assertEqual(pixel(data, 0, 0), 1)
                events.append("refresh-complete")
            display = types.SimpleNamespace(display=display)
            self.assertTrue(app.empty_battery_shutdown(Board(), rtc, display, frame, config, 3.0, root))
            self.assertEqual(events, ["disable-alarm", "refresh-complete", "power-off"])
            state = app.load_state(root)
            self.assertEqual(state["path"], "@battery-empty")
            self.assertEqual(state["previous_path"], "/old.e6")
            events.clear()
            app.empty_battery_shutdown(Board(), rtc, display, frame, config, 3.0, root)
            self.assertEqual(events, ["disable-alarm", "power-off"])
            self.assertFalse(app.empty_battery_shutdown(Board(), rtc, display, frame, config, 3.75, root))
            self.assertEqual(app.previous_content(state), "/old.e6")
            # Recover the last normal file after charging, even with no default
            # content and no historical event in the current schedule.
            config["default"] = None
            restored = []
            normal_display = types.SimpleNamespace(display=lambda data: restored.append(bytes(data)))
            controller = app.Controller(root, config, normal_display, frame)
            self.assertTrue(controller.update(Schedule.parse(""), (2026, 10, 11, 10, 0, 0),
                                              app.previous_content(state), voltage=3.75))
            self.assertEqual(restored, [b"\x55" * 192000])
            self.assertEqual(app.load_state(root)["path"], "/old.e6")

    def test_final_warning_failure_still_cuts_power_and_leaves_pending_for_retry(self):
        with tempfile.TemporaryDirectory() as root, contextlib.redirect_stdout(io.StringIO()):
            off = []
            board = types.SimpleNamespace(usb=lambda: False, activity=Pin(0), screen_power=Pin(0),
                                          power_off=lambda: off.append(True))
            def failure(*args): raise OSError("hardware unavailable")
            rtc = types.SimpleNamespace(disable_alarm=failure)
            display = types.SimpleNamespace(display=failure)
            app.empty_battery_shutdown(board, rtc, display, bytearray(192000), dict(app.DEFAULTS), 3.0, root)
            self.assertEqual(off, [True])
            self.assertEqual(app.load_state(root)["digest"], "pending")
            board.usb = lambda: True
            self.assertFalse(app.empty_battery_shutdown(board, rtc, display, bytearray(192000),
                                                       dict(app.DEFAULTS), 2.9, root))
            self.assertEqual(off, [True])

    def test_low_battery_works_with_bad_card_or_custom_threshold_or_refresh_voltage_sag(self):
        for mode in ("bad-card", "threshold", "sag"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                config = {"low_battery_voltage": 3.3, "rotation": 0}
                (root / "config.json").write_text(json.dumps(config))
                (root / "cron").write_text("* * * * * /a.e6")
                (root / "a.e6").write_bytes(
                    struct.pack("<4sHHI4x", b"E6P1", 800, 480, 192000) + b"\x55" * 192000)
                frames, events = [], []
                voltage = [3.75 if mode == "sag" else 3.2 if mode == "threshold" else 3.0]
                class Board:
                    activity, screen_power, rtc_int = Pin(0), Pin(0), Pin(1)
                    i2c = None
                    next_button = types.SimpleNamespace(pressed=lambda: False)
                    def usb(self): return False
                    def battery_voltage(self): return voltage[0]
                    def mount_sd(self):
                        if mode == "bad-card": raise OSError("bad card")
                    def power_off(self):
                        events.append("power-off")
                        raise KeyboardInterrupt
                rtc = types.SimpleNamespace(disable_alarm=lambda: events.append("disable-alarm"),
                                            read_time=lambda: (2026, 10, 11, 10, 0, 0))
                def display(data):
                    frames.append(bytes(data))
                    events.append("refresh-complete")
                    voltage[0] = 3.0
                modules = {"board": types.SimpleNamespace(Board=Board),
                           "rtc": types.SimpleNamespace(PCF85063=lambda bus: rtc),
                           "epaper": types.SimpleNamespace(Epaper=types.SimpleNamespace(
                               for_board=lambda b: types.SimpleNamespace(display=display)))}
                with patch.dict(sys.modules, modules), patch.object(app, "ROOT", temporary), \
                        patch.object(app, "time", Clock()), patch.object(sign_log, "LOG", sign_log.Logger()), \
                        contextlib.redirect_stdout(io.StringIO()):
                    # A simulated power loss exits through KeyboardInterrupt.
                    try:
                        app.run(bytearray(192000), rtc_wake=True)
                    except KeyboardInterrupt:
                        pass
                self.assertEqual(len(frames), 2 if mode == "sag" else 1)
                self.assertEqual(events[-2:], ["refresh-complete", "power-off"])
                rotation = app.DEFAULTS["rotation"] if mode == "bad-card" else config["rotation"]
                self.assertEqual(frames[-1], empty_battery_frame(bytearray(192000), rotation))

