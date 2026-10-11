"""Copy this and firmware modules to MicroPython flash, not the TF card."""
import time

# USB gives time to interrupt with Ctrl-C/mpremote before automatic startup.
from machine import Pin
if Pin(24, Pin.IN).value():
    print("PhotoPainter: starting in 5s; Ctrl-C opens REPL")
    time.sleep_ms(5000)

from framebuffer import FRAME
from app import run
run(FRAME)
