"""Five numeric cron fields followed by one SD-card path. Never executes commands."""
from calendar_time import civil, days, to_minutes, weekday

MAX_ENTRIES = 64
HORIZON_DAYS = 366 * 8


def card_path(path):
    path = path.strip()
    if not path or "\\" in path or ":" in path or "\x00" in path:
        raise ValueError("invalid TF path")
    parts = path.lstrip("/").split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError("TF paths cannot contain empty, . or .. components")
    if not any(path.lower().endswith(suffix) for suffix in (".bmp", ".e6", ".txt", ".md")):
        raise ValueError("supported files: .bmp, .e6, .txt, .md")
    return "/" + "/".join(parts)


def parse_field(text, lower, upper, sunday=False):
    values = set()
    for item in text.split(","):
        pieces = item.split("/")
        if len(pieces) > 2 or not pieces[0]:
            raise ValueError("invalid cron field: " + text)
        step = int(pieces[1]) if len(pieces) == 2 else 1
        if step <= 0:
            raise ValueError("cron step must be positive")
        base = pieces[0]
        if base == "*":
            start, end = lower, upper
        elif "-" in base:
            bounds = base.split("-")
            if len(bounds) != 2:
                raise ValueError("invalid cron range")
            start, end = int(bounds[0]), int(bounds[1])
        else:
            start = int(base)
            end = upper if len(pieces) == 2 else start
        if not lower <= start <= end <= upper:
            raise ValueError("cron value out of range: " + text)
        for value in range(start, end + 1, step):
            values.add(0 if sunday and value == 7 else value)
    if not values:
        raise ValueError("empty cron field")
    return sorted(values)


class Entry:
    def __init__(self, fields, path, line_number):
        self.minutes = parse_field(fields[0], 0, 59)
        self.hours = parse_field(fields[1], 0, 23)
        self.dom = parse_field(fields[2], 1, 31)
        self.months = parse_field(fields[3], 1, 12)
        self.dow = parse_field(fields[4], 0, 7, sunday=True)
        # Conventional cron: fields beginning with * use AND; otherwise DOM/DOW OR.
        self.dom_star = fields[2].startswith("*")
        self.dow_star = fields[4].startswith("*")
        self.path = card_path(path)
        self.line_number = line_number

    def matches_day(self, day_number):
        year, month, day = civil(day_number)
        if not 2000 <= year <= 2099 or month not in self.months:
            return False
        dom = day in self.dom
        dow = weekday(day_number) in self.dow
        return dom and dow if self.dom_star or self.dow_star else dom or dow

    def occurrence(self, minute, direction, horizon=HORIZON_DAYS):
        day_number, limit = divmod(minute, 1440)
        hours = self.hours if direction == 1 else reversed(self.hours)
        # Materialize just 24 values, because the sequence is reused for each day.
        hours = tuple(hours)
        minutes = tuple(self.minutes if direction == 1 else reversed(self.minutes))
        for offset in range(horizon + 1):
            candidate_day = day_number + direction * offset
            if not self.matches_day(candidate_day):
                continue
            for hour in hours:
                for value in minutes:
                    time_of_day = hour * 60 + value
                    if offset == 0 and direction * (time_of_day - limit) < 0:
                        continue
                    return candidate_day * 1440 + time_of_day
        return None


class Schedule:
    def __init__(self, entries):
        self.entries = entries

    @classmethod
    def parse(cls, source):
        entries = []
        for number, line in enumerate(source.splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(None, 5)
            if len(parts) != 6:
                raise ValueError("cron line %d: expected five fields and a path" % number)
            try:
                entry = Entry(parts[:5], parts[5], number)
            except ValueError as exc:
                raise ValueError("cron line %d: %s" % (number, exc))
            entries.append(entry)
            if len(entries) > MAX_ENTRIES:
                raise ValueError("too many cron entries (max 64)")
        return cls(entries)

    def current(self, now):
        minute = to_minutes(now)
        best = None
        for entry in self.entries:
            event = entry.occurrence(minute, -1)
            if event is not None and (best is None or (event, entry.line_number) >
                                     (best[0], best[1].line_number)):
                best = event, entry
        return best

    def next_minute(self, now):
        minute = to_minutes(now) + 1
        best = None
        for entry in self.entries:
            event = entry.occurrence(minute, 1)
            if event is not None and (best is None or event < best):
                best = event
        return best
