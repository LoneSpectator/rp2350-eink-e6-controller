"""Copy this and firmware modules to MicroPython flash, not the TF card."""
import time
from framebuffer import FRAME
import sign_log as log
from power_led import PowerIndicator

# Kept in main's globals so the timer can continue idle charging indication
# after Ctrl-C returns to the USB REPL.
power_indicator = PowerIndicator.for_hardware()

try:
    # This delay is counted by the running MCU, so PWR stays on.
    from machine import Pin
    if Pin(24, Pin.IN).value():
        log.info("PhotoPainter: starting in 5s; Ctrl-C opens REPL")
        time.sleep_ms(5000)
    from app import run
    run(FRAME, boot_ms=globals().get("_boot_ms"),
        key_at_boot=globals().get("_next_at_boot", False),
        rtc_wake=globals().get("_rtc_alarm_at_boot"), power_indicator=power_indicator)
finally:
    power_indicator.set_working(False)
