"""PhotoPainter (B) GPIO mapping from Waveshare DEV_Config.h (Pico 2)."""
import os
import time
from machine import ADC, I2C, Pin, SPI


class Board:
    def __init__(self, power_indicator=None):
        self.hold = Pin(18, Pin.OUT, value=1)
        self.screen_power = Pin(16, Pin.OUT, value=0)
        self.vbus = Pin(24, Pin.IN)
        self.key = Pin(19, Pin.IN, Pin.PULL_UP)
        from status_page import NextButton
        self.next_button = NextButton(self.key, Pin.IRQ_FALLING)
        self.rtc_int = Pin(6, Pin.IN, Pin.PULL_UP)
        self.charging = Pin(17, Pin.IN, Pin.PULL_UP)
        self.activity = Pin(25, Pin.OUT, value=0)
        from activity_led import ActivityIndicator
        self.activity_indicator = ActivityIndicator.for_hardware(self.activity)
        from power_led import PowerIndicator
        self.power_indicator = power_indicator or PowerIndicator.for_hardware()
        self.power_led = self.power_indicator.pin
        self.set_working(True)
        self.adc = ADC(29)
        self.i2c = I2C(1, sda=Pin(14), scl=Pin(15), freq=100000)
        self.sd_bus = None
        self.sd = None

    def usb(self):
        return bool(self.vbus.value())

    def set_working(self, working):
        self.power_indicator.set_working(working)

    def battery_voltage(self):
        return self.adc.read_u16() * 3.3 * 3 / 65535

    def mount_sd(self):
        from sdcard import SDCard
        from activity_led import IndicatedBlockDevice
        try:
            import vfs
        except ImportError:
            vfs = os
        self.sd_bus = SPI(0, sck=Pin(2), mosi=Pin(3), miso=Pin(4))
        self.activity_indicator.card_begin()
        try:
            device = SDCard(self.sd_bus, Pin(5, Pin.OUT, value=1), baudrate=4000000)
            self.sd = IndicatedBlockDevice(device, self.activity_indicator)
            filesystem = vfs.VfsFat(self.sd)
            vfs.mount(filesystem, "/sd")
        finally:
            self.activity_indicator.card_end()

    def sync(self):
        if hasattr(os, "sync"):
            os.sync()

    def power_off(self):
        if self.usb():
            return False
        self.sync()
        self.screen_power.value(0)
        self.activity.value(0)
        self.set_working(False)
        self.power_led.value(0)
        self.hold.value(0)
        time.sleep_ms(500)
        # If supply did not fall, retain power and report instead of claiming sleep.
        self.hold.value(1)
        raise OSError("power latch did not shut down the MCU; check board circuitry")
