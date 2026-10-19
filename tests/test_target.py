"""TARGET's calendar, read for when the ECB publishes."""

from __future__ import annotations

from datetime import date

from meridian.plugin.v1 import operations_pb2 as ops

from ecb import target
from ecb.declared import TARGET_CALENDAR

from conftest import target_2026


def days() -> target.Days:
    return target.days_of(target_2026(ops.ReadCalendarParams(calendar_id=TARGET_CALENDAR)))


def test_a_closing_day_and_a_weekend_publish_nothing() -> None:
    held = days()
    assert held.publishes_on(date(2026, 10, 19))
    assert not held.publishes_on(date(2026, 10, 17))  # a Saturday
    assert not held.publishes_on(date(2026, 12, 25))
    assert target.closed(held, [date(2026, 4, 3), date(2026, 4, 7)]) == [date(2026, 4, 3)]


def test_the_next_rates_skip_the_closing_days() -> None:
    held = days()
    assert target.next_publication(held, date(2026, 10, 16)) == date(2026, 10, 19)
    # Christmas, St Stephen's Day on a Saturday, then Sunday.
    assert target.next_publication(held, date(2026, 12, 24)) == date(2026, 12, 28)


def test_a_calendar_not_held_assumes_monday_to_friday() -> None:
    unread = target.days_of(ops.ReadCalendarResult(found=False))
    assert unread.unread and unread.publishes_on(date(2026, 12, 25))
    assert not unread.publishes_on(date(2026, 10, 17))
    # Outside the coverage, Monday to Friday too.
    assert days().publishes_on(date(2030, 1, 1))
