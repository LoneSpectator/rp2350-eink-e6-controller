"""PWR stays on while firmware runs, including software-timed waits.

After firmware stops, charging blinks; power-off extinguishes the LED.
"""


class PowerIndicator:
    def __init__(self, pin, vbus, charging, timer=None):
        self.pin, self.vbus, self.charging = pin, vbus, charging
        self.timer = timer
        self.working = True
        self.phase = False
        self.pin.value(1)
        if timer is not None:
            timer.init(period=500, mode=timer.PERIODIC, callback=self.tick, hard=False)

    @classmethod
    def for_hardware(cls):
        from machine import Pin, Timer
        return cls(Pin(26, Pin.OUT, value=1), Pin(24, Pin.IN),
                   Pin(17, Pin.IN, Pin.PULL_UP), Timer(-1))

    def set_working(self, working):
        working = bool(working)
        if working != self.working:
            self.working = working
            self.phase = False
            self.tick()

    def tick(self, timer=None):
        # Soft timer: no filesystem, logging, or screen work in the callback.
        if self.working:
            self.phase = False
            self.pin.value(1)
        elif self.vbus.value() and not self.charging.value():
            self.phase = not self.phase
            self.pin.value(int(self.phase))
        else:
            self.phase = False
            self.pin.value(0)
