"""Cron-controlled PhotoPainter, retained content, and RTC battery power-off."""
import gc
import binascii
import hashlib
import json
import os
import time
import sign_log as log

from calendar_time import from_seconds, to_seconds
from scheduler import Schedule, card_path
from timing import report, ticks_ms

ROOT = "/sd"
DEFAULTS = {
    "cron": "/cron", "font": "/fonts/sign.e6f",
    "default": "/text/default.txt", "rotation": 180,
    "battery_sleep": True, "wake_checkpoint_minutes": 360,
    "retry_minutes": 5, "low_battery_voltage": 3.1,
    "status_seconds": 60,
    "text": {"scale": 1, "margin": 24, "line_spacing": 8,
             "foreground": 0, "background": 1},
    "logging": log.DEFAULTS,
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
    for key, upper in (("wake_checkpoint_minutes", 360), ("retry_minutes", 60),
                       ("status_seconds", 600)):
        if not isinstance(config[key], int) or not 1 <= config[key] <= upper:
            raise ValueError(key + " out of range")
    if not isinstance(config["low_battery_voltage"], (int, float)) or not (
            2.8 <= config["low_battery_voltage"] <= 3.5):
        raise ValueError("invalid low_battery_voltage")
    if not isinstance(config["text"], dict):
        raise ValueError("text settings must be an object")
    config["logging"] = log.validate_settings(config["logging"])
    return config


def read_schedule(root, config):
    with open(root + relative_file(config["cron"]), "r") as stream:
        source = stream.read(16385)
    if len(source) > 16384:
        raise ValueError("cron file too large")
    return Schedule.parse(source)


def file_digest(path):
    digest = hashlib.sha256()
    chunk_size = min(4096, max(1, os.stat(path)[6]))
    with open(path, "rb") as stream:
        while True:
            # MicroPython reserves the requested size even for a short file.
            chunk = stream.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return binascii.hexlify(digest.digest()).decode()


def content_digest(root, path, config):
    is_text = path.lower().rsplit(".", 1)[-1] in ("txt", "md")
    limit = 8192 if is_text else 2000000
    if os.stat(root + path)[6] > limit:
        raise ValueError("content file exceeds supported size")
    digest = hashlib.sha256()
    digest.update(file_digest(root + path).encode())
    digest.update(str(config["rotation"]).encode())
    if is_text:
        # Version this key whenever TXT rasterization/cache semantics change.
        digest.update(b"E6C1-renderer-2")
        digest.update(path.lower().rsplit(".", 1)[-1].encode())
        digest.update(json.dumps(config["text"]).encode())
        font_path = relative_file(config["font"])
        metadata = os.stat(root + font_path)
        digest.update(font_path.encode("utf-8"))
        # TF-card font updates normally change size or FAT modification time.
        # If both are deliberately preserved, delete the sidecar to rebuild.
        digest.update(str((metadata[6], metadata[8])).encode())
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


def save_state(root, path, digest, previous_path=None):
    # FAT rename-overwrite is not portable. The old screen remains correct if an
    # interrupted write loses this cache; boot then performs one redundant refresh.
    temporary = root + "/.display-state.tmp"
    destination = root + "/.display-state.json"
    with open(temporary, "w") as stream:
        state = {"version": 1, "path": path, "digest": digest}
        if previous_path is not None:
            state["previous_path"] = previous_path
        # MicroPython json.dump has no indent argument. Keep generated JSON
        # four-space indented as well as the TF-card configuration.
        stream.write("{\n" + ",\n".join("    " + json.dumps(key) + ": " + json.dumps(state[key])
                                    for key in state) + "\n}\n")
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


def previous_content(state):
    return state.get("previous_path") if state.get("path") in (
        "@status", "@battery-empty") else state.get("path")


def battery_voltage(board):
    return sum(board.battery_voltage() for _ in range(16)) / 16


def empty_battery_shutdown(board, rtc, display, buffer, config, voltage, root=None):
    if board.usb() or voltage >= config["low_battery_voltage"]:
        return False
    board.set_working(True)
    log.warning("Battery empty; final warning then power-off; battery V:", voltage)
    try:
        rtc.disable_alarm()
    except Exception as exc:
        log.exception("Cannot disable low-battery RTC alarm", exc)
    board.activity.value(1)
    try:
        from battery_warning import empty_battery_frame
        state = load_state(root) if root is not None else {}
        digest = "shown-" + str(config["rotation"])
        if state.get("path") != "@battery-empty" or state.get("digest") != digest:
            previous = previous_content(state)
            # Pending forces a retry if power was lost during the final refresh.
            if root is not None:
                try:
                    save_state(root, "@battery-empty", "pending", previous)
                except Exception as exc:
                    log.exception("Cannot save empty-battery pending state", exc)
            display.display(empty_battery_frame(buffer, config["rotation"]))
            if root is not None:
                try:
                    save_state(root, "@battery-empty", digest, previous)
                except Exception as exc:
                    log.exception("Cannot save empty-battery shown state", exc)
    except Exception as exc:
        log.exception("Final battery warning failed", exc)
    finally:
        board.screen_power.value(0)
        board.activity.value(0)
        board.set_working(False)
        board.power_off()
    return not board.usb()


class Controller:
    def __init__(self, root, config, display, buffer=None):
        self.root, self.config, self.display = root, config, display
        self.buffer = buffer

    def update(self, schedule, now, fallback_path=None, voltage=None):
        started = ticks_ms()
        active = schedule.current(now)
        stage = report("select", started)
        path = active[1].path if active else self.config["default"]
        if path is None:
            path = fallback_path
        if path is None:
            log.info("No prior cron event; retain screen")
            return False
        path = card_path(path)
        from content import render_file
        from battery_warning import low_charge, overlay_low_battery
        warning = low_charge(voltage)
        frame = None
        try:
            gc.collect()
            digest = content_digest(self.root, path, self.config)
            state = load_state(self.root)
            stage = report("fingerprint", stage)
            is_text = path.lower().rsplit(".", 1)[-1] in ("txt", "md")
            if is_text:
                from text_cache import text_frame
                gc.collect()
                frame, digest = text_frame(
                    self.root + path, self.root + relative_file(self.config["font"]),
                    self.config["text"], self.config["rotation"], digest, self.buffer)
                stage = report("text_cache", stage)
            # Cache pixels remain clean. The display state also tracks the badge,
            # so crossing 10% refreshes even when the scheduled file is unchanged.
            if warning:
                digest += ":battery-low"
            if state.get("path") == path and state.get("digest") == digest:
                log.info("Content unchanged:", path)
                return False
            gc.collect()
            if not is_text:
                frame = render_file(self.root + path, self.root + relative_file(self.config["font"]),
                                    self.config["text"], self.config["rotation"], self.buffer)
                stage = report("render", stage)
            if warning:
                overlay_low_battery(frame, self.config["rotation"])
                log.warning("Low battery overlay; battery V:", voltage)
            gc.collect()
            self.display.display(frame)
            stage = report("display", stage)
            save_state(self.root, path, digest)
            report("state", stage)
        finally:
            del frame
            gc.collect()
            report("update_total", started)
        log.info("Displayed:", path)
        return True


def shut_down(board, rtc, target):
    board.set_working(True)
    rtc.set_alarm(target)
    board.sync()
    log.info("RTC wake:", target)
    if board.usb():
        board.set_working(False)
        return
    # Long font/image processing may cross the target. Do not power off with
    # an already-latched alarm or a time that has already passed.
    if to_seconds(rtc.read_time()) >= to_seconds(target) or not board.rtc_int.value():
        raise OSError("wake time passed or RTC INT still low; leave MCU running")
    button = getattr(board, "next_button", None)
    if button is not None and button.pressed():
        rtc.disable_alarm()
        log.info("NEXT before power-off; keep MCU on for status page")
        return False
    board.power_off()


def show_status(board, rtc, display, buffer, root, config, session):
    from status_page import render_status
    rtc.disable_alarm()
    now = rtc.read_time()
    started, elapsed = session.sample(now)
    voltage = battery_voltage(board)
    previous = load_state(root)
    previous_path = previous_content(previous)
    if previous_path is None and config["default"] is None and read_schedule(root, config).current(now) is None:
        log.warning("No normal content is available to restore; retain existing screen")
        return False
    frame = render_status(now, started, elapsed, voltage, config["status_seconds"],
                          root + relative_file(config["font"]), config["rotation"], buffer)
    from battery_warning import low_charge, overlay_low_battery
    if low_charge(voltage):
        overlay_low_battery(frame, config["rotation"])
    # Mark the transient screen before refresh, so power loss mid-refresh cannot
    # leave a cache claiming that the normal content is still on the panel.
    save_state(root, "@status", "temporary", previous_path)
    display.display(frame)
    session.shown(config["status_seconds"])
    log.info("Status page; restore in", config["status_seconds"], "seconds; battery V:", voltage)
    return True


def run(buffer, boot_ms=None, key_at_boot=False, rtc_wake=None, power_indicator=None):
    from board import Board
    from epaper import Epaper
    from rtc import PCF85063
    from status_page import StatusSession
    board = Board() if power_indicator is None else Board(power_indicator=power_indicator)
    rtc = PCF85063(board.i2c)
    display = Epaper.for_board(board)
    if rtc_wake is None:
        rtc_wake = not board.rtc_int.value()
    session = StatusSession(clock=time, boot_ms=boot_ms,
                            pending=key_at_boot or (not board.usb() and not rtc_wake))
    config = dict(DEFAULTS)
    mounted = False
    last_minute = None
    while True:
        try:
            if not mounted:
                board.set_working(True)
                started = ticks_ms()
                board.mount_sd()
                report("mount_sd", started)
                mounted = True
                log.configure(ROOT, DEFAULTS["logging"], rtc.read_time)
                config = read_config(ROOT)
                log.configure(ROOT, config["logging"], rtc.read_time)
                log.info("Started; USB:", board.usb(), "battery V:", board.battery_voltage())
            voltage = battery_voltage(board)
            if empty_battery_shutdown(board, rtc, display, buffer, config, voltage, ROOT):
                return
            now = rtc.read_time()
            session.sample(now)
            if board.next_button.pressed() or session.pending:
                board.set_working(True)
                session.pending = False
                config = read_config(ROOT)
                log.configure(ROOT, config["logging"], rtc.read_time)
                board.activity.value(1)
                show_status(board, rtc, display, buffer, ROOT, config, session)
                board.activity.value(0)
                board.set_working(False)
                continue
            if session.active():
                if not session.expired():
                    board.set_working(False)
                    time.sleep_ms(100)
                    continue
                session.finish()
                last_minute = None
                log.info("Status timeout; restore latest schedule")
            minute = to_seconds(now) // 60
            if last_minute != minute:
                board.set_working(True)
                started = ticks_ms()
                config = read_config(ROOT)
                log.configure(ROOT, config["logging"], rtc.read_time)
                schedule = read_schedule(ROOT, config)
                report("load_schedule", started)
                board.activity.value(1)
                controller = Controller(ROOT, config, display, buffer)
                state = load_state(ROOT)
                fallback = previous_content(state)
                controller.update(schedule, now, fallback, voltage)
                # Account for voltage sag during a long full-panel refresh.
                if empty_battery_shutdown(board, rtc, display, buffer, config,
                                          battery_voltage(board), ROOT):
                    return
                # A NEXT press during rendering is latched by its GPIO IRQ.
                if board.next_button.pressed():
                    session.pending = True
                    board.activity.value(0)
                    board.set_working(False)
                    continue
                board.activity.value(0)
                # Use time *after* rendering. Reconcile if refresh crossed an event.
                after = rtc.read_time()
                if to_seconds(after) // 60 != minute:
                    last_minute = minute
                    board.set_working(False)
                    continue
                next_minute = schedule.next_minute(after)
                if config["battery_sleep"] and not board.usb():
                    target = wake_target(after, next_minute, config["wake_checkpoint_minutes"])
                    if shut_down(board, rtc, target) is False:
                        session.pending = True
                        continue
                else:
                    rtc.disable_alarm()
                last_minute = minute
            board.set_working(False)
            time.sleep_ms(100)
        except KeyboardInterrupt:
            board.screen_power.value(0)
            board.activity.value(0)
            log.info("Stopped; USB REPL available")
            board.set_working(False)
            return
        except Exception as exc:
            board.set_working(True)
            board.screen_power.value(0)
            board.activity.value(0)
            log.exception("Sign error", exc)
            # The final warning also works when the TF card or RTC is invalid.
            try:
                if empty_battery_shutdown(board, rtc, display, buffer, config,
                                          battery_voltage(board), ROOT if mounted else None):
                    return
            except Exception as power_error:
                log.exception("Empty-battery power-off failed", power_error)
            # Retain the existing image and retry via RTC when battery-powered.
            if not session.active() and not board.usb() and config["battery_sleep"]:
                try:
                    now = rtc.read_time()
                    target = wake_target(now, None, retry_minutes=config["retry_minutes"])
                    if shut_down(board, rtc, target) is False:
                        session.pending = True
                except Exception as alarm_error:
                    log.exception("Cannot safely arm wake", alarm_error)
                    # Invalid RTC must be set over USB. Avoid silently draining battery.
                    try:
                        rtc.disable_alarm()
                        board.power_off()
                    except Exception as power_error:
                        log.exception("Power-off failed", power_error)
            last_minute = None
            board.set_working(False)
            time.sleep_ms(1000)
