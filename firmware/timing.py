"""Small phase timings for USB diagnostics; ticks_diff handles timer wrap."""
import time
import sign_log as log


def ticks_ms(clock=time):
    if hasattr(clock, "ticks_ms"):
        return clock.ticks_ms()
    return int(clock.monotonic() * 1000)


def report(phase, started, clock=time):
    ended = ticks_ms(clock)
    elapsed = clock.ticks_diff(ended, started) if hasattr(clock, "ticks_diff") else ended - started
    log.debug("[timing] %s: %d ms" % (phase, elapsed))
    return ended
