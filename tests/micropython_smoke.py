"""Run with MicroPython v1.26.0 Unix; argv[1] is a disposable TF-card copy."""
import os
import sys

sys.path.insert(0, "firmware")
from framebuffer import FRAME
from app import Controller, load_state, read_config, read_schedule, wake_target
from calendar_time import from_minutes, to_minutes
from content import BitmapFont, render_file
from rtc import PCF85063
from scheduler import Schedule

root = sys.argv[1]
now = (2026, 10, 12, 10, 0, 0)
config = read_config(root)
schedule = read_schedule(root, config)
assert schedule.current(now)[1].path == "/text/open.txt"
assert from_minutes(schedule.next_minute(now)) == (2026, 10, 12, 18, 0, 0)
assert from_minutes(Schedule.parse("0 0 29 2 * /leap.txt").next_minute(
    (2025, 3, 1, 0, 0, 0))) == (2028, 2, 29, 0, 0, 0)
assert wake_target((2026, 12, 31, 23, 59, 30),
                   to_minutes((2027, 1, 1, 0, 0, 0))) == (2027, 1, 1, 0, 0, 0)

font = BitmapFont(root + "/fonts/sign.e6f")
assert len(font.glyph("中")[1]) == 128
assert len(font.glyph("A")[1]) == 128
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
for path in ("/text/default.txt", "/text/closed.txt", "/pic/weekend.e6"):
    frame = render_file(root + path, root + "/fonts/sign.e6f", config["text"], 180, FRAME)
    assert len(frame) == 192000
    assert frame is FRAME
    del frame
print("MicroPython smoke passed: cron, leap/year boundary, Chinese/English, E6, display cache")
