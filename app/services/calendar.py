"""Business-day calendar: weekends and South African public holidays are excluded."""
from datetime import date, datetime, timedelta

from app.models import PublicHoliday


def holidays_between(start, end):
    rows = PublicHoliday.query.filter(PublicHoliday.date >= start, PublicHoliday.date <= end).all()
    return {h.date for h in rows}


def is_business_day(d, holidays=None):
    if isinstance(d, datetime):
        d = d.date()
    if d.weekday() >= 5:
        return False
    if holidays is None:
        holidays = holidays_between(d, d)
    return d not in holidays


def add_business_days(start, days):
    """Move forward `days` business days, keeping the time of day for datetimes."""
    as_dt = isinstance(start, datetime)
    current = start.date() if as_dt else start
    holidays = holidays_between(current, current + timedelta(days=days * 3 + 30))
    added = 0
    while added < days:
        current += timedelta(days=1)
        if is_business_day(current, holidays):
            added += 1
    if as_dt:
        return datetime.combine(current, start.time())
    return current


def business_days_between(start, end):
    """Whole business days after `start` up to and including `end`."""
    if isinstance(start, datetime):
        start = start.date()
    if isinstance(end, datetime):
        end = end.date()
    if end <= start:
        return 0
    holidays = holidays_between(start, end)
    count, current = 0, start
    while current < end:
        current += timedelta(days=1)
        if is_business_day(current, holidays):
            count += 1
    return count


def business_hours_between(start, end):
    """Elapsed hours, counting only time that falls on business days."""
    if end <= start:
        return 0.0
    holidays = holidays_between(start.date(), end.date())
    total = 0.0
    cursor = start
    while cursor < end:
        next_midnight = datetime.combine(cursor.date() + timedelta(days=1), datetime.min.time())
        segment_end = min(next_midnight, end)
        if is_business_day(cursor.date(), holidays):
            total += (segment_end - cursor).total_seconds() / 3600
        cursor = segment_end
    return total


def observed_holidays(year, fixed, movable):
    """SA rule: a holiday on a Sunday is observed on the Monday after.
    `fixed` = [(month, day, name)], `movable` = [(date, name)]."""
    out = []
    for month, day, name in fixed:
        d = date(year, month, day)
        out.append((d, name))
        if d.weekday() == 6:
            out.append((d + timedelta(days=1), f"{name} (observed)"))
    out.extend(movable)
    return sorted(out)
