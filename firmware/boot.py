"""Retain the battery power latch before importing application modules."""
from machine import Pin

_battery_hold = Pin(18, Pin.OUT, value=1)
# The screen's high voltage rail is enabled only during a successful update.
_screen_power = Pin(16, Pin.OUT, value=0)
