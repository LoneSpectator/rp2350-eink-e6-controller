"""Level-filtered console diagnostics and bounded daily TF-card logs."""
import io
import os
import sys
import time

LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "OFF": 100}
DEFAULTS = {"level": "INFO", "directory": "/logs",
            "max_bytes": 65536, "backup_count": 3}


def validate_settings(settings):
    if not isinstance(settings, dict):
        raise ValueError("logging settings must be an object")
    result = dict(DEFAULTS)
    for key in settings:
        if key not in DEFAULTS:
            raise ValueError("unknown logging setting: " + key)
        result[key] = settings[key]
    if not isinstance(result["level"], str) or result["level"].upper() not in LEVELS:
        raise ValueError("logging level must be DEBUG, INFO, WARNING, ERROR or OFF")
    result["level"] = result["level"].upper()
    path = result["directory"]
    if not isinstance(path, str) or not path.startswith("/") or any(
            part in ("", ".", "..") for part in path[1:].split("/")) or any(
            value in path for value in ("\\", ":", "\x00")):
        raise ValueError("invalid logging directory")
    if not isinstance(result["max_bytes"], int) or not 1024 <= result["max_bytes"] <= 4194304:
        raise ValueError("logging max_bytes must be 1024..4194304")
    if not isinstance(result["backup_count"], int) or not 0 <= result["backup_count"] <= 10:
        raise ValueError("logging backup_count must be 0..10")
    return result


def remove_if_present(path):
    try:
        os.remove(path)
    except OSError as exc:
        if not exc.args or exc.args[0] != 2:
            raise


class Logger:
    def __init__(self):
        self.root = None
        self.settings = dict(DEFAULTS)
        self.rtc_time = None
        self.ready = False
        self.failed = False

    def configure(self, root, settings, rtc_time=None):
        updated = validate_settings(settings)
        if root != self.root or updated["directory"] != self.settings["directory"]:
            self.ready = False
        self.root, self.settings, self.rtc_time = root, updated, rtc_time
        self.failed = False

    def timestamp(self):
        if self.rtc_time is not None:
            try:
                return "%04d-%02d-%02d %02d:%02d:%02d" % self.rtc_time()
            except Exception:
                pass
        now = time.ticks_ms() if hasattr(time, "ticks_ms") else int(time.monotonic() * 1000)
        return "uptime_ms=%d" % now

    def make_directory(self):
        path = self.root
        for component in self.settings["directory"][1:].split("/"):
            path += "/" + component
            try:
                os.mkdir(path)
            except OSError as exc:
                if not exc.args or exc.args[0] != 17:  # EEXIST
                    raise
        self.ready = True

    def append(self, name, record):
        path = self.root + self.settings["directory"] + "/" + name + ".log"
        try:
            size = os.stat(path)[6]
        except OSError as exc:
            if not exc.args or exc.args[0] != 2:
                raise
            size = 0
        if size + len(record.encode("utf-8")) > self.settings["max_bytes"]:
            count = self.settings["backup_count"]
            if count:
                remove_if_present(path + "." + str(count))
                for index in range(count - 1, 0, -1):
                    try:
                        os.rename(path + "." + str(index), path + "." + str(index + 1))
                    except OSError as exc:
                        if not exc.args or exc.args[0] != 2:
                            raise
                try:
                    os.rename(path, path + ".1")
                except OSError as exc:
                    if not exc.args or exc.args[0] != 2:
                        raise
            else:
                remove_if_present(path)
        with open(path, "a") as stream:
            stream.write(record)
        if hasattr(os, "sync"):
            os.sync()

    def record(self, level, parts):
        if LEVELS[level] < LEVELS[self.settings["level"]]:
            return
        message = " ".join(str(part) for part in parts)
        stamp = self.timestamp()
        record = "[%s] [%s] %s\n" % (stamp, level, message)
        print(record.rstrip("\n"))
        if self.root is None or self.failed:
            return
        # Use the same RTC sample for the record and filename at midnight.
        name = "undated" if stamp.startswith("uptime_ms=") else stamp[:10]
        # Bound even an unusually large traceback without exceeding one file.
        limit = min(16384, self.settings["max_bytes"] // 4 - 64)
        if len(message) > limit:
            message = message[:limit - 16] + "... [truncated]"
        record = "[%s] [%s] %s\n" % (stamp, level, message)
        try:
            if not self.ready:
                self.make_directory()
            self.append(name, record)
        except (OSError, ValueError) as exc:
            self.failed = True
            print("[%s] [ERROR] Log write failed: %s" % (stamp, exc))

    def exception(self, message, exc):
        if LEVELS["ERROR"] < LEVELS[self.settings["level"]]:
            return
        if hasattr(sys, "print_exception"):
            stream = io.StringIO()
            sys.print_exception(exc, stream)
            trace = stream.getvalue()
        else:
            import traceback
            trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        self.record("ERROR", (message, "\n" + trace))


LOG = Logger()


def configure(root, settings, rtc_time=None):
    LOG.configure(root, settings, rtc_time)


def debug(*parts):
    LOG.record("DEBUG", parts)


def info(*parts):
    LOG.record("INFO", parts)


def warning(*parts):
    LOG.record("WARNING", parts)


def exception(message, exc):
    LOG.exception(message, exc)
