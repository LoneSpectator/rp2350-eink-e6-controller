"""Civil time arithmetic, independent of CPython/MicroPython epoch and timezone."""


def leap(year):
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def month_days(year, month):
    if month == 2:
        return 29 if leap(year) else 28
    return 30 if month in (4, 6, 9, 11) else 31


def validate(value):
    year, month, day, hour, minute, second = value
    if not 2000 <= year <= 2099 or not 1 <= month <= 12:
        raise ValueError("RTC year/month out of range")
    if not 1 <= day <= month_days(year, month):
        raise ValueError("RTC day out of range")
    if not 0 <= hour < 24 or not 0 <= minute < 60 or not 0 <= second < 60:
        raise ValueError("RTC time out of range")
    return value


def days(year, month, day):
    # Howard Hinnant's civil calendar arithmetic; day 0 = 1970-01-01.
    year -= month <= 2
    era = year // 400
    yoe = year - era * 400
    shifted = month + (-3 if month > 2 else 9)
    doy = (153 * shifted + 2) // 5 + day - 1
    return era * 146097 + yoe * 365 + yoe // 4 - yoe // 100 + doy - 719468


def civil(day_number):
    z = day_number + 719468
    era = z // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    year = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    day = doy - (153 * mp + 2) // 5 + 1
    month = mp + (3 if mp < 10 else -9)
    return year + (month <= 2), month, day


def to_minutes(value):
    validate(value)
    y, m, d, h, minute, _ = value
    return days(y, m, d) * 1440 + h * 60 + minute


def to_seconds(value):
    return to_minutes(value) * 60 + value[5]


def from_minutes(value):
    day, minutes = divmod(value, 1440)
    return civil(day) + (minutes // 60, minutes % 60, 0)


def from_seconds(value):
    minute, second = divmod(value, 60)
    return from_minutes(minute)[:5] + (second,)


def weekday(day_number):
    return (day_number + 4) % 7  # cron: Sunday 0
