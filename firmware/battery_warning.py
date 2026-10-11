"""Red battery warnings drawn directly into the reusable packed frame."""
from content import HEIGHT, WIDTH, Canvas
from status_page import estimate_charge

RED, WHITE = 3, 1


def low_charge(voltage):
    return voltage is not None and estimate_charge(voltage) < 10


def rectangle(frame, x, y, width, height, color, rotation):
    if rotation == 180:
        x, y = WIDTH - x - width, HEIGHT - y - height
    # Byte-aligned spans, with individual edge nibbles preserved.
    begin, end = x, x + width
    first, last = (begin + 1) // 2, end // 2
    block = bytes((color * 17,)) * (last - first)
    for row in range(y, y + height):
        offset = row * (WIDTH // 2)
        if begin & 1:
            index = offset + begin // 2
            frame[index] = (frame[index] & 0xF0) | color
        if end & 1:
            index = offset + end // 2
            frame[index] = (frame[index] & 0x0F) | (color << 4)
        frame[offset + first:offset + last] = block


def battery(frame, x, y, width, height, stroke, rotation, empty=False):
    cap = max(4, width // 16)
    body = width - cap
    rectangle(frame, x, y, body, height, RED, rotation)
    rectangle(frame, x + stroke, y + stroke, body - 2 * stroke,
              height - 2 * stroke, WHITE, rotation)
    rectangle(frame, x + body, y + height // 3, cap,
              height - 2 * (height // 3), RED, rotation)
    if empty:
        # Exclamation mark, with no dependence on a font or TF-card file.
        middle = x + body // 2 - stroke
        rectangle(frame, middle, y + height // 4, stroke * 2,
                  height // 3, RED, rotation)
        rectangle(frame, middle, y + height * 2 // 3, stroke * 2,
                  stroke * 2, RED, rotation)
    else:
        rectangle(frame, x + stroke * 2, y + stroke * 2, stroke * 2,
                  height - stroke * 4, RED, rotation)


def overlay_low_battery(frame, rotation):
    # White backing keeps the red outline readable over photos of any color.
    rectangle(frame, WIDTH - 86, HEIGHT - 58, 76, 48, WHITE, rotation)
    battery(frame, WIDTH - 80, HEIGHT - 52, 64, 36, 3, rotation)
    return frame


def empty_battery_frame(buffer, rotation):
    canvas = Canvas(buffer=buffer)
    battery(canvas.data, (WIDTH - 448) // 2, (HEIGHT - 224) // 2,
            448, 224, 12, rotation, empty=True)
    return canvas.data
