"""Copy this and firmware modules to MicroPython flash, not the TF card."""
import time
from framebuffer import FRAME
import sign_log as log
from power_led import PowerIndicator

# Kept in main's globals so the timer can continue idle charging indication
# after Ctrl-C returns to the USB REPL.
power_indicator = PowerIndicator.for_hardware()

# USB gives time to interrupt with Ctrl-C/mpremote before automatic startup.
from machine import Pin
if Pin(24, Pin.IN).value():
    power_indicator.set_working(False)
    log.info("PhotoPainter: starting in 5s; Ctrl-C opens REPL")
    time.sleep_ms(5000)

power_indicator.set_working(True)
try:
    from app import run
    run(FRAME, boot_ms=globals().get("_boot_ms"),
        key_at_boot=globals().get("_next_at_boot", False),
        rtc_wake=globals().get("_rtc_alarm_at_boot"), power_indicator=power_indicator)
finally:
    power_indicator.set_working(False)
