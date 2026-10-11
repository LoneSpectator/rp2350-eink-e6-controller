"""ACT: steady during panel refresh, 5 Hz during card I/O, otherwise off."""
import time
from timing import ticks_ms


class ActivityIndicator:
    def __init__(self, pin, timer=None, clock=time):
        self.pin, self.timer, self.clock = pin, timer, clock
        self.refreshing = False
        self.card_depth = 0
        self.phase = True
        self.blink_at = self.last_io = ticks_ms(clock)
        pin.value(0)
        if timer is not None:
            timer.init(period=100, mode=timer.PERIODIC, callback=self.tick, hard=False)

    @classmethod
    def for_hardware(cls, pin):
        from machine import Timer
        return cls(pin, Timer(-1))

    def set_refreshing(self, refreshing):
        self.refreshing = bool(refreshing)
        self.tick()

    def card_begin(self):
        now = ticks_ms(self.clock)
        gap = self.clock.ticks_diff(now, self.last_io) if hasattr(self.clock, "ticks_diff") else now - self.last_io
        if not self.card_depth and (gap < 0 or gap >= 100):
            self.phase, self.blink_at = True, now
        self.card_depth += 1
        self.tick()

    def card_end(self):
        self.card_depth -= 1
        self.last_io = ticks_ms(self.clock)
        self.tick()

    def tick(self, timer=None):
        if self.refreshing:
            self.pin.value(1)
        elif self.card_depth:
            now = ticks_ms(self.clock)
            elapsed = self.clock.ticks_diff(now, self.blink_at) if hasattr(self.clock, "ticks_diff") else now - self.blink_at
            steps = elapsed // 100
            if steps:
                self.phase = bool(self.phase ^ (steps & 1))
                self.blink_at = now
            self.pin.value(int(self.phase))
        else:
            self.pin.value(0)


class IndicatedBlockDevice:
    """Observe all physical VFS reads/writes without changing the SD driver."""
    def __init__(self, device, activity):
        self.device, self.activity = device, activity

    def readblocks(self, block, buffer):
        self.activity.card_begin()
        try:
            return self.device.readblocks(block, buffer)
        finally:
            self.activity.card_end()

    def writeblocks(self, block, buffer):
        self.activity.card_begin()
        try:
            return self.device.writeblocks(block, buffer)
        finally:
            self.activity.card_end()

    def ioctl(self, operation, argument):
        return self.device.ioctl(operation, argument)
