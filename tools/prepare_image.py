#!/usr/bin/env python3
"""Convert images to the device's 800x480 six-color .e6 or 24-bit .bmp format."""
import argparse
from pathlib import Path
import struct

from PIL import Image, ImageOps

RGB = ((0, 0, 0), (255, 255, 255), (255, 255, 0),
       (255, 0, 0), (0, 0, 255), (0, 255, 0))
CODES = (0, 1, 2, 3, 5, 6)


def convert(source, output, fit="contain", dither=False):
    with Image.open(source) as original:
        rgba = ImageOps.exif_transpose(original).convert("RGBA")
    image = Image.new("RGB", rgba.size, "white")
    image.paste(rgba, mask=rgba.getchannel("A"))
    if fit == "crop":
        canvas = ImageOps.fit(image, (800, 480), method=Image.Resampling.LANCZOS)
    else:
        image = ImageOps.contain(image, (800, 480), method=Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (800, 480), "white")
        canvas.paste(image, ((800 - image.width) // 2, (480 - image.height) // 2))
    palette = Image.new("P", (1, 1))
    palette.putpalette([component for color in RGB for component in color] + [255] * (768 - 18))
    colored = canvas.quantize(palette=palette, dither=(Image.Dither.FLOYDSTEINBERG
                              if dither else Image.Dither.NONE)).convert("RGB")
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.suffix.lower() == ".bmp":
        colored.save(output, format="BMP")
    elif output.suffix.lower() == ".e6":
        mapping = dict(zip(RGB, CODES))
        pixels = list(colored.getdata())
        packed = bytes(mapping[pixels[n]] * 16 + mapping[pixels[n + 1]]
                       for n in range(0, len(pixels), 2))
        output.write_bytes(struct.pack("<4sHHI4x", b"E6P1", 800, 480, len(packed)) + packed)
    else:
        raise ValueError("output extension must be .bmp or .e6")
    return colored


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--fit", choices=("contain", "crop"), default="contain")
    parser.add_argument("--dither", action="store_true", help="use for photos; omit for text/graphics")
    args = parser.parse_args()
    convert(args.source, args.output, args.fit, args.dither)
    print("Saved:", args.output)


if __name__ == "__main__":
    main()
