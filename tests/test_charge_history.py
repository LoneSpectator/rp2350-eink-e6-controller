import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "firmware"))
from charge_history import ChargeHistory


class ChargeHistoryTests(unittest.TestCase):
    def test_observed_completion_is_saved_once_and_survives_reboot(self):
        with tempfile.TemporaryDirectory() as root, contextlib.redirect_stdout(io.StringIO()):
            history = ChargeHistory(root)
            time = (2026, 10, 12, 9, 0, 0)
            self.assertFalse(history.observe(True, False, 4.2, time))
            self.assertIsNone(history.last_full)  # Already full at boot has no known completion time.
            self.assertFalse(history.observe(True, True, 3.9, time))
            full = (2026, 10, 12, 10, 30, 0)
            self.assertTrue(history.observe(True, False, 4.2, full))
            file = Path(root, ".charge-state.json")
            original = file.read_text()
            self.assertEqual(json.loads(original)["last_full"], list(full))
            self.assertTrue(original.splitlines()[1].startswith("    "))
            self.assertFalse(history.observe(True, False, 4.2, (2026, 10, 12, 11, 0, 0)))
            self.assertEqual(file.read_text(), original)
            restarted = ChargeHistory(root)
            self.assertEqual(restarted.last_full, full)
            self.assertFalse(restarted.observe(True, False, 4.2, (2026, 10, 13, 9, 0, 0)))
            self.assertEqual(restarted.last_full, full)

    def test_unplugging_usb_and_low_voltage_charge_stop_do_not_count_as_full(self):
        with tempfile.TemporaryDirectory() as root:
            history = ChargeHistory(root)
            time = (2026, 10, 12, 9, 0, 0)
            history.observe(True, True, 3.9, time)
            self.assertFalse(history.observe(False, False, 4.2, time))
            self.assertFalse(history.observe(True, False, 4.2, time))
            history.observe(True, True, 3.9, time)
            self.assertFalse(history.observe(True, False, 3.9, time))
            self.assertIsNone(history.last_full)
            self.assertFalse(Path(root, ".charge-state.json").exists())

    def test_interrupted_rename_recovers_temporary_state_and_corruption_is_ignored(self):
        with tempfile.TemporaryDirectory() as root, contextlib.redirect_stdout(io.StringIO()):
            older, newer = (2026, 10, 11, 9, 0, 0), (2026, 10, 12, 9, 0, 0)
            for name, value in ((".charge-state.json", older), (".charge-state.tmp", newer)):
                Path(root, name).write_text(json.dumps({"version": 1, "last_full": value}))
            self.assertEqual(ChargeHistory(root).last_full, newer)
            Path(root, ".charge-state.tmp").write_text("{broken")
            self.assertEqual(ChargeHistory(root).last_full, older)
            Path(root, ".charge-state.json").write_text("[]")
            self.assertIsNone(ChargeHistory(root).last_full)
