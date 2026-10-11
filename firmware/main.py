"""Copy this and firmware modules to MicroPython flash, not the TF card."""
import time
from framebuffer import FRAME
import sign_log as log

# USB gives time to interrupt with Ctrl-C/mpremote before automatic startup.
from machine import Pin
if Pin(24, Pin.IN).value():
    log.info("PhotoPainter: starting in 5s; Ctrl-C opens REPL")
    time.sleep_ms(5000)

from app import run
run(FRAME, boot_ms=globals().get("_boot_ms"),
    key_at_boot=globals().get("_next_at_boot", False),
    rtc_wake=globals().get("_rtc_alarm_at_boot"))
