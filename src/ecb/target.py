"""The days the ECB publishes on, from the dataset's calendar: the euro's,
TARGET's closing days, which core holds as reference data (contract v22,
W1.20; spec/settlement-calendars-are-core-reference-data).

The ECB updates its reference rates "every working day, except on TARGET
closing days" (its reference rates page). So the plugin reads the platform's
"Euro (TARGET)" calendar (`ReadCalendar`, the catalogue's `calendar_id`)
over the days it needs, as of now, and takes a day as one the ECB publishes
on when it is no weekend of the calendar's and not a closed day, or a
weekend day the calendar lists open. Two things read it:

- the next rates expected, on Connection: the first such day after the
  latest the portal stated, around 16:00 CET;
- a want: a day asked that TARGET closes is declined `source_silent` at
  once, without asking the portal, since the ECB states nothing for it.

A calendar the deployment cannot answer -- not held and the platform not
reached, or a day outside its coverage -- is said, and the plugin then takes
Monday to Friday, which is right on every day but TARGET's six closing days
a year: a want for one of those is asked of the portal, which answers no
rate, and is declined `source_silent` all the same.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import meridian
from meridian.plugin.v1 import operations_pb2 as ops

from .declared import TARGET_CALENDAR

log = logging.getLogger("ecb")

#: Monday to Sunday as the calendar names them, by `date.weekday()`.
_WEEKDAYS = {
    ops.WEEKDAY_MONDAY: 0,
    ops.WEEKDAY_TUESDAY: 1,
    ops.WEEKDAY_WEDNESDAY: 2,
    ops.WEEKDAY_THURSDAY: 3,
    ops.WEEKDAY_FRIDAY: 4,
    ops.WEEKDAY_SATURDAY: 5,
    ops.WEEKDAY_SUNDAY: 6,
}
#: How far ahead the next rates are looked for: past any run of closing days.
AHEAD = 14


@dataclass
class Days:
    """A range of the calendar as read: the days it closes and opens, its
    weekends by the date each began, and its coverage; or why it was not
    read (`unread`), the weekdays then assumed."""

    closed: set[date] = field(default_factory=set)
    opened: set[date] = field(default_factory=set)
    weekends: list[tuple[date, frozenset[int]]] = field(default_factory=list)
    covered_from: date | None = None
    covered_to: date | None = None
    version: int = 0
    unread: str = ""

    def covers(self, day: date) -> bool:
        return (
            not self.unread
            and self.covered_from is not None
            and self.covered_to is not None
            and self.covered_from <= day <= self.covered_to
        )

    def publishes_on(self, day: date) -> bool:
        """Whether the ECB publishes on `day` by the calendar, or by Monday to
        Friday where the calendar does not cover it."""
        if not self.covers(day):
            return day.weekday() < 5
        if day in self.opened:
            return True
        if day in self.closed:
            return False
        weekend = frozenset({5, 6})
        for since, days in sorted(self.weekends):
            if since <= day:
                weekend = days
        return day.weekday() not in weekend


def _date(text: str) -> date | None:
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def days_of(answer: Any) -> Days:
    """A ReadCalendar answer as `Days`."""
    if not answer.found:
        return Days(unread="the deployment holds no TARGET calendar and could not pull it")
    read = Days(version=int(answer.version))
    for day in answer.days:
        on = _date(day.date)
        if on is None:
            continue
        if day.kind == ops.CALENDAR_DAY_KIND_CLOSED:
            read.closed.add(on)
        elif day.kind == ops.CALENDAR_DAY_KIND_OPEN:
            read.opened.add(on)
    for weekend in answer.weekends:
        since = _date(weekend.valid_from_date) or date.min
        read.weekends.append(
            (since, frozenset(_WEEKDAYS[w] for w in weekend.weekdays if w in _WEEKDAYS))
        )
    read.covered_from = _date(answer.coverage.from_date)
    read.covered_to = _date(answer.coverage.to_date)
    return read


async def read(plugin: Any, start: date, end: date, as_of_ns: int) -> Days:
    """TARGET's days from `start` to `end`, as of `as_of_ns`; a refusal said
    and answered as unread."""
    try:
        answer = await plugin.read_calendar(
            calendar_id=TARGET_CALENDAR, from_date=start, to_date=end, as_of_ns=as_of_ns
        )
    except meridian.MeridianError as refused:
        log.warning("the TARGET calendar was not read: %s", refused)
        return Days(unread=f"the deployment refused the read: {refused}")
    return days_of(answer)


def next_publication(days: Days, after: date) -> date | None:
    """The first day after `after` the ECB publishes on, within `AHEAD` days."""
    for n in range(1, AHEAD + 1):
        day = after + timedelta(days=n)
        if days.publishes_on(day):
            return day
    return None


def closed(days: Days, asked: Iterable[date]) -> list[date]:
    """The days asked the ECB publishes nothing on."""
    return [d for d in asked if not days.publishes_on(d)]
