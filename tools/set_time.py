#!/usr/bin/env python3
"""Set the product's external PCF85063 to local civil time over USB/mpremote."""
import argparse
from datetime import datetime
import subprocess
import sys
from zoneinfo import ZoneInfo


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="auto")
    parser.add_argument("--timezone", default="Asia/Shanghai")
    args = parser.parse_args()
    # mpremote first interrupts main; set real time in the same host process.
    date = datetime.now(ZoneInfo(args.timezone))
    value = (date.year, date.month, date.day, date.hour, date.minute, date.second)
    code = ("from board import Board; from rtc import PCF85063; "
            "r=PCF85063(Board().i2c); print(r.set_time(%r))" % (value,))
    subprocess.run([sys.executable, "-m", "mpremote", "connect", args.port,
                    "exec", code], check=True)
    print("RTC uses local civil time in", args.timezone, "; reset device to start scheduling")


if __name__ == "__main__":
    main()
