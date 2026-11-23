"""Slot finding. Pure functions over naive wall-clock datetimes in the
configured timezone, so they are easy to test."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta

from .config import Account

SEARCH_DAYS = 400


def now_in(tz_name: str) -> datetime:
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo(tz_name)).replace(tzinfo=None, second=0, microsecond=0)
    except Exception:  # no tz database (e.g. Windows without tzdata): local clock
        return datetime.now().replace(second=0, microsecond=0)


def next_slot(account: Account, taken: list[datetime], earliest: datetime) -> datetime:
    """First posting slot for `account` at or after `earliest` that is not
    already taken and keeps the day under max_per_day."""
    taken_set = set(taken)
    per_day: Counter[date] = Counter(t.date() for t in taken)
    day = earliest.date()
    for _ in range(SEARCH_DAYS):
        if day.weekday() in account.days and per_day[day] < account.max_per_day:
            for t in account.times:
                dt = datetime.combine(day, t)
                if dt >= earliest and dt not in taken_set:
                    return dt
        day += timedelta(days=1)
    raise RuntimeError(f"No free slot for {account.id} in the next {SEARCH_DAYS} days")


def earliest_for(account: Account, now: datetime, lead_minutes: int, not_before: datetime | None) -> datetime:
    lead = max(lead_minutes, account.spec["min_lead_minutes"])
    start = now + timedelta(minutes=lead)
    if not_before and not_before > start:
        start = not_before
    return start


def window_opens(account: Account, slot: datetime) -> datetime | None:
    """When the site's scheduler first lets you pick `slot`. None = already."""
    if account.horizon_days is None:
        return None
    # one hour of slack so we never sit right on the platform's edge
    return slot - timedelta(days=account.horizon_days) + timedelta(hours=1)


def is_ready(account: Account, slot: datetime, now: datetime) -> bool:
    opens = window_opens(account, slot)
    return opens is None or opens <= now
