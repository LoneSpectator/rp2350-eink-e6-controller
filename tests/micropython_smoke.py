"""Run with MicroPython v1.26.0 Unix; argv[1] is a disposable TF-card copy."""
import os
import sys

sys.path.insert(0, "firmware")
from framebuffer import FRAME
from app import Controller, empty_battery_shutdown, load_state, read_config, read_schedule, wake_target
from calendar_time import from_minutes, to_minutes
from content import BitmapFont, render_file
from rtc import PCF85063
from scheduler import Schedule
import sign_log as log

root = sys.argv[1]
now = (2026, 10, 12, 10, 0, 0)
config = read_config(root)
log.configure(root, {"debug": True}, lambda: now)
schedule = read_schedule(root, config)
assert schedule.current(now)[1].path == "/text/open.txt"
assert from_minutes(schedule.next_minute(now)) == (2026, 10, 12, 18, 0, 0)
assert from_minutes(Schedule.parse("0 0 29 2 * /leap.txt").next_minute(
    (2025, 3, 1, 0, 0, 0))) == (2028, 2, 29, 0, 0, 0)
assert wake_target((2026, 12, 31, 23, 59, 30),
                   to_minutes((2027, 1, 1, 0, 0, 0))) == (2027, 1, 1, 0, 0, 0)

font = BitmapFont(root + "/fonts/sign.e6f")
assert (font.width, font.height) == (64, 64)
assert len(font.glyph("中")[1]) == 512
assert len(font.glyph("A")[1]) == 512
font.close()


class Display:
    count = 0
    def display(self, frame):
        assert len(frame) == 192000
        self.count += 1


display = Display()
assert Controller(root, config, display, FRAME).update(schedule, now)
assert not Controller(root, config, display, FRAME).update(schedule, now)
assert display.count == 1
assert load_state(root)["path"] == "/text/open.txt"
assert os.stat(root + "/text/open.txt.e6cache")[6] == 192076
# Reboot-equivalent controllers alternate the user's two TXT paths. Returning
# to either cached file must not open the font or call the text renderer.
import text_cache
loop = Schedule.parse("*/5 * * * * /text/open.txt\n2-59/5 * * * * /text/closed.txt")
assert Controller(root, config, display, FRAME).update(loop, (2026, 10, 12, 10, 2, 0))
render = text_cache.render_file
def no_render(*args):
    raise AssertionError("cached text was rendered again")
text_cache.render_file = no_render
assert Controller(root, config, display, FRAME).update(loop, (2026, 10, 12, 10, 5, 0))
assert Controller(root, config, display, FRAME).update(loop, (2026, 10, 12, 10, 7, 0))
text_cache.render_file = render
assert display.count == 4
for path in ("/text/default.txt", "/text/closed.txt", "/pic/weekend.e6"):
    frame = render_file(root + path, root + "/fonts/sign.e6f", config["text"], 180, FRAME)
    assert len(frame) == 192000
    assert frame is FRAME
    del frame
markdown = Schedule.parse("* * * * * /text/notice.md")
assert Controller(root, config, display, FRAME).update(markdown, now)
text_cache.render_file = no_render
assert not Controller(root, config, display, FRAME).update(markdown, now)
text_cache.render_file = render
from status_page import render_status
assert render_status(now, now, 600, 3.75, 60, root + "/fonts/sign.e6f", 180, FRAME) is FRAME
from battery_warning import empty_battery_frame, overlay_low_battery
# Battery overlays are applied after cache loading, and removed on recovery.
text_cache.render_file = no_render
controller = Controller(root, config, display, FRAME)
assert controller.update(markdown, now, voltage=3.4)
assert not controller.update(markdown, now, voltage=3.4)
assert controller.update(markdown, now, voltage=3.75)
text_cache.render_file = render
assert overlay_low_battery(FRAME, 180) is FRAME
assert empty_battery_frame(FRAME, 180) is FRAME
class Indicator:
    def value(self, level):
        self.level = level

class EmptyBoard:
    activity, screen_power = Indicator(), Indicator()
    offs = 0
    def usb(self): return False
    def power_off(self):
        assert self.screen_power.level == self.activity.level == 0
        assert load_state(root)["digest"] == "shown-180"
        self.offs += 1

class Alarm:
    def disable_alarm(self): pass

board = EmptyBoard()
count = display.count
assert empty_battery_shutdown(board, Alarm(), display, FRAME, config, 3.0, root)
assert display.count == count + 1 and board.offs == 1
assert empty_battery_shutdown(board, Alarm(), display, FRAME, config, 3.0, root)
assert display.count == count + 1 and board.offs == 2
text_cache.render_file = no_render
assert controller.update(markdown, now, voltage=3.75)
text_cache.render_file = render
try:
    raise ValueError("smoke warning traceback")
except ValueError as exc:
    log.exception("Smoke exception", exc)
assert os.stat(root + "/logs/debug.log")[6] > 0
assert os.stat(root + "/logs/warnings.log")[6] > 0
print("MicroPython smoke passed: cron, Source Han 64px, TXT/Markdown cache, status, batteries, logs")
