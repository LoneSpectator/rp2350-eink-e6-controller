"""Persist the last observed USB charging completion, never a boot estimate."""
import json
import os
import sign_log as log
from calendar_time import validate


class ChargeHistory:
    def __init__(self, root):
        self.root = root
        self.last_full = None
        self.was_charging = False
        for name in (".charge-state.json", ".charge-state.tmp"):
            try:
                path = root + "/" + name
                size = os.stat(path)[6]
                if size > 512:
                    raise ValueError("charge state too large")
                with open(path, "r") as stream:
                    state = json.loads(stream.read(size))
                if state.get("version") != 1:
                    raise ValueError("invalid charge state version")
                last = validate(tuple(state["last_full"]))
                if self.last_full is None or last > self.last_full:
                    self.last_full = last
            except OSError as exc:
                if not exc.args or exc.args[0] != 2:
                    log.warning("Cannot read charge history:", exc)
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                log.warning("Invalid charge history:", exc)

    def observe(self, usb, charging, voltage, now):
        complete = self.was_charging and usb and not charging and voltage >= 4.1
        self.was_charging = bool(usb and charging)
        if not complete:
            return False
        self.last_full = validate(tuple(now))
        try:
            temporary = self.root + "/.charge-state.tmp"
            destination = self.root + "/.charge-state.json"
            with open(temporary, "w") as stream:
                stream.write('{\n    "version": 1,\n    "last_full": ' +
                             json.dumps(self.last_full) + '\n}\n')
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
            log.info("Battery charge complete:", self.last_full)
        except OSError as exc:
            log.exception("Cannot save charge history", exc)
        return True
