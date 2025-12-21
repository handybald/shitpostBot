"""Date/time parsing and timezone utilities for scheduling"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional, Tuple
import re

# Default timezone from config
DEFAULT_TIMEZONE = "Europe/Istanbul"


def get_timezone(tz_name: str = DEFAULT_TIMEZONE) -> ZoneInfo:
    """Get ZoneInfo object for timezone"""
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo("UTC")


def parse_datetime_string(date_str: str, time_str: str, tz_name: str = DEFAULT_TIMEZONE) -> Tuple[Optional[datetime], Optional[str]]:
    """
    Parse date and time strings into UTC datetime object.

    Args:
        date_str: Date in YYYY-MM-DD format
        time_str: Time in HH:MM format
        tz_name: Timezone name (default: Europe/Istanbul)

    Returns:
        Tuple of (UTC datetime object or None, error message or None)

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

        # Create timezone-aware datetime
        tz = get_timezone(tz_name)
        dt = datetime(year, month, day, hour, minute, tzinfo=tz)

        # Convert to UTC for storage
        dt_utc = dt.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)

        # Check if date is in the past
        now_utc = datetime.utcnow()
        if dt_utc < now_utc:
            return None, f"Cannot schedule in the past. Time {date_str} {time_str} ({tz_name}) is before now"

        return dt_utc, None

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
    Format UTC datetime for user-friendly display in local timezone.

    Args:
        dt: UTC datetime (timezone-naive)
        tz_name: Target timezone name

    Returns:
        Formatted string like "2025-12-25 18:00 (TRT)"
    """
    try:
        # Convert UTC to target timezone
        dt_utc = dt.replace(tzinfo=ZoneInfo("UTC"))
        tz = get_timezone(tz_name)
        dt_local = dt_utc.astimezone(tz)

        return dt_local.strftime("%Y-%m-%d %H:%M (%Z)")
    except Exception:
        return dt.strftime("%Y-%m-%d %H:%M UTC")


def format_date_for_display(dt: datetime, tz_name: str = DEFAULT_TIMEZONE) -> str:
    """Format date for display"""
    try:
        dt_utc = dt.replace(tzinfo=ZoneInfo("UTC"))
        tz = get_timezone(tz_name)
        dt_local = dt_utc.astimezone(tz)
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
    if not isinstance(day, int):
        return False, "Day must be an integer"
    if not (0 <= day <= 6):
        return False, "Day must be 0-6 (0=Monday, 1=Tuesday, ..., 6=Sunday)"
    return True, None


def day_name(day: int) -> str:
    """Get day name from day number"""
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    return days[day] if 0 <= day <= 6 else "Unknown"
