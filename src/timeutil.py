"""Small, pure helpers for time and money: clock, formatting, rounding."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

CURRENCIES = ("HUF", "EUR", "USD")

DATE_FORMAT = "%Y-%m-%d" # yyyy-MM-dd
CLOCK_FORMAT = "%H:%M:%S"
DATE_TIME_FORMAT = f"{DATE_FORMAT} - {CLOCK_FORMAT}"


def local_now() -> datetime:
    """Current local time, timezone-aware (so durations stay right across DST)."""
    return datetime.now().astimezone().replace(microsecond=0)


def start_of_day(day: date) -> datetime:
    """Local midnight at the start of `day`, timezone-aware."""
    return datetime.combine(day, time()).astimezone()


def whole_seconds(span: timedelta) -> int:
    return max(0, int(span.total_seconds()))


def format_duration(seconds: int) -> str:
    """Seconds as HH:MM:SS. Hours are not capped, so totals can read e.g. 141:12:30."""
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def parse_duration(text: str) -> int:
    hours, minutes, secs = (int(part) for part in text.split(":"))
    return hours * 3600 + minutes * 60 + secs


def decimals_for(currency: str) -> int:
    """Forint is billed in whole units, euro and dollar in cents."""
    return 0 if currency == "HUF" else 2


def wage(seconds: int, hourly_rate: Decimal, currency: str) -> Decimal:
    """Money earned in `seconds`, rounded half-up to the currency's smallest unit."""
    amount = Decimal(seconds) * hourly_rate / 3600
    unit = Decimal(1).scaleb(-decimals_for(currency))
    return amount.quantize(unit, rounding=ROUND_HALF_UP)


def format_money(amount: Decimal, currency: str, grouped: bool = False) -> str:
    """Hungarian notation: decimal comma, optionally a space between thousands.

    format_money(Decimal("12006"), "HUF")         -> "12006"
    format_money(Decimal("1234.5"), "EUR", True)  -> "1 234,50"
    """
    grouping = "," if grouped else ""
    text = format(amount, f"{grouping}.{decimals_for(currency)}f")   # e.g. "1,234.50"
    return text.replace(",", " ").replace(".", ",")
