#!/usr/bin/env python3
"""Generate on-demand MicroPython bitmap fonts from a licensed TTF/OTF/TTC."""
import argparse
import math
from pathlib import Path
import struct

from PIL import Image, ImageDraw, ImageFont


def build_font(font_path, output, characters, cell=32, size=26, font_index=0):
    if not 8 <= cell <= 64 or not 1 <= size <= cell:
        raise ValueError("cell must be 8..64; font size must fit the cell")
    font = ImageFont.truetype(str(font_path), size, index=font_index)
    chars = sorted(set(characters) - {"\n", "\r", "\t"}, key=ord)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    row_bytes = (cell + 7) // 8
    with output.open("wb") as stream:
        stream.write(struct.pack("<4sBBHII", b"E6F1", cell, cell,
                                 row_bytes * cell, len(chars), 0))
        for char in chars:
            image = Image.new("1", (cell, cell), 0)
            draw = ImageDraw.Draw(image)
            draw.text((0, cell - max(4, size // 5)), char, font=font, fill=1, anchor="ls")
            advance = max(1, min(cell, math.ceil(font.getlength(char))))
            bitmap = bytearray(row_bytes * cell)
            for y in range(cell):
                for x in range(cell):
                    if image.getpixel((x, y)):
                        bitmap[y * row_bytes + x // 8] |= 0x80 >> (x % 8)
            stream.write(struct.pack("<IB", ord(char), advance))
            stream.write(bitmap)
    return len(chars)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("font", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("text_files", nargs="*", type=Path)
    parser.add_argument("--chars", default="")
    parser.add_argument("--cjk", action="store_true", help="include basic CJK, punctuation, ASCII")
    parser.add_argument("--cell", type=int, default=32)
    parser.add_argument("--size", type=int, default=26)
    parser.add_argument("--font-index", type=int, default=0, help="TTC collection face index")
    args = parser.parse_args()
    chars = "".join(chr(n) for n in range(32, 127)) + args.chars
    for path in args.text_files:
        chars += path.read_text(encoding="utf-8-sig")
    if args.cjk:
        chars += "".join(chr(n) for n in range(0x4E00, 0xA000))
        chars += "".join(chr(n) for n in range(0x3000, 0x3040))
        chars += "".join(chr(n) for n in range(0xFF01, 0xFF61))
        chars += "“”‘’—–…·￥"
    count = build_font(args.font, args.output, chars, args.cell, args.size, args.font_index)
    print("Generated %d glyphs, %d bytes: %s" % (count, args.output.stat().st_size, args.output))


if __name__ == "__main__":
    main()
