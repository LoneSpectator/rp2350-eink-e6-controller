import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "firmware"))
from app import Controller, DEFAULTS, load_state, read_config
from content import BitmapFont, Canvas, draw_text, nearest_color, read_bmp, read_e6, render_file
from scheduler import Schedule
from text_cache import HEADER_BYTES


def tiny_font(path):
    # Chinese plus ASCII: two-pixel cell, one lit diagonal.
    chars = sorted(" AB中", key=ord)
    with open(path, "wb") as stream:
        stream.write(struct.pack("<4sBBHII", b"E6F1", 2, 2, 2, len(chars), 0))
        for char in chars:
            stream.write(struct.pack("<IB", ord(char), 2))
            stream.write(b"\x80\x40" if char != " " else b"\0\0")


class ContentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_six_color_encoding_and_rotation(self):
        canvas = Canvas(4, 2)
        for x, color in enumerate((0, 1, 2, 3)):
            canvas.pixel(x, 0, color)
        canvas.pixel(0, 1, 5)
        canvas.pixel(1, 1, 6)
        self.assertEqual(canvas.data, b"\x01\x23\x56\x11")
        canvas.rotate180()
        self.assertEqual(canvas.data, b"\x11\x65\x32\x10")
        canvas.rotate180()
        self.assertEqual(canvas.data, b"\x01\x23\x56\x11")

    def test_rgb_quantization(self):
        self.assertEqual(nearest_color(250, 10, 0), 3)
        self.assertEqual(nearest_color(0, 1, 250), 5)
        self.assertEqual(nearest_color(0, 250, 1), 6)

    def test_bmp_bottom_up_top_down_and_padding(self):
        for height in (2, -2):
            path = self.root / "sample.bmp"
            # Logical top: red/blue; bottom: green/yellow. 2-byte row padding.
            top = b"\0\0\xff\xff\0\0\x99\x99"
            bottom = b"\0\xff\0\0\xff\xff\x77\x77"
            pixels = bottom + top if height > 0 else top + bottom
            path.write_bytes(struct.pack("<2sIHHI", b"BM", 70, 0, 0, 54) +
                             struct.pack("<IiiHHIIiiII", 40, 2, height, 1, 24, 0, 16, 0, 0, 0, 0) + pixels)
            canvas = Canvas(2, 2)
            read_bmp(str(path), canvas)
            self.assertEqual(canvas.data, b"\x35\x62")

    def test_bmp_compression_and_truncation_rejected(self):
        path = self.root / "bad.bmp"
        header = struct.pack("<2sIHHI", b"BM", 54, 0, 0, 54)
        for compression in (0, 1):
            path.write_bytes(header + struct.pack("<IiiHHIIiiII", 40, 2, 2, 1, 24, compression,
                                                  16, 0, 0, 0, 0))
            with self.assertRaises(ValueError):
                read_bmp(str(path), Canvas(2, 2))

    def test_raw_e6_invalid_color_length_and_trailing_data(self):
        path = self.root / "a.e6"
        header = struct.pack("<4sHHI4x", b"E6P1", 2, 2, 2)
        path.write_bytes(header + b"\x35\x62")
        canvas = Canvas(2, 2)
        read_e6(str(path), canvas)
        self.assertEqual(canvas.data, b"\x35\x62")
        for data in (b"\x44\x62", b"\x35", b"\x35\x62\0"):
            path.write_bytes(header + data)
            with self.assertRaises(ValueError):
                read_e6(str(path), Canvas(2, 2))

    def test_reusable_frame_survives_multiple_content_changes(self):
        path = self.root / "reusable.e6"
        header = struct.pack("<4sHHI4x", b"E6P1", 800, 480, 192000)
        buffer = bytearray(192000)
        for color in (0x35, 0x62):
            path.write_bytes(header + bytes((color,)) * 192000)
            result = render_file(str(path), "unused", rotation=0, buffer=buffer)
            self.assertIs(result, buffer)
            self.assertEqual(result[0], color)

    def test_unicode_font_lookup_wrap_and_overflow(self):
        path = self.root / "font.e6f"
        tiny_font(path)
        font = BitmapFont(str(path))
        try:
            canvas = Canvas(4, 4)
            draw_text("AB中", font, canvas, {"margin": 0, "scale": 1, "line_spacing": 0})
            self.assertEqual(canvas.data, b"\x01\x01\x10\x10\x01\x11\x10\x11")
            with self.assertRaises(ValueError):
                draw_text("AB中AB", font, canvas, {"margin": 0, "scale": 1, "line_spacing": 0})
            with self.assertRaisesRegex(ValueError, "U\\+6587"):
                font.glyph("文")
        finally:
            font.close()

    def test_truncated_font(self):
        path = self.root / "font.e6f"
        tiny_font(path)
        path.write_bytes(path.read_bytes()[:-1])
        with self.assertRaises(ValueError):
            BitmapFont(str(path))

    def test_glyph_cache_avoids_card_reads_and_bounds_memory(self):
        path = self.root / "font.e6f"
        tiny_font(path)
        font = BitmapFont(str(path))
        font.cache_limit = 2
        try:
            with patch.object(font, "stream", wraps=font.stream) as stream:
                expected = font.glyph("A")
                reads = stream.read.call_count
                self.assertEqual(font.glyph("A"), expected)
                self.assertEqual(stream.read.call_count, reads)
                font.glyph("B")
                font.glyph("中")
                self.assertLessEqual(len(font.cache), 2)
                self.assertEqual(font.glyph("A"), expected)
                self.assertGreater(stream.read.call_count, reads)
        finally:
            font.close()


class Display:
    def __init__(self, fail=False):
        self.count = 0
        self.fail = fail

    def display(self, frame):
        self.count += 1
        if self.fail:
            raise OSError("screen failure")
        assert len(frame) == 192000


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.path = self.root / "a.e6"
        self.path.write_bytes(struct.pack("<4sHHI4x", b"E6P1", 800, 480, 192000) + b"\x11" * 192000)
        self.schedule = Schedule.parse("0 9 * * * /a.e6")
        self.now = (2026, 10, 11, 10, 0, 0)
        self.config = dict(DEFAULTS)

    def tearDown(self):
        self.temporary.cleanup()

    def test_restart_unchanged_skips_but_modified_content_refreshes(self):
        display = Display()
        Controller(str(self.root), self.config, display).update(self.schedule, self.now)
        self.assertEqual(display.count, 1)
        Controller(str(self.root), self.config, display).update(self.schedule, self.now)
        self.assertEqual(display.count, 1)
        with self.path.open("r+b") as stream:
            stream.seek(16)
            stream.write(b"\x00")
        Controller(str(self.root), self.config, display).update(self.schedule, self.now)
        self.assertEqual(display.count, 2)

    def test_display_failure_does_not_mark_content_as_shown(self):
        with self.assertRaises(OSError):
            Controller(str(self.root), self.config, Display(fail=True)).update(self.schedule, self.now)
        self.assertEqual(load_state(str(self.root)), {})

    def test_missing_file_does_not_overwrite_previous_state(self):
        display = Display()
        controller = Controller(str(self.root), self.config, display)
        controller.update(self.schedule, self.now)
        state = load_state(str(self.root))
        missing = Schedule.parse("0 9 * * * /missing.e6")
        with self.assertRaises(OSError):
            controller.update(missing, self.now)
        self.assertEqual(load_state(str(self.root)), state)
        self.assertEqual(display.count, 1)

    def test_invalid_configuration(self):
        for config in ({"retry_minutes": 0}, {"cron": "../schedule.cron"},
                       {"rotation": 90}, {"battery_sleep": "true"}, {"unknown": 1}):
            (self.root / "config.json").write_text(json.dumps(config))
            with self.assertRaises(ValueError):
                read_config(str(self.root))

    def test_corrupt_state_and_no_prior_event(self):
        (self.root / ".display-state.json").write_text("broken")
        self.assertEqual(load_state(str(self.root)), {})
        self.config["default"] = None
        self.assertFalse(Controller(str(self.root), self.config, Display()).update(
            Schedule.parse(""), self.now))

    def text_fixture(self):
        font = self.root / "font.e6f"
        tiny_font(font)
        (self.root / "a.txt").write_text("\ufeffA\t中\r\n", encoding="utf-8")
        self.config["font"] = "/font.e6f"
        self.config["rotation"] = 0
        self.config["text"] = {"margin": 0, "scale": 1}
        return font, Schedule.parse("0 9 * * * /a.txt")

    def change_font_byte(self, path, offset, value):
        before = path.stat()
        with path.open("r+b") as stream:
            stream.seek(offset)
            stream.write(value)
        # Font changes use size/mtime. Advance by FAT's two-second granularity.
        os.utime(path, (before.st_atime, before.st_mtime + 2))
        self.assertEqual(path.stat().st_size, before.st_size)

    def test_font_changes_rebuild_cache_only_changed_pixels_refresh(self):
        font, schedule = self.text_fixture()
        display = Display()
        controller = Controller(str(self.root), self.config, display)
        self.assertTrue(controller.update(schedule, self.now))
        # Records are space, A, B, Chinese, each seven bytes. B is unused.
        self.change_font_byte(font, 16 + 2 * 7 + 5, b"\x40")
        self.assertFalse(controller.update(schedule, self.now))
        self.change_font_byte(font, 16 + 7 + 5, b"\x40")
        self.assertTrue(controller.update(schedule, self.now))
        self.assertEqual(display.count, 2)

    def test_font_advance_changes_invalidate_pixel_cache(self):
        font, schedule = self.text_fixture()
        display = Display()
        controller = Controller(str(self.root), self.config, display)
        controller.update(schedule, self.now)
        self.change_font_byte(font, 16 + 7 + 4, b"\x01")
        self.assertTrue(controller.update(schedule, self.now))
        self.assertEqual(display.count, 2)

    def test_controller_closes_font_on_skip_render_error_and_display_error(self):
        _, schedule = self.text_fixture()
        opened = []
        def track_font(path):
            font = BitmapFont(path)
            opened.append(font)
            return font
        with patch("content.BitmapFont", side_effect=track_font):
            controller = Controller(str(self.root), self.config, Display())
            controller.update(schedule, self.now)
            self.assertFalse(controller.update(schedule, self.now))
            self.config["text"] = {"scale": 0}
            with self.assertRaises(ValueError):
                controller.update(schedule, self.now)
            self.config["text"] = {"margin": 1, "scale": 1}
            with self.assertRaises(OSError):
                Controller(str(self.root), self.config, Display(fail=True)).update(schedule, self.now)
        self.assertEqual(len(opened), 3)
        self.assertTrue(all(font.stream.closed for font in opened))

    def test_rebooted_txt_rotation_reads_pixels_without_font_or_layout(self):
        self.text_fixture()
        (self.root / "b.txt").write_text("中A", encoding="utf-8")
        schedule = Schedule.parse("*/5 * * * * /a.txt\n2-59/5 * * * * /b.txt")
        display = Display()
        frame = bytearray(192000)
        with patch("text_cache.render_file", wraps=render_file) as render:
            for minute in (0, 2):
                Controller(str(self.root), self.config, display, frame).update(
                    schedule, (2026, 10, 11, 10, minute, 0))
            self.assertEqual(render.call_count, 2)
            with patch("content.BitmapFont", side_effect=AssertionError("font opened on cache hit")):
                for minute in (5, 7):
                    Controller(str(self.root), self.config, display, frame).update(
                        schedule, (2026, 10, 11, 10, minute, 0))
            self.assertEqual(render.call_count, 2)
        self.assertEqual(display.count, 4)
        for name in ("a.txt", "b.txt"):
            self.assertEqual((self.root / (name + ".e6cache")).stat().st_size,
                             HEADER_BYTES + len(frame))

    def test_txt_same_size_mtime_edit_config_and_corruption_rebuild(self):
        _, schedule = self.text_fixture()
        text = self.root / "a.txt"
        display = Display()
        controller = Controller(str(self.root), self.config, display)
        with patch("text_cache.render_file", wraps=render_file) as render:
            controller.update(schedule, self.now)
            before = text.stat()
            text.write_bytes(text.read_bytes().replace(b"A", b"B"))
            os.utime(text, ns=(before.st_atime_ns, before.st_mtime_ns))
            controller.update(schedule, self.now)
            self.assertEqual(render.call_count, 2)
            self.config["rotation"] = 180
            controller.update(schedule, self.now)
            self.config["text"] = {"scale": 2}
            controller.update(schedule, self.now)
            cache = self.root / "a.txt.e6cache"
            with cache.open("r+b") as stream:
                stream.seek(HEADER_BYTES)
                value = stream.read(1)[0]
                stream.seek(HEADER_BYTES)
                stream.write(bytes((value ^ 1,)))
            # Bad pixels are regenerated even when the retained screen is current.
            self.assertFalse(controller.update(schedule, self.now))
            self.assertEqual(render.call_count, 5)

    def test_cache_write_failure_does_not_block_display(self):
        _, schedule = self.text_fixture()
        display = Display()
        with patch("text_cache.save_cache", side_effect=OSError("card full")):
            self.assertTrue(Controller(str(self.root), self.config, display).update(schedule, self.now))
        self.assertEqual(display.count, 1)
        self.assertEqual(load_state(str(self.root))["path"], "/a.txt")
        self.assertFalse((self.root / "a.txt.e6cache").exists())
