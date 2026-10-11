#!/usr/bin/env python3
"""Render the exact device layout to an RGB PNG for inspection on a computer."""
import argparse
from pathlib import Path
import sys

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "firmware"))
from app import read_config, relative_file
from battery_warning import low_charge, overlay_low_battery
from content import COLORS, RGB, render_file


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tf_root", type=Path)
    parser.add_argument("file", help="TF path, e.g. /text/open.txt")
    parser.add_argument("output", type=Path)
    parser.add_argument("--battery-voltage", type=float, help="simulate the low-battery overlay")
    args = parser.parse_args()
    root = str(args.tf_root)
    config = read_config(root)
    # Show logical reading direction; rotation setting compensates physical mounting.
    frame = render_file(root + relative_file(args.file), root + relative_file(config["font"]),
                        config["text"], rotation=0)
    if low_charge(args.battery_voltage):
        overlay_low_battery(frame, 0)
    palette = dict(zip(COLORS, RGB))
    data = bytearray()
    for value in frame:
        data.extend(palette[value >> 4])
        data.extend(palette[value & 15])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    Image.frombytes("RGB", (800, 480), bytes(data)).save(args.output)
    print("Preview:", args.output)


if __name__ == "__main__":
    main()
