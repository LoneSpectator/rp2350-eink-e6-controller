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

    def test_default_info_filter_and_console_have_identical_daily_records(self):
        self.configure({})
        self.logger.record("DEBUG", ("phase", 10))
        self.assertFalse((self.root / "logs").exists())
        self.assertEqual(self.output.getvalue(), "")
        self.logger.record("INFO", ("normal",))
        self.logger.record("WARNING", ("battery low",))
        record = (self.root / "logs/2026-10-11.log").read_text()
        self.assertEqual(record, "[2026-10-11 21:30:00] [INFO] normal\n"
                                 "[2026-10-11 21:30:00] [WARNING] battery low\n")
        self.assertEqual(record, self.output.getvalue())
        self.assertEqual([path.name for path in (self.root / "logs").iterdir()], ["2026-10-11.log"])

    def test_all_levels_and_traceback_share_one_daily_file(self):
        self.configure({"level": "DEBUG", "directory": "/diagnostics/logs"})
        self.logger.record("DEBUG", ("cache hit",))
        self.logger.record("INFO", ("normal",))
        self.logger.record("WARNING", ("battery low",))
        try:
            raise ValueError("bad schedule")
        except ValueError as exc:
            self.logger.exception("Sign error", exc)
        record = (self.root / "diagnostics/logs/2026-10-11.log").read_text()
        for part in ("[DEBUG] cache hit", "[INFO] normal", "[WARNING] battery low", "[ERROR] Sign error",
                     "Traceback", "ValueError: bad schedule"):
            self.assertIn(part, record)
        self.assertEqual(record.count("[ERROR]"), 1)
        self.assertEqual(len(list((self.root / "diagnostics/logs").iterdir())), 1)

    def test_each_level_filters_both_console_and_file_and_off_disables_them(self):
        levels = ("DEBUG", "INFO", "WARNING", "ERROR")
        for threshold in (*levels, "OFF"):
            with self.subTest(threshold=threshold), tempfile.TemporaryDirectory() as root:
                self.output.truncate(0)
                self.output.seek(0)
                self.logger.configure(root, {"level": threshold}, lambda: (2026, 10, 12, 9, 0, 0))
                for level in levels:
                    self.logger.record(level, (level + " event",))
                file = Path(root, "logs/2026-10-12.log")
                if threshold == "OFF":
                    self.assertFalse(file.exists())
                    self.assertEqual(self.output.getvalue(), "")
                else:
                    record = file.read_text()
                    self.assertEqual(record, self.output.getvalue())
                    for level in levels:
                        self.assertEqual(("[%s]" % level) in record,
                                         levels.index(level) >= levels.index(threshold))

    def test_date_rollover_uses_one_rtc_sample_and_reboot_appends_to_existing_day(self):
        moments = iter(((2026, 10, 11, 23, 59, 59), (2026, 10, 12, 0, 0, 0)))
        self.logger.configure(str(self.root), {"level": "INFO"}, lambda: next(moments))
        self.logger.record("INFO", ("before midnight",))
        self.logger.record("WARNING", ("after midnight",))
        previous = (self.root / "logs/2026-10-11.log").read_text()
        current = (self.root / "logs/2026-10-12.log").read_text()
        self.assertIn("[2026-10-11 23:59:59] [INFO] before midnight", previous)
        self.assertIn("[2026-10-12 00:00:00] [WARNING] after midnight", current)
        self.assertNotIn("after midnight", previous)
        restarted = Logger()
        restarted.configure(str(self.root), {}, lambda: (2026, 10, 12, 9, 0, 0))
        restarted.record("INFO", ("new boot",))
        self.assertTrue((self.root / "logs/2026-10-12.log").read_text().startswith(current))
        self.assertIn("new boot", (self.root / "logs/2026-10-12.log").read_text())

    def test_invalid_rtc_preserves_undated_warnings_then_switches_to_valid_date(self):
        def invalid_time(): raise ValueError("RTC invalid")
        self.logger.configure(str(self.root), {"level": "WARNING"}, invalid_time)
        self.logger.record("WARNING", ("set the RTC",))
        undated = (self.root / "logs/undated.log").read_text()
        self.assertIn("[uptime_ms=", undated)
        self.assertIn("[WARNING] set the RTC", undated)
        self.configure({"level": "WARNING"})
        self.logger.record("ERROR", ("valid date",))
        self.assertIn("valid date", (self.root / "logs/2026-10-11.log").read_text())
        self.assertEqual((self.root / "logs/undated.log").read_text(), undated)

    def test_rotation_is_bounded_and_keeps_most_recent_records(self):
        self.configure({"level": "DEBUG", "max_bytes": 1024, "backup_count": 2})
        for index in range(60):
            self.logger.record("WARNING", ("record-%03d" % index, "中" * 80))
        files = sorted((self.root / "logs").glob("2026-10-11.log*"))
        self.assertEqual(len(files), 3)
        self.assertTrue(all(path.stat().st_size <= 1024 for path in files))
        self.assertIn("record-059", (self.root / "logs/2026-10-11.log").read_text())
        self.logger.configure(str(self.root), {"level": "INFO", "max_bytes": 1024, "backup_count": 2},
                              lambda: (2026, 10, 12, 0, 0, 0))
        self.logger.record("INFO", ("new day",))
        self.assertEqual(len(list((self.root / "logs").glob("2026-10-11.log*"))), 3)
        self.assertIn("new day", (self.root / "logs/2026-10-12.log").read_text())

    def test_io_failure_does_not_interrupt_application_or_recurse(self):
        self.configure({"level": "DEBUG"})
        with patch.object(self.logger, "append", side_effect=OSError("full")) as append:
            self.logger.record("WARNING", ("first",))
            self.logger.record("WARNING", ("second",))
            self.assertEqual(append.call_count, 1)
        self.assertIn("[ERROR] Log write failed", self.output.getvalue())
        self.logger.configure(None, {"level": "ERROR"})
        self.logger.record("ERROR", ("console only",))
        self.assertIn("uptime_ms=", self.output.getvalue())

    def test_old_configuration_is_rejected_and_level_names_are_normalized(self):
        for flags in ({"debug": True}, {"warnings": False}, {"level": "INFO", "debug": False}):
            with self.subTest(flags=flags), self.assertRaises(ValueError):
                validate_settings(flags)
        self.assertEqual(validate_settings({"level": "debug"})["level"], "DEBUG")

    def test_invalid_settings(self):
        for settings in ({"debug": "true"}, {"warnings": 1}, {"directory": "/../logs"},
                         {"max_bytes": 1}, {"backup_count": 11}, {"unknown": True},
                         {"level": "verbose"}, {"level": 10}, {"level": None}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                validate_settings(settings)
