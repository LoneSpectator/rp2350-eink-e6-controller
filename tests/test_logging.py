import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "firmware"))
from sign_log import Logger, validate_settings


class LoggingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.logger = Logger()
        self.output = io.StringIO()
        self.console = contextlib.redirect_stdout(self.output)
        self.console.__enter__()

    def tearDown(self):
        self.console.__exit__(None, None, None)
        self.temporary.cleanup()

    def configure(self, settings):
        self.logger.configure(str(self.root), settings, lambda: (2026, 10, 11, 21, 30, 0))

    def test_defaults_persist_only_warnings_and_console_has_same_prefix(self):
        self.configure({})
        self.logger.record("DEBUG", ("phase", 10))
        self.logger.record("INFO", ("normal",))
        self.assertFalse((self.root / "logs").exists())
        self.logger.record("WARNING", ("battery low",))
        record = (self.root / "logs/warnings.log").read_text()
        self.assertEqual(record, "[2026-10-11 21:30:00] [WARNING] battery low\n")
        self.assertIn(record, self.output.getvalue())
        self.assertFalse((self.root / "logs/debug.log").exists())

    def test_debug_and_traceback_files_include_timestamp_and_level(self):
        self.configure({"debug": True, "directory": "/diagnostics/logs"})
        self.logger.record("DEBUG", ("cache hit",))
        try:
            raise ValueError("bad schedule")
        except ValueError as exc:
            self.logger.exception("Sign error", exc)
        debug = (self.root / "diagnostics/logs/debug.log").read_text()
        warnings = (self.root / "diagnostics/logs/warnings.log").read_text()
        self.assertIn("[DEBUG] cache hit", debug)
        self.assertIn("[ERROR] Sign error", warnings)
        self.assertIn("Traceback", warnings)
        self.assertIn("ValueError: bad schedule", warnings)
        self.assertIn(warnings, debug)

    def test_rotation_is_bounded_and_keeps_most_recent_records(self):
        self.configure({"debug": True, "max_bytes": 1024, "backup_count": 2})
        for index in range(60):
            self.logger.record("WARNING", ("record-%03d" % index, "中" * 80))
        for kind in ("debug", "warnings"):
            files = sorted((self.root / "logs").glob(kind + ".log*"))
            self.assertEqual(len(files), 3)
            self.assertTrue(all(path.stat().st_size <= 1024 for path in files))
            self.assertIn("record-059", (self.root / ("logs/" + kind + ".log")).read_text())

    def test_io_failure_does_not_interrupt_application_or_recurse(self):
        self.configure({"debug": True})
        with patch.object(self.logger, "append", side_effect=OSError("full")) as append:
            self.logger.record("WARNING", ("first",))
            self.logger.record("WARNING", ("second",))
            self.assertEqual(append.call_count, 1)
        self.assertIn("[WARNING] Log write failed", self.output.getvalue())
        self.logger.configure(None, {"debug": False, "warnings": False})
        self.logger.record("ERROR", ("console only",))
        self.assertIn("uptime_ms=", self.output.getvalue())

    def test_invalid_settings(self):
        for settings in ({"debug": "true"}, {"warnings": 1}, {"directory": "/../logs"},
                         {"max_bytes": 1}, {"backup_count": 11}, {"unknown": True}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                validate_settings(settings)
