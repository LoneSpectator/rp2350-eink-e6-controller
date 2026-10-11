import datetime
from pathlib import Path
import random
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "firmware"))
from calendar_time import civil, days, from_minutes, from_seconds, to_minutes, to_seconds, weekday
from scheduler import Schedule, card_path
from app import wake_target


class CalendarTests(unittest.TestCase):
    def test_calendar_against_standard_library(self):
        rng = random.Random(2350)
        epoch = datetime.date(1970, 1, 1)
        for _ in range(250):
            date = datetime.date(2000, 1, 1) + datetime.timedelta(days=rng.randrange(36525))
            number = days(date.year, date.month, date.day)
            self.assertEqual(number, (date - epoch).days)
            self.assertEqual(civil(number), (date.year, date.month, date.day))
            self.assertEqual(weekday(number), (date.weekday() + 1) % 7)

    def test_seconds_roundtrip(self):
        for value in ((2000, 2, 29, 23, 59, 59), (2026, 12, 31, 23, 59, 59)):
            self.assertEqual(from_seconds(to_seconds(value)), value)

    def test_invalid_calendar(self):
        for value in ((2025, 2, 29, 0, 0, 0), (2026, 4, 31, 0, 0, 0), (2026, 1, 1, 24, 0, 0)):
            with self.assertRaises(ValueError):
                to_minutes(value)


class CronTests(unittest.TestCase):
    def test_weekday_recovery_and_next(self):
        cron = Schedule.parse("0 9 * * 1-5 /open.txt\n0 18 * * 1-5 /closed.txt")
        now = (2026, 10, 11, 12, 0, 0)  # Sunday
        event, entry = cron.current(now)
        self.assertEqual(from_minutes(event), (2026, 10, 9, 18, 0, 0))
        self.assertEqual(entry.path, "/closed.txt")
        self.assertEqual(from_minutes(cron.next_minute(now)), (2026, 10, 12, 9, 0, 0))

    def test_missed_event_and_boundary(self):
        cron = Schedule.parse("0 9 * * * /open.txt\n0 18 * * * /closed.txt")
        self.assertEqual(cron.current((2026, 10, 12, 18, 0, 1))[1].path, "/closed.txt")
        self.assertEqual(cron.current((2026, 10, 12, 9, 5, 0))[1].path, "/open.txt")

    def test_same_minute_last_line_wins(self):
        cron = Schedule.parse("* * * * * /a.txt\n# comment\n* * * * * /b.txt")
        self.assertEqual(cron.current((2026, 10, 11, 12, 0, 0))[1].path, "/b.txt")

    def test_lists_ranges_and_steps(self):
        cron = Schedule.parse("5-55/10 9,17 * * 1-5 /a.txt")
        now = (2026, 10, 12, 10, 0, 0)
        self.assertEqual(from_minutes(cron.current(now)[0]), (2026, 10, 12, 9, 55, 0))
        self.assertEqual(from_minutes(cron.next_minute(now)), (2026, 10, 12, 17, 5, 0))

    def test_dom_dow_or_semantics(self):
        cron = Schedule.parse("0 12 1 * 1 /a.txt")
        self.assertEqual(from_minutes(cron.next_minute((2026, 10, 1, 0, 0, 0))),
                         (2026, 10, 1, 12, 0, 0))  # Thursday, DOM matches
        self.assertEqual(from_minutes(cron.next_minute((2026, 10, 4, 0, 0, 0))),
                         (2026, 10, 5, 12, 0, 0))  # Monday, DOW matches

    def test_star_steps_use_and(self):
        cron = Schedule.parse("0 9 */2 * 1 /a.txt")
        self.assertEqual(from_minutes(cron.next_minute((2026, 10, 5, 9, 0, 0))),
                         (2026, 10, 19, 9, 0, 0))

    def test_31st_and_leap_day(self):
        cron = Schedule.parse("0 0 31 * * /a.txt")
        self.assertEqual(from_minutes(cron.next_minute((2026, 4, 1, 0, 0, 0))),
                         (2026, 5, 31, 0, 0, 0))
        leap = Schedule.parse("0 0 29 2 * /a.txt")
        self.assertEqual(from_minutes(leap.next_minute((2025, 3, 1, 0, 0, 0))),
                         (2028, 2, 29, 0, 0, 0))
        self.assertEqual(from_minutes(leap.current((2026, 1, 1, 0, 0, 0))[0]),
                         (2024, 2, 29, 0, 0, 0))

    def test_impossible_date_and_empty(self):
        cron = Schedule.parse("0 0 31 2 * /a.txt")
        self.assertIsNone(cron.current((2026, 10, 11, 0, 0, 0)))
        self.assertIsNone(cron.next_minute((2026, 10, 11, 0, 0, 0)))
        self.assertIsNone(Schedule.parse("# empty").next_minute((2026, 10, 11, 0, 0, 0)))

    def test_sunday_7_and_spaces_in_path(self):
        cron = Schedule.parse("0 0 * * 7 pic/周末 通知.bmp")
        self.assertEqual(cron.current((2026, 10, 11, 0, 0, 0))[1].path, "/pic/周末 通知.bmp")

    def test_invalid_cron_fails_whole_file(self):
        for source in ("60 * * * * /a.txt", "*/0 * * * * /a.txt", "0 24 * * * /a.txt",
                       "0 0 0 * * /a.txt", "0 0 * 13 * /a.txt", "0 0 * * 8 /a.txt",
                       "9-3 * * * * /a.txt", "@daily /a.txt", "0 0 * * * ../a.txt",
                       "0 0 * * * /run.py", "1,,2 * * * * /a.txt"):
            with self.subTest(source=source), self.assertRaises(ValueError):
                Schedule.parse(source)

    def test_card_paths_are_data(self):
        for path in ("/../a.txt", "a//b.bmp", "C:/a.txt", "a\\b.txt", "a/./b.txt"):
            with self.assertRaises(ValueError):
                card_path(path)
        self.assertEqual(card_path("/text/$(date).txt"), "/text/$(date).txt")

    def test_cron_against_minute_scan(self):
        cron = Schedule.parse("*/17 8-20 * * 1,3,5 /a.txt")
        start = datetime.datetime(2026, 10, 11, 16, 20)
        for sign in (-1, 1):
            date = start + (datetime.timedelta(minutes=1) if sign == 1 else datetime.timedelta())
            while not (date.minute % 17 == 0 and 8 <= date.hour <= 20 and date.weekday() in (0, 2, 4)):
                date += datetime.timedelta(minutes=sign)
            now = (start.year, start.month, start.day, start.hour, start.minute, 0)
            result = cron.next_minute(now) if sign == 1 else cron.current(now)[0]
            self.assertEqual(from_minutes(result), (date.year, date.month, date.day, date.hour, date.minute, 0))


class WakeTests(unittest.TestCase):
    def test_next_event_before_checkpoint(self):
        now = (2026, 10, 31, 23, 59, 30)
        event = to_minutes((2026, 11, 1, 0, 0, 0))
        self.assertEqual(wake_target(now, event), (2026, 11, 1, 0, 0, 0))

    def test_distant_event_checkpoint_crosses_year(self):
        now = (2026, 12, 31, 23, 0, 0)
        event = to_minutes((2027, 2, 1, 0, 0, 0))
        self.assertEqual(wake_target(now, event), (2027, 1, 1, 5, 0, 0))

    def test_error_retry_and_past_target(self):
        now = (2026, 10, 11, 8, 0, 59)
        self.assertEqual(wake_target(now, None, retry_minutes=5), (2026, 10, 11, 8, 5, 59))
        self.assertEqual(wake_target(now, to_minutes(now)), (2026, 10, 11, 8, 1, 1))
