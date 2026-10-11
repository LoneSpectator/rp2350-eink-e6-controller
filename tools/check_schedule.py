#!/usr/bin/env python3
"""Validate the TF cron file and show selected/next events without a device."""
import argparse
from datetime import datetime
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "firmware"))
from calendar_time import from_minutes
from scheduler import Schedule


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--at", help="RTC local time: YYYY-MM-DDTHH:MM:SS")
    parser.add_argument("--timezone", default="Asia/Shanghai")
    args = parser.parse_args()
    date = datetime.fromisoformat(args.at) if args.at else datetime.now(ZoneInfo(args.timezone))
    now = (date.year, date.month, date.day, date.hour, date.minute, date.second)
    schedule = Schedule.parse(args.file.read_text(encoding="utf-8"))
    active = schedule.current(now)
    print("Current:", (from_minutes(active[0]), active[1].path) if active else "none")
    next_minute = schedule.next_minute(now)
    print("Next:", from_minutes(next_minute) if next_minute is not None else "none within 8 years")


if __name__ == "__main__":
    main()
