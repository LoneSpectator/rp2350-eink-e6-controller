#!/usr/bin/env python3
"""Upload modules to an already-flashed Pico, with main.py copied last."""
import argparse
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="auto")
    args = parser.parse_args()
    firmware = Path(__file__).resolve().parents[1] / "firmware"
    files = [firmware / "boot.py"]
    files += sorted(p for p in firmware.glob("*.py") if p.name not in ("boot.py", "main.py"))
    files += [firmware / "main.py"]
    command = [sys.executable, "-m", "mpremote", "connect", args.port]
    for file in files:
        command += ["fs", "cp", str(file), ":" + file.name, "+"]
    subprocess.run(command[:-1], check=True)
    print("Firmware uploaded. Set external RTC time, insert TF card, then reset.")


if __name__ == "__main__":
    main()
