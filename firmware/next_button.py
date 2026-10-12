"""Debounced short/long NEXT presses, including edges during startup/refresh."""
import time


class NextButton:
    def __init__(self, pin, trigger, clock=time, long_press_ms=3000):
        self.clock, self.pin = clock, pin
        self.long_press_ms = long_press_ms
        self.down_at = self.now() if not pin.value() else None
        self.last_release = None
        self.released_ms = 0
        self.long_reported = False
        pin.irq(handler=self.edge, trigger=trigger)

    def now(self):
        return self.clock.ticks_ms() if hasattr(self.clock, "ticks_ms") else int(self.clock.monotonic() * 1000)

    def elapsed(self, now, previous):
        return self.clock.ticks_diff(now, previous) if hasattr(self.clock, "ticks_diff") else now - previous

    def edge(self, pin):
        now = self.now()
        if not pin.value():
            if self.down_at is None and (self.last_release is None or
                                        self.elapsed(now, self.last_release) >= 50):
                self.down_at = now
                self.long_reported = False
        elif self.down_at is not None:
            duration = self.elapsed(now, self.down_at)
            if not self.long_reported:
                self.released_ms = max(self.released_ms, duration)
            self.down_at = None
            self.last_release = now

    def pending(self):
        return self.released_ms >= 50 or (self.down_at is not None and not self.long_reported)

    def poll(self):
        if self.down_at is not None and not self.long_reported and (
                self.elapsed(self.now(), self.down_at) >= self.long_press_ms):
            self.long_reported = True
            self.released_ms = 0
            return "long"
        duration = self.released_ms
        self.released_ms = 0
        if duration >= self.long_press_ms:
            return "long"
        if duration >= 50:
            return "short"
        return None
