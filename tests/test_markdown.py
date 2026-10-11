from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "firmware"))
from content import BitmapFont, Canvas
from markdown_content import COLOR_NAMES, draw_markdown, inline_runs
from scheduler import card_path
from test_content import tiny_font


def pixel(canvas, x, y):
    value = canvas.data[(y * canvas.width + x) // 2]
    return value & 15 if x & 1 else value >> 4


class MarkdownTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        path = Path(self.temporary.name) / "font.e6f"
        tiny_font(path)
        self.font = BitmapFont(str(path))
        self.settings = {"margin": 0, "scale": 1, "line_spacing": 0}

    def tearDown(self):
        self.font.close()
        self.temporary.cleanup()

    def test_centered_heading_size_bold_and_second_level(self):
        canvas = Canvas(16, 10)
        draw_markdown("# A\n## B", self.font, canvas, self.settings)
        self.assertEqual(pixel(canvas, 0, 0), 1)
        for x in (5, 6, 7):
            self.assertEqual(pixel(canvas, x, 0), 0)  # Centered 5-pixel cell.
        self.assertEqual(pixel(canvas, 7, 4), 0)  # ## uses the body scale.

    def test_all_six_colors_and_inline_color_restoration(self):
        for name, code in COLOR_NAMES.items():
            canvas = Canvas(8, 4)
            draw_markdown('<span style="color: %s">A</span>B' % name,
                          self.font, canvas, self.settings)
            self.assertEqual(pixel(canvas, 0, 0), code)
            self.assertEqual(pixel(canvas, 1, 1), code)
            self.assertEqual(pixel(canvas, 2, 0), 0)
        canvas = Canvas(8, 4)
        draw_markdown("**A**B", self.font, canvas, self.settings)
        self.assertEqual(pixel(canvas, 1, 0), 0)  # Bold thickens by one pixel.
        self.assertEqual(pixel(canvas, 3, 0), 1)

    def test_wrapping_keeps_color_and_bold_and_detects_overflow(self):
        canvas = Canvas(4, 4)
        draw_markdown('<span style="color:red">AB中</span>', self.font, canvas, self.settings)
        self.assertEqual(pixel(canvas, 0, 2), 3)
        with self.assertRaisesRegex(ValueError, "exceeds one screen"):
            draw_markdown("AB中", self.font, Canvas(4, 2), self.settings)
        with self.assertRaisesRegex(ValueError, "no room"):
            draw_markdown("# A", self.font, Canvas(4, 6), self.settings)

    def test_invalid_and_nested_spans_and_literal_escaping(self):
        for source in ('<span style="color:purple">A</span>', '</span>A',
                       '<span style="color:red">A', '**A', '<span bad="red">A</span>'):
            with self.subTest(source=source), self.assertRaises(ValueError):
                list(inline_runs(source, 0))
        runs = list(inline_runs('<span style="color:red">A<span style="color:blue">B</span>中</span>', 0))
        self.assertEqual([run[1] for run in runs], [3, 5, 3])
        self.assertEqual("".join(run[0] for run in inline_runs(r"\*\*A", 0)), "**A")
        self.assertEqual(card_path("/text/通知.MD"), "/text/通知.MD")
