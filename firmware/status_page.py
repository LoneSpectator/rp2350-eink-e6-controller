"""NEXT-key status page, monotonic return timer and approximate Li-ion charge."""
import time

from calendar_time import from_seconds, to_seconds
from content import BitmapFont, Canvas, paint_glyph
from timing import ticks_ms

# Generic single-cell Li-ion curve, not a calibrated fuel gauge.
CHARGE_CURVE = ((3.2, 0), (3.3, 5), (3.5, 10), (3.6, 20), (3.7, 40),
                (3.8, 60), (3.9, 75), (4.0, 85), (4.1, 95), (4.2, 100))


def estimate_charge(voltage):
    if voltage <= CHARGE_CURVE[0][0]:
        return 0
    for index in range(1, len(CHARGE_CURVE)):
        high_v, high_p = CHARGE_CURVE[index]
        low_v, low_p = CHARGE_CURVE[index - 1]
        if voltage <= high_v:
            return int(low_p + (voltage - low_v) * (high_p - low_p) / (high_v - low_v) + 0.5)
    return 100


def difference(clock, now, previous):
    return clock.ticks_diff(now, previous) if hasattr(clock, "ticks_diff") else now - previous


class StatusSession:
    def __init__(self, clock=time, boot_ms=None, pending=False):
        self.clock = clock
        self.last_tick = ticks_ms(clock)
        self.elapsed_ms = 0 if boot_ms is None else difference(clock, self.last_tick, boot_ms)
        self.started_at = None
        self.restore_at = None
        self.pending = pending

    def uptime_ms(self):
        now = ticks_ms(self.clock)
        self.elapsed_ms += difference(self.clock, now, self.last_tick)
        self.last_tick = now
        return self.elapsed_ms

    def sample(self, now):
        elapsed = self.uptime_ms() // 1000
        if self.started_at is None:
            self.started_at = from_seconds(to_seconds(now) - elapsed)
        return self.started_at, elapsed

    def shown(self, seconds):
        self.restore_at = self.uptime_ms() + seconds * 1000

    def active(self):
        return self.restore_at is not None

    def expired(self):
        return self.active() and self.uptime_ms() >= self.restore_at

    def finish(self):
        self.restore_at = None


def date_text(value):
    return "%04d-%02d-%02d %02d:%02d:%02d" % value


def status_text(now, last_full, voltage):
    charged = date_text(last_full) if last_full is not None else "未知"
    standby = "未知"
    if last_full is not None:
        elapsed = to_seconds(now) - to_seconds(last_full)
        if elapsed >= 0:
            days, remainder = divmod(elapsed, 86400)
            hours, remainder = divmod(remainder, 3600)
            minutes, seconds_elapsed = divmod(remainder, 60)
            standby = "%dd %02d:%02d:%02d" % (days, hours, minutes, seconds_elapsed)
    percent = estimate_charge(voltage)
    return ('设备状态\n当前：%s\n充电：%s\n待机：%s\n'
            '电池：%.2f V    %d%%') % (
                date_text(now), charged, standby, voltage, percent)


def render_status(now, last_full, voltage, font_path, rotation, buffer):
    canvas = Canvas(buffer=buffer)
    font = BitmapFont(font_path)
    def width(text):
        return sum(font.glyph(char)[0] for char in text)
    def draw(text, x, y, color=0, bold=False):
        for char in text:
            advance, bitmap = font.glyph(char)
            paint_glyph(font, bitmap, canvas, x, y, 1, color, bold)
            x += advance
    try:
        if font.height > 72:
            raise ValueError("status font height must be at most 72 pixels")
        lines = status_text(now, last_full, voltage).splitlines()
        draw(lines[0], (canvas.width - width(lines[0])) // 2, 20, bold=True)
        for index, line in enumerate(lines[1:4]):
            if width(line) > canvas.width - 48:
                raise ValueError("status font too wide for a full date/time line")
            draw(line, 24, 108 + index * 80)
        draw("电池：%.2f V" % voltage, 24, 348)
        percent = estimate_charge(voltage)
        value = "%d%%" % percent
        draw(value, canvas.width - 24 - width(value), 348, 3 if percent <= 20 else 0)
    finally:
        font.close()
    if rotation == 180:
        canvas.rotate180()
    return canvas.data
