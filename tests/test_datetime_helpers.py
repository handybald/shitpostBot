"""Unit tests for the pure next-slot calculation and UTC<->local helpers."""

from datetime import datetime, timezone

import pytest

from src.utils import datetime_helpers as dh

TZ = "Europe/Istanbul"  # UTC+3 year-round since 2016 (no DST)


def utc(*args, **kwargs) -> datetime:
    return datetime(*args, tzinfo=timezone.utc, **kwargs)


MON_WED_FRI_1800 = [
    {"day_of_week": 0, "time": "18:00"},  # Monday
    {"day_of_week": 2, "time": "18:00"},  # Wednesday
    {"day_of_week": 4, "time": "18:00"},  # Friday
]


class TestComputeNextSlotBeforeAfter:
    def test_monday_before_configured_time_picks_monday(self):
        # 2026-01-05 is a Monday. 10:00 UTC = 13:00 Istanbul, before 18:00.
        now = utc(2026, 1, 5, 10, 0)
        result = dh.compute_next_slot(MON_WED_FRI_1800, now=now, tz_name=TZ)
        assert result == utc(2026, 1, 5, 15, 0)  # 18:00 Istanbul == 15:00 UTC

    def test_monday_after_configured_time_picks_wednesday(self):
        # 16:00 UTC = 19:00 Istanbul, after 18:00 -> rolls to Wednesday.
        now = utc(2026, 1, 5, 16, 0)
        result = dh.compute_next_slot(MON_WED_FRI_1800, now=now, tz_name=TZ)
        assert result == utc(2026, 1, 7, 15, 0)  # Wednesday 18:00 Istanbul

    def test_wednesday_before_configured_time_picks_wednesday(self):
        now = utc(2026, 1, 7, 10, 0)  # Wednesday
        result = dh.compute_next_slot(MON_WED_FRI_1800, now=now, tz_name=TZ)
        assert result == utc(2026, 1, 7, 15, 0)

    def test_wednesday_after_configured_time_picks_friday(self):
        now = utc(2026, 1, 7, 16, 0)  # Wednesday, after 18:00 local
        result = dh.compute_next_slot(MON_WED_FRI_1800, now=now, tz_name=TZ)
        assert result == utc(2026, 1, 9, 15, 0)  # Friday

    def test_friday_before_configured_time_picks_friday(self):
        now = utc(2026, 1, 9, 10, 0)  # Friday
        result = dh.compute_next_slot(MON_WED_FRI_1800, now=now, tz_name=TZ)
        assert result == utc(2026, 1, 9, 15, 0)

    def test_friday_after_configured_time_wraps_to_next_monday(self):
        now = utc(2026, 1, 9, 16, 0)  # Friday, after 18:00 local
        result = dh.compute_next_slot(MON_WED_FRI_1800, now=now, tz_name=TZ)
        assert result == utc(2026, 1, 12, 15, 0)  # Next Monday

    def test_weekend_picks_next_monday(self):
        now = utc(2026, 1, 10, 10, 0)  # Saturday
        result = dh.compute_next_slot(MON_WED_FRI_1800, now=now, tz_name=TZ)
        assert result == utc(2026, 1, 12, 15, 0)


class TestIstanbulUtcConversion:
    def test_local_to_utc_istanbul_is_utc_plus_3(self):
        dt_local = datetime(2026, 6, 15, 18, 0)  # naive, interpreted as Istanbul
        result = dh.local_to_utc(dt_local, TZ)
        assert result == utc(2026, 6, 15, 15, 0)

    def test_format_datetime_for_display_round_trip(self):
        naive_utc_from_db = datetime(2026, 6, 15, 15, 0)  # naive UTC as stored
        formatted = dh.format_datetime_for_display(naive_utc_from_db, TZ)
        assert "18:00" in formatted


class TestYearMonthBoundary:
    def test_new_year_boundary(self):
        # Dec 31 2025 is a Wednesday; after 18:00 local -> next slot is
        # Friday Jan 2 2026, crossing both a month and a year boundary.
        now = utc(2025, 12, 31, 16, 0)
        result = dh.compute_next_slot(MON_WED_FRI_1800, now=now, tz_name=TZ)
        assert result == utc(2026, 1, 2, 15, 0)

    def test_month_boundary(self):
        # Jan 30 2026 is a Friday; after 18:00 local -> next slot is
        # Monday Feb 2 2026, crossing a month boundary.
        now = utc(2026, 1, 30, 16, 0)
        result = dh.compute_next_slot(MON_WED_FRI_1800, now=now, tz_name=TZ)
        assert result == utc(2026, 2, 2, 15, 0)


class TestSameMinuteScheduling:
    def test_exact_slot_instant_rolls_to_next_occurrence(self):
        # `now` is exactly Monday 18:00:00.000000 Istanbul (15:00 UTC) - the
        # slot must be treated as already-passed (strictly-after semantics),
        # never scheduled "at" the current instant.
        now = utc(2026, 1, 5, 15, 0, 0)
        result = dh.compute_next_slot(MON_WED_FRI_1800, now=now, tz_name=TZ)
        assert result == utc(2026, 1, 7, 15, 0)  # rolls to Wednesday

    def test_one_second_before_slot_still_picks_it(self):
        now = utc(2026, 1, 5, 14, 59, 59)
        result = dh.compute_next_slot(MON_WED_FRI_1800, now=now, tz_name=TZ)
        assert result == utc(2026, 1, 5, 15, 0, 0)

    def test_one_second_after_slot_rolls_forward(self):
        now = utc(2026, 1, 5, 15, 0, 1)
        result = dh.compute_next_slot(MON_WED_FRI_1800, now=now, tz_name=TZ)
        assert result == utc(2026, 1, 7, 15, 0)


class TestComputeNextSlotEdgeCases:
    def test_empty_schedules_returns_none(self):
        assert dh.compute_next_slot([], now=utc(2026, 1, 5, 10, 0), tz_name=TZ) is None

    def test_naive_now_raises(self):
        with pytest.raises(ValueError):
            dh.compute_next_slot(MON_WED_FRI_1800, now=datetime(2026, 1, 5, 10, 0), tz_name=TZ)

    def test_utc_for_db_requires_aware(self):
        with pytest.raises(ValueError):
            dh.utc_for_db(datetime(2026, 1, 5, 10, 0))

    def test_utc_for_db_and_utc_from_db_round_trip(self):
        aware = utc(2026, 1, 5, 10, 30)
        naive = dh.utc_for_db(aware)
        assert naive.tzinfo is None
        back = dh.utc_from_db(naive)
        assert back == aware
