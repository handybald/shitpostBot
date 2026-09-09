"""Date/time parsing and timezone utilities for scheduling.

Time convention (see issue #2):
    - User-facing input/output uses the configured IANA timezone
      (default Europe/Istanbul).
    - Application calculations use aware UTC datetime values.
    - SQLite DateTime columns persist UTC as naive values for compatibility.
      Conversion between aware and naive UTC values must always go through
      `utc_for_db` / `utc_from_db` - never a raw `datetime.utcnow()`.
    - ScheduleConfig.day_of_week is 0=Monday through 6=Sunday everywhere.
"""

from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from typing import Optional, Tuple, List, Dict, Any
import re

# Default timezone from config
DEFAULT_TIMEZONE = "Europe/Istanbul"

UTC = timezone.utc


def get_timezone(tz_name: str = DEFAULT_TIMEZONE) -> ZoneInfo:
    """Get ZoneInfo object for timezone"""
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo("UTC")


def now_utc() -> datetime:
    """Current time as an aware UTC datetime.

    This is the only sanctioned replacement for `datetime.utcnow()` in
    scheduling/publishing code - it returns an *aware* value so it can be
    compared safely against other aware values and never accidentally
    mixed with naive DB values.
    """
    return datetime.now(UTC)


def utc_for_db(dt: datetime) -> datetime:
    """Convert an aware datetime to a naive UTC datetime for DB storage.

    Args:
        dt: An aware datetime (any timezone).

    Returns:
        A naive datetime representing the same instant in UTC.

    Raises:
        ValueError: if `dt` is naive (ambiguous - refuse to guess).
    """
    if dt.tzinfo is None:
        raise ValueError("utc_for_db requires an aware datetime, got a naive one")
    return dt.astimezone(UTC).replace(tzinfo=None)


def utc_from_db(dt: Optional[datetime]) -> Optional[datetime]:
    """Convert a naive UTC datetime read from the DB into an aware UTC datetime.

    Args:
        dt: A naive datetime as stored by SQLite (assumed UTC), or None.

    Returns:
        An aware UTC datetime, or None if `dt` is None.
    """
    if dt is None:
        return None
    if dt.tzinfo is not None:
        # Already aware - normalize to UTC rather than guessing it's wrong.
        return dt.astimezone(UTC)
    return dt.replace(tzinfo=UTC)


def local_to_utc(dt_local: datetime, tz_name: str = DEFAULT_TIMEZONE) -> datetime:
    """Convert a datetime in the given local timezone to an aware UTC datetime.

    Args:
        dt_local: A datetime. If naive, it is interpreted as wall-clock time
            in `tz_name`. If aware, it is simply converted to UTC.
        tz_name: IANA timezone name to interpret naive input in.

    Returns:
        An aware UTC datetime.
    """
    if dt_local.tzinfo is None:
        tz = get_timezone(tz_name)
        dt_local = dt_local.replace(tzinfo=tz)
    return dt_local.astimezone(UTC)


def parse_datetime_string(date_str: str, time_str: str, tz_name: str = DEFAULT_TIMEZONE) -> Tuple[Optional[datetime], Optional[str]]:
    """
    Parse date and time strings into a naive UTC datetime suitable for DB storage.

    Args:
        date_str: Date in YYYY-MM-DD format
        time_str: Time in HH:MM format
        tz_name: Timezone name (default: Europe/Istanbul)

    Returns:
        Tuple of (naive UTC datetime object or None, error message or None)

    Examples:
        parse_datetime_string("2025-12-25", "18:00")
        parse_datetime_string("2025-12-25", "18:00", "America/New_York")
    """
    try:
        # Validate date format
        date_match = re.match(r'^(\d{4})-(\d{2})-(\d{2})$', date_str)
        if not date_match:
            return None, f"Invalid date format '{date_str}'. Use YYYY-MM-DD (e.g., 2025-12-25)"

        year, month, day = map(int, date_match.groups())

        # Validate time format
        time_match = re.match(r'^(\d{1,2}):(\d{2})$', time_str)
        if not time_match:
            return None, f"Invalid time format '{time_str}'. Use HH:MM (e.g., 18:00)"

        hour, minute = map(int, time_match.groups())

        # Validate ranges
        if not (1 <= month <= 12):
            return None, f"Month must be 1-12, got {month}"
        if not (1 <= day <= 31):
            return None, f"Day must be 1-31, got {day}"
        if not (0 <= hour <= 23):
            return None, f"Hour must be 0-23, got {hour}"
        if not (0 <= minute <= 59):
            return None, f"Minute must be 0-59, got {minute}"

        # Create timezone-aware datetime and convert to UTC
        dt_local = datetime(year, month, day, hour, minute)
        dt_utc_aware = local_to_utc(dt_local, tz_name)

        if dt_utc_aware <= now_utc():
            return None, f"Cannot schedule in the past. Time {date_str} {time_str} ({tz_name}) is before now"

        return utc_for_db(dt_utc_aware), None

    except ValueError as e:
        return None, f"Invalid date/time: {str(e)}"
    except Exception as e:
        return None, f"Error parsing date/time: {str(e)}"


def parse_time_string(time_str: str) -> Tuple[Optional[Tuple[int, int]], Optional[str]]:
    """
    Parse time string into (hour, minute) tuple.

    Args:
        time_str: Time in HH:MM format

    Returns:
        Tuple of ((hour, minute) or None, error message or None)
    """
    try:
        time_match = re.match(r'^(\d{1,2}):(\d{2})$', time_str)
        if not time_match:
            return None, f"Invalid time format '{time_str}'. Use HH:MM (e.g., 18:00)"

        hour, minute = map(int, time_match.groups())

        if not (0 <= hour <= 23):
            return None, f"Hour must be 0-23, got {hour}"
        if not (0 <= minute <= 59):
            return None, f"Minute must be 0-59, got {minute}"

        return (hour, minute), None

    except Exception as e:
        return None, f"Error parsing time: {str(e)}"


def format_datetime_for_display(dt: datetime, tz_name: str = DEFAULT_TIMEZONE) -> str:
    """
    Format a naive-UTC-from-DB (or aware) datetime for user-friendly display
    in the local timezone.

    Args:
        dt: Naive UTC datetime as stored in the DB, or an aware datetime.
        tz_name: Target timezone name

    Returns:
        Formatted string like "2025-12-25 18:00 (TRT)"
    """
    try:
        dt_aware = utc_from_db(dt)
        tz = get_timezone(tz_name)
        dt_local = dt_aware.astimezone(tz)

        return dt_local.strftime("%Y-%m-%d %H:%M (%Z)")
    except Exception:
        return dt.strftime("%Y-%m-%d %H:%M UTC")


def format_date_for_display(dt: datetime, tz_name: str = DEFAULT_TIMEZONE) -> str:
    """Format date for display"""
    try:
        dt_aware = utc_from_db(dt)
        tz = get_timezone(tz_name)
        dt_local = dt_aware.astimezone(tz)
        return dt_local.strftime("%Y-%m-%d")
    except Exception:
        return dt.strftime("%Y-%m-%d")


def validate_day_of_week(day: int) -> Tuple[bool, Optional[str]]:
    """
    Validate day of week number.

    Args:
        day: Day number (0=Mon, 1=Tue, ..., 6=Sun)

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not isinstance(day, int) or isinstance(day, bool):
        return False, "Day must be an integer"
    if not (0 <= day <= 6):
        return False, "Day must be 0-6 (0=Monday, 1=Tuesday, ..., 6=Sunday)"
    return True, None


def day_name(day: int) -> str:
    """Get day name from day number"""
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    return days[day] if 0 <= day <= 6 else "Unknown"


def compute_next_slot(
    schedules: List[Dict[str, Any]],
    now: datetime,
    tz_name: str = DEFAULT_TIMEZONE,
) -> Optional[datetime]:
    """
    Pure, deterministic calculation of the next scheduling slot.

    Args:
        schedules: List of dicts with keys "day_of_week" (0=Mon..6=Sun) and
            "time" (HH:MM string). Only slots the caller wants considered
            should be passed in (e.g. already filtered to `enabled=True`).
        now: Aware UTC datetime to compute "next" relative to. Never reads
            the real clock - callers must pass `now_utc()` (or a fake clock
            in tests).
        tz_name: IANA timezone name the schedules are expressed in.

    Returns:
        The next slot as an aware UTC datetime, strictly after `now`, or
        None if `schedules` is empty. Deterministic and side-effect free.
    """
    if not schedules:
        return None
    if now.tzinfo is None:
        raise ValueError("compute_next_slot requires an aware `now`, got a naive one")

    tz = get_timezone(tz_name)
    now_local = now.astimezone(tz)

    parsed_schedules = []
    for sched in schedules:
        day = sched["day_of_week"]
        hour, minute = map(int, sched["time"].split(":"))
        parsed_schedules.append((day, hour, minute))

    best_candidate: Optional[datetime] = None

    # Search a full week + 1 day of offsets to guarantee we find the next
    # occurrence of every configured slot regardless of today's weekday.
    for day_offset in range(0, 8):
        candidate_date = now_local.date() + timedelta(days=day_offset)
        candidate_weekday = candidate_date.weekday()

        for day, hour, minute in parsed_schedules:
            if day != candidate_weekday:
                continue

            candidate_local = datetime(
                candidate_date.year, candidate_date.month, candidate_date.day,
                hour, minute, tzinfo=tz
            )

            # Strictly after `now` - a slot at exactly `now` is treated as
            # already-passed so we never schedule "in the past instant".
            if candidate_local <= now_local:
                continue

            candidate_utc = candidate_local.astimezone(UTC)
            if best_candidate is None or candidate_utc < best_candidate:
                best_candidate = candidate_utc

        # Once we've found a candidate and fully scanned through the day it
        # falls on, we can stop as soon as we pass that day (further days
        # can only be later). We keep scanning day_offset in order, so the
        # first day_offset that yields any candidate gives the earliest one
        # for that day; once we have *a* candidate we only need to keep
        # going if a later day could still be earlier, which is impossible
        # here since day_offset increases monotonically in local time.
        if best_candidate is not None:
            break

    return best_candidate
