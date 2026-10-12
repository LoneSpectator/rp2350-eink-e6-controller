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
from calendar_time import from_seconds, to_seconds
from next_button import NextButton
from test_status import Clock, Pin


class PreviewTests(unittest.TestCase):
    def test_long_press_previews_file_order_even_when_dates_do_not_match_then_restores(self):
        for usb in (True, False):
            with self.subTest(usb=usb), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / "config.json").write_text(json.dumps({"rotation": 0}))
                (root / "cron").write_text("0 9 * * * /a.e6\n# Comment\n"
                                          "0 0 31 2 * /b.e6\n1 9 * * * /c.e6")
                for name, color in (("a", 5), ("b", 3), ("c", 1)):
                    (root / (name + ".e6")).write_bytes(
                        struct.pack("<4sHHI4x", b"E6P1", 800, 480, 192000) + bytes((color * 17,)) * 192000)
                app.save_state(temporary, "/a.e6", "prior")
                clock = Clock()
                button = NextButton(Pin(0), 12, clock)
                baseline = to_seconds((2026, 10, 12, 9, 0, 0))
                frames, starts, completed, offs = [], [], [], []
                class Board:
                    i2c = None
                    screen_power, activity, rtc_int = Pin(0), Pin(0), Pin(1)
                    next_button = button
                    working = True
                    def mount_sd(self): pass
                    def usb(self): return usb
                    def battery_voltage(self): return 3.75
                    def set_working(self, working): self.working = working
                    def sync(self): pass
                    def power_off(self):
                        offs.append(clock.now)
                        raise KeyboardInterrupt
                board = Board()
                alarm_calls = []
                rtc = types.SimpleNamespace(
                    read_time=lambda: from_seconds(baseline + clock.now // 1000),
                    disable_alarm=lambda: None, set_alarm=lambda target: alarm_calls.append(clock.now))
                def display(frame):
                    self.assertTrue(board.working)
                    starts.append(clock.now)
                    frames.append(frame[0])
                    clock.now += 20000
                    completed.append(clock.now)
                    if len(frames) <= 3:
                        self.assertEqual(app.load_state(temporary)["path"], "@preview")
                        self.assertEqual(app.previous_content(app.load_state(temporary)), "/a.e6")
                    if len(frames) == 4:
                        clock.stop = True
                original_sleep = clock.sleep_ms
                def sleep(delay):
                    self.assertTrue(board.working)
                    self.assertFalse(alarm_calls)
                    original_sleep(delay)
                clock.sleep_ms = sleep
                modules = {"board": types.SimpleNamespace(Board=lambda: board),
                           "rtc": types.SimpleNamespace(PCF85063=lambda bus: rtc),
                           "epaper": types.SimpleNamespace(Epaper=types.SimpleNamespace(
                               for_board=lambda b: types.SimpleNamespace(display=display)))}
                with patch.dict(sys.modules, modules), patch.object(app, "ROOT", temporary), \
                        patch.object(app, "time", clock), patch.object(sign_log, "LOG", sign_log.Logger()), \
                        contextlib.redirect_stdout(io.StringIO()):
                    app.run(bytearray(192000), rtc_wake=True)
                self.assertEqual(frames, [0x55, 0x33, 0x11, 0x11])
                self.assertGreaterEqual(starts[0], 3000)
                for index in range(1, 4):
                    self.assertGreaterEqual(starts[index] - completed[index - 1], 60000)
                self.assertEqual(app.load_state(temporary)["path"], "/c.e6")
                self.assertEqual(len(offs), 0 if usb else 1)
                self.assertTrue(not alarm_calls or alarm_calls[0] >= completed[-1])

    def test_new_next_configuration_defaults_merge_and_obsolete_fields_are_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            file = Path(root, "config.json")
            file.write_text(json.dumps({"next": {"preview_seconds": 10}}))
            config = app.read_config(root)
            self.assertEqual(config["next"]["preview_seconds"], 10)
            self.assertEqual(config["next"]["long_press_ms"], 3000)
            self.assertEqual(config["next"]["status_seconds"], 60)
            for settings in ({"status_seconds": 60}, {"next": {"unknown": True}},
                             {"next": {"long_press_ms": 20}}, {"next": {"preview_seconds": False}},
                             {"logging": {"debug": True}}):
                file.write_text(json.dumps(settings))
                with self.subTest(settings=settings), self.assertRaises(ValueError):
                    app.read_config(root)
