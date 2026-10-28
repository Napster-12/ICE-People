"""Clock and formatting helpers. All times are Africa/Johannesburg, stored naive."""
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Africa/Johannesburg")


def now():
    return datetime.now(TZ).replace(tzinfo=None, microsecond=0)


def today():
    return now().date()


def _as_datetime(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def format_date(value):
    """24 Oct 2026"""
    d = _as_datetime(value)
    return f"{d.day:02d} {d:%b %Y}" if d else (value or "")


def format_datetime(value):
    d = _as_datetime(value)
    return f"{d.day:02d} {d:%b %Y %H:%M}" if d else (value or "")


def format_money(value, symbol=True):
    """R 1 234 567.00 (South African style: space thousands separator)."""
    if value is None or value == "":
        return "—"
    amount = Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sign = "-" if amount < 0 else ""
    whole, cents = f"{abs(amount):.2f}".split(".")
    groups = []
    while whole:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    text = f"{sign}{' '.join(groups)}.{cents}"
    return f"R {text}" if symbol else text


def to_decimal(value, default=None):
    if value is None or value == "":
        return default
    try:
        return Decimal(str(value).replace(" ", "").replace(",", "").replace("R", ""))
    except Exception:
        return default
