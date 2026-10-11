"""Bounded-memory six-color image and Unicode bitmap-text renderer."""
import os
import struct

WIDTH, HEIGHT = 800, 480
COLORS = (0, 1, 2, 3, 5, 6)
RGB = ((0, 0, 0), (255, 255, 255), (255, 255, 0),
       (255, 0, 0), (0, 0, 255), (0, 255, 0))


def nearest_color(red, green, blue):
    best, distance = 0, 3 * 255 * 255 + 1
    for index, color in enumerate(RGB):
        value = (red - color[0]) ** 2 + (green - color[1]) ** 2 + (blue - color[2]) ** 2
        if value < distance:
            best, distance = COLORS[index], value
    return best


class Canvas:
    def __init__(self, width=WIDTH, height=HEIGHT, buffer=None):
        if width % 2:
            raise ValueError("canvas width must be even")
        self.width, self.height = width, height
        self.data = buffer if buffer is not None else bytearray(width * height // 2)
        if len(self.data) != width * height // 2:
            raise ValueError("incorrect reusable frame length")
        self.fill(1)

    def pixel(self, x, y, color):
        if not 0 <= x < self.width or not 0 <= y < self.height:
            raise ValueError("pixel outside canvas")
        offset = (y * self.width + x) // 2
        previous = self.data[offset]
        self.data[offset] = ((previous & 0xF0) | color) if x & 1 else (
            (previous & 0x0F) | (color << 4))

    def fill(self, color):
        value = color * 17
        # Slice a small fixed block, not a second full-frame allocation.
        block = bytes((value,)) * 1024
        for offset in range(0, len(self.data), 1024):
            size = min(1024, len(self.data) - offset)
            self.data[offset:offset + size] = block[:size]

    def rotate180(self):
        end = len(self.data) - 1
        for start in range(len(self.data) // 2):
            a, b = self.data[start], self.data[end - start]
            self.data[start] = (b >> 4) | ((b & 15) << 4)
            self.data[end - start] = (a >> 4) | ((a & 15) << 4)
        if len(self.data) & 1:
            i = len(self.data) // 2
            value = self.data[i]
            self.data[i] = (value >> 4) | ((value & 15) << 4)


def exact_read(stream, size):
    data = stream.read(size)
    if len(data) != size:
        raise ValueError("truncated file")
    return data


def read_bmp(path, canvas):
    with open(path, "rb") as stream:
        header = exact_read(stream, 14)
        if header[:2] != b"BM":
            raise ValueError("not a BMP")
        offset = struct.unpack_from("<I", header, 10)[0]
        info = exact_read(stream, 40)
        size, width, height, planes, bits, compression = struct.unpack_from("<IiiHHI", info)
        if size < 40 or offset < 14 + size:
            raise ValueError("invalid BMP header/offset")
        if width != canvas.width or abs(height) != canvas.height:
            raise ValueError("BMP must be 800x480 (no device-side resize)")
        if planes != 1 or bits != 24 or compression != 0:
            raise ValueError("BMP must be uncompressed 24-bit RGB")
        stride = (width * 3 + 3) & ~3
        if os.stat(path)[6] < offset + stride * abs(height):
            raise ValueError("truncated BMP pixels")
        stream.seek(offset)
        for row_number in range(abs(height)):
            row = exact_read(stream, stride)
            y = canvas.height - 1 - row_number if height > 0 else row_number
            destination = y * (canvas.width // 2)
            for x in range(0, canvas.width, 2):
                p = x * 3
                first = nearest_color(row[p + 2], row[p + 1], row[p])
                second = nearest_color(row[p + 5], row[p + 4], row[p + 3])
                canvas.data[destination + x // 2] = first * 16 + second


def read_e6(path, canvas):
    with open(path, "rb") as stream:
        magic, width, height, length = struct.unpack("<4sHHI4x", exact_read(stream, 16))
        if (magic != b"E6P1" or width != canvas.width or height != canvas.height or
                length != len(canvas.data)):
            raise ValueError("invalid E6P1 frame header")
        view = memoryview(canvas.data)
        for offset in range(0, length, 4096):
            size = min(4096, length - offset)
            if stream.readinto(view[offset:offset + size]) != size:
                raise ValueError("truncated E6P1 frame")
        if stream.read(1):
            raise ValueError("unexpected data after E6P1 frame")
        for value in canvas.data:
            if value >> 4 not in COLORS or value & 15 not in COLORS:
                raise ValueError("unsupported E6P1 color code")


class BitmapFont:
    """Sorted fixed-size Unicode records, read on demand from the TF card.

    Header <4sBBHII>: E6F1, cell width/height, bitmap bytes, count, reserved=0.
    Record: <I codepoint>, one-byte advance, MSB-first row-padded bitmap.
    """
    def __init__(self, path):
        self.stream = open(path, "rb")
        try:
            magic, self.width, self.height, self.size, self.count, reserved = struct.unpack(
                "<4sBBHII", exact_read(self.stream, 16))
            if (magic != b"E6F1" or reserved or not 1 <= self.width <= 64 or
                    not 1 <= self.height <= 64 or self.count > 100000 or
                    self.size != ((self.width + 7) // 8) * self.height):
                raise ValueError("invalid E6F1 font header")
            self.record_size = 5 + self.size
            if os.stat(path)[6] != 16 + self.count * self.record_size:
                raise ValueError("truncated E6F1 font")
        except Exception:
            self.stream.close()
            raise

    def close(self):
        self.stream.close()

    def glyph(self, character):
        target = ord(character)
        low, high = 0, self.count - 1
        while low <= high:
            mid = (low + high) // 2
            self.stream.seek(16 + mid * self.record_size)
            value, advance = struct.unpack("<IB", exact_read(self.stream, 5))
            if value == target:
                if not 1 <= advance <= self.width:
                    raise ValueError("invalid font advance")
                return advance, exact_read(self.stream, self.size)
            if value < target:
                low = mid + 1
            else:
                high = mid - 1
        raise ValueError("font missing character U+%04X; regenerate font" % target)


def draw_text(text, font, canvas, settings):
    margin = settings.get("margin", 24)
    scale = settings.get("scale", 2)
    spacing = settings.get("line_spacing", 8)
    foreground = settings.get("foreground", 0)
    background = settings.get("background", 1)
    if (not isinstance(margin, int) or margin < 0 or
            not isinstance(scale, int) or not 1 <= scale <= 4 or
            not isinstance(spacing, int) or spacing < 0 or
            foreground not in COLORS or background not in COLORS):
        raise ValueError("invalid text layout settings")
    if 2 * margin + font.width * scale > canvas.width or (
            2 * margin + font.height * scale > canvas.height):
        raise ValueError("text layout has no room for a glyph")
    canvas.fill(background)
    x, y = margin, margin
    right, bottom = canvas.width - margin, canvas.height - margin
    row_bytes = (font.width + 7) // 8
    for character in text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", "    "):
        if character == "\n":
            x, y = margin, y + font.height * scale + spacing
            continue
        advance, bitmap = font.glyph(character)
        cell_width = max(advance, font.width) * scale
        # Bitmap overhangs are contained within a cell, including the final glyph.
        if x + cell_width > right:
            x, y = margin, y + font.height * scale + spacing
        if y + font.height * scale > bottom:
            raise ValueError("TXT exceeds one screen; shorten it or reduce text scale")
        for gy in range(font.height):
            for gx in range(font.width):
                if bitmap[gy * row_bytes + gx // 8] & (0x80 >> (gx % 8)):
                    for sy in range(scale):
                        for sx in range(scale):
                            canvas.pixel(x + gx * scale + sx, y + gy * scale + sy, foreground)
        x += advance * scale


def render_file(path, font_path, settings=None, rotation=180, buffer=None):
    if rotation not in (0, 180):
        raise ValueError("supported screen rotations: 0, 180")
    canvas = Canvas(buffer=buffer)
    suffix = path.lower().rsplit(".", 1)[-1]
    if suffix == "bmp":
        read_bmp(path, canvas)
    elif suffix == "e6":
        read_e6(path, canvas)
    elif suffix == "txt":
        with open(path, "rb") as stream:
            data = stream.read(8193)
        if len(data) > 8192:
            raise ValueError("TXT exceeds 8192 bytes")
        text = data.decode("utf-8")
        if text.startswith("\ufeff"):
            text = text[1:]
        font = BitmapFont(font_path)
        try:
            draw_text(text, font, canvas, settings or {})
        finally:
            font.close()
    else:
        raise ValueError("unsupported content type")
    if rotation == 180:
        canvas.rotate180()
    return canvas.data
