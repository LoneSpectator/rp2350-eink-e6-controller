"""NEXT-key status page, monotonic return timer and approximate Li-ion charge."""
import time

from calendar_time import from_seconds, to_seconds
from content import BitmapFont, Canvas
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


class NextButton:
    def __init__(self, pin, falling_trigger, clock=time):
        self.clock, self.pin = clock, pin
        self.pending = not pin.value()
        self.last_edge = None
        pin.irq(handler=self.edge, trigger=falling_trigger)

    def edge(self, pin):
        now = ticks_ms(self.clock)
        if self.last_edge is None or difference(self.clock, now, self.last_edge) >= 50:
            self.pending = True
            self.last_edge = now

    def pressed(self):
        result = self.pending
        self.pending = False
        return result


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


def status_text(now, started, elapsed, voltage, seconds):
    days, remainder = divmod(elapsed, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds_elapsed = divmod(remainder, 60)
    percent = estimate_charge(voltage)
    color = "red" if percent <= 20 else "black"
    return ('## 设备状态\n当前：%s\n启动：%s\n运行：%dd %02d:%02d:%02d\n'
            '电池：%.2f V\n<span style="color: %s">电量：%d%%</span>') % (
                date_text(now), date_text(started), days, hours,
                minutes, seconds_elapsed, voltage, color, percent)


def render_status(now, started, elapsed, voltage, seconds, font_path, rotation, buffer):
    from markdown_content import draw_markdown
    canvas = Canvas(buffer=buffer)
    font = BitmapFont(font_path)
    try:
        draw_markdown(status_text(now, started, elapsed, voltage, seconds), font, canvas,
                      {"margin": 24, "scale": 2, "line_spacing": 8})
    finally:
        font.close()
    if rotation == 180:
        canvas.rotate180()
    return canvas.data
