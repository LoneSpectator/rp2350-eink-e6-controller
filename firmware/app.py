"""Cron-controlled PhotoPainter, retained content, and RTC battery power-off."""
import gc
import binascii
import hashlib
import json
import os
import time

from calendar_time import from_seconds, to_seconds
from scheduler import Schedule, card_path

ROOT = "/sd"
DEFAULTS = {
    "cron": "/schedule.cron", "font": "/fonts/sign.e6f",
    "default": "/text/default.txt", "rotation": 180,
    "battery_sleep": True, "wake_checkpoint_minutes": 360,
    "retry_minutes": 5, "low_battery_voltage": 3.1,
    "text": {"scale": 2, "margin": 24, "line_spacing": 8,
             "foreground": 0, "background": 1},
}


def relative_file(path):
    if not isinstance(path, str):
        raise ValueError("TF filename must be a string")
    parts = path.lstrip("/").split("/")
    if (any(part in ("", ".", "..") for part in parts) or
            "\\" in path or ":" in path or "\x00" in path):
        raise ValueError("invalid TF filename")
    return "/" + "/".join(parts)


def read_config(root):
    config = dict(DEFAULTS)
    try:
        with open(root + "/config.json", "r") as stream:
            source = stream.read(4097)
    except OSError as exc:
        if exc.args and exc.args[0] == 2:
            return config
        raise
    if len(source) > 4096:
        raise ValueError("config.json too large")
    custom = json.loads(source)
    if not isinstance(custom, dict):
        raise ValueError("config.json must be an object")
    for key in custom:
        if key not in DEFAULTS:
            raise ValueError("unknown config setting: " + key)
    config.update(custom)
    relative_file(config["cron"])
    relative_file(config["font"])
    if config["default"] is not None:
        card_path(config["default"])
    if config["rotation"] not in (0, 180) or not isinstance(config["battery_sleep"], bool):
        raise ValueError("invalid rotation or battery_sleep")
    for key, upper in (("wake_checkpoint_minutes", 360), ("retry_minutes", 60)):
        if not isinstance(config[key], int) or not 1 <= config[key] <= upper:
            raise ValueError(key + " out of range")
    if not isinstance(config["low_battery_voltage"], (int, float)) or not (
            2.8 <= config["low_battery_voltage"] <= 3.5):
        raise ValueError("invalid low_battery_voltage")
    if not isinstance(config["text"], dict):
        raise ValueError("text settings must be an object")
    return config


def read_schedule(root, config):
    with open(root + relative_file(config["cron"]), "r") as stream:
        source = stream.read(16385)
    if len(source) > 16384:
        raise ValueError("schedule.cron too large")
    return Schedule.parse(source)


def file_digest(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        while True:
            chunk = stream.read(4096)
            if not chunk:
                break
            digest.update(chunk)
    return binascii.hexlify(digest.digest()).decode()


def content_digest(root, path, config):
    limit = 8192 if path.lower().endswith(".txt") else 2000000
    if os.stat(root + path)[6] > limit:
        raise ValueError("content file exceeds supported size")
    digest = hashlib.sha256()
    digest.update(file_digest(root + path).encode())
    digest.update(str(config["rotation"]).encode())
    if path.lower().endswith(".txt"):
        digest.update(json.dumps(config["text"]).encode())
        # Include font bytes, so editing the font also invalidates the display cache.
        digest.update(file_digest(root + relative_file(config["font"])).encode())
    return binascii.hexlify(digest.digest()).decode()


def load_state(root):
    try:
        with open(root + "/.display-state.json", "r") as stream:
            source = stream.read(1025)
        if len(source) > 1024:
            return {}
        result = json.loads(source)
        return result if isinstance(result, dict) and result.get("version") == 1 else {}
    except (OSError, ValueError):
        return {}


def save_state(root, path, digest):
    # FAT rename-overwrite is not portable. The old screen remains correct if an
    # interrupted write loses this cache; boot then performs one redundant refresh.
    temporary = root + "/.display-state.tmp"
    destination = root + "/.display-state.json"
    with open(temporary, "w") as stream:
        json.dump({"version": 1, "path": path, "digest": digest}, stream)
    if hasattr(os, "sync"):
        os.sync()
    try:
        os.remove(destination)
    except OSError as exc:
        if not exc.args or exc.args[0] != 2:
            raise
    os.rename(temporary, destination)
    if hasattr(os, "sync"):
        os.sync()


def wake_target(now, next_minute, checkpoint_minutes=360, retry_minutes=None):
    current = to_seconds(now)
    target = current + checkpoint_minutes * 60
    if next_minute is not None:
        target = min(target, next_minute * 60)
    if retry_minutes is not None:
        target = min(target, current + retry_minutes * 60)
    # RTC has no month/year alarm match. Checkpoint within 6h makes the exact
    # day/time alarm unambiguous across months; annual cron still works.
    return from_seconds(max(current + 2, target))


class Controller:
    def __init__(self, root, config, display, buffer=None):
        self.root, self.config, self.display = root, config, display
        self.buffer = buffer

    def update(self, schedule, now):
        active = schedule.current(now)
        path = active[1].path if active else self.config["default"]
        if path is None:
            print("No prior cron event; retain screen")
            return False
        path = card_path(path)
        digest = content_digest(self.root, path, self.config)
        state = load_state(self.root)
        if state.get("path") == path and state.get("digest") == digest:
            print("Content unchanged:", path)
            return False
        from content import render_file
        gc.collect()
        frame = render_file(self.root + path, self.root + relative_file(self.config["font"]),
                            self.config["text"], self.config["rotation"], self.buffer)
        try:
            self.display.display(frame)
            save_state(self.root, path, digest)
        finally:
            del frame
            gc.collect()
        print("Displayed:", path)
        return True


def shut_down(board, rtc, target):
    rtc.set_alarm(target)
    board.sync()
    print("RTC wake:", target)
    if board.usb():
        return
    # Long font/image processing may cross the target. Do not power off with
    # an already-latched alarm or a time that has already passed.
    if to_seconds(rtc.read_time()) >= to_seconds(target) or not board.rtc_int.value():
        raise OSError("wake time passed or RTC INT still low; leave MCU running")
    board.power_off()


def run(buffer):
    from board import Board
    from epaper import Epaper
    from rtc import PCF85063
    board = Board()
    rtc = PCF85063(board.i2c)
    display = Epaper.for_board(board)
    config = dict(DEFAULTS)
    mounted = False
    last_minute = None
    while True:
        try:
            if not board.usb() and board.battery_voltage() < config["low_battery_voltage"]:
                print("Battery low; charge over USB")
                rtc.disable_alarm()
                board.power_off()
            if not mounted:
                board.mount_sd()
                mounted = True
            now = rtc.read_time()
            minute = to_seconds(now) // 60
            if last_minute != minute:
                config = read_config(ROOT)
                schedule = read_schedule(ROOT, config)
                board.activity.value(1)
                controller = Controller(ROOT, config, display, buffer)
                controller.update(schedule, now)
                board.activity.value(0)
                # Use time *after* rendering. Reconcile if refresh crossed an event.
                after = rtc.read_time()
                if to_seconds(after) // 60 != minute:
                    last_minute = minute
                    continue
                next_minute = schedule.next_minute(after)
                if config["battery_sleep"] and not board.usb():
                    target = wake_target(after, next_minute, config["wake_checkpoint_minutes"])
                    shut_down(board, rtc, target)
                else:
                    rtc.disable_alarm()
                last_minute = minute
            time.sleep_ms(1000)
        except KeyboardInterrupt:
            board.screen_power.value(0)
            board.activity.value(0)
            print("Stopped; USB REPL available")
            return
        except Exception as exc:
            board.screen_power.value(0)
            board.activity.value(0)
            print("Sign error:", exc)
            # Retain the existing image and retry via RTC when battery-powered.
            if not board.usb() and config["battery_sleep"]:
                try:
                    now = rtc.read_time()
                    target = wake_target(now, None, retry_minutes=config["retry_minutes"])
                    shut_down(board, rtc, target)
                except Exception as alarm_error:
                    print("Cannot safely arm wake:", alarm_error)
                    # Invalid RTC must be set over USB. Avoid silently draining battery.
                    try:
                        rtc.disable_alarm()
                        board.power_off()
                    except Exception as power_error:
                        print("Power-off failed:", power_error)
            last_minute = None
            time.sleep_ms(1000)
