"""The reference rates as the lake's prices: each rate the price of the
euro's cash instrument in the other currency, as the ECB quotes it.

The lake keeps FX as prices (spec/the-lake, its Q3): a rate is the price of
a currency's cash instrument, in another currency. The ECB quotes every
currency per euro -- USD 1.1225 is what one euro costs in dollars -- so every
rate is the price of the euro's cash instrument, in that currency. Nothing is
inverted, here or in the lake (principle 14): a reader wanting euros per
dollar inverts it itself, and says so.

Each price:

- **kind** `close`, the dataset's declared close for the business date: a
  fixing is a dataset of closes (spec/the-lake), and the reference rate is
  the day's one rate. Basis `per_unit`.
- **business_date** the rate's day, as the portal states it: a plain date.
- **valid from and until** the declared day: Frankfurt's, midnight to
  midnight (`day_time_zone` Europe/Berlin, `day_end_minute` 0).
- **row key** the currency's code and the day (`USD:2026-10-19`): the same
  rate read again is a repeat, and a rate the ECB corrects is the same row's
  next version.
- **source time** `published`, where the plugin knows it: the portal's
  Last-Modified when the rate was first read from an answer stating it on
  the rate's own day, which the hourly check of the current rates is
  (raw.py). A rate first read later -- a past day a reader wanted -- states
  no published time rather than a wrong one.
- **raw** the answer it was first read from, kept in the plugin's storage.

A rate whose currency did not resolve is not sent, and neither is any rate
while the euro's own instrument has not: the caller reports each miss.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import meridian
from meridian import Money, ObservationMeta, Price, SourceTime
from meridian.plugin.v1 import operations_pb2 as ops

from .rates import EUR, Rate

#: The day the dataset declares: Frankfurt's, ending at midnight.
DAY_TIME_ZONE = "Europe/Berlin"
DAY_END_MINUTE = 0
FRANKFURT = ZoneInfo(DAY_TIME_ZONE)


def _ns(moment: datetime) -> int:
    return int(moment.timestamp()) * 10**9


def day_bounds(day: date) -> tuple[int, int]:
    """The declared day for business date `day`: midnight to midnight,
    Frankfurt time, in nanoseconds since the epoch."""
    start = datetime.combine(day, time(0, 0), FRANKFURT)
    end = datetime.combine(day + timedelta(days=1), time(0, 0), FRANKFURT)
    return _ns(start), _ns(end)


def frankfurt_day(at_ns: int) -> date:
    """The day in Frankfurt at a moment."""
    return datetime.fromtimestamp(at_ns // 10**9, FRANKFURT).date()


def row_key(code: str, day: date) -> str:
    return f"{code}:{day.isoformat()}"


@dataclass(frozen=True)
class First:
    """Where a rate was first read: the answer's key in storage, and its
    published time, 0 where the plugin does not know it."""

    key: str
    published_ns: int = 0


@dataclass(frozen=True)
class Converted:
    """Rates as prices, and the currencies that held any back, once each."""

    prices: tuple[Price, ...]
    unresolved: tuple[str, ...]


def to_prices(
    rates: Sequence[Rate],
    instruments: Mapping[str, str],
    *,
    dataset: str,
    first: Callable[[Rate], First],
    raw: Callable[[str], ops.RawRecordRef],
    days: Sequence[date] | None = None,
) -> Converted:
    """The prices `rates` state, on `days` where given; `instruments` maps an
    ISO code to the deployment's cash instrument resolved for it, `first`
    says where each rate was first read, and `raw` names that answer."""
    euro = instruments.get(EUR, "")
    wanted = set(days) if days is not None else None
    prices: list[Price] = []
    unresolved: dict[str, None] = {} if euro else {EUR: None}
    for rate in rates:
        if wanted is not None and rate.day not in wanted:
            continue
        if not instruments.get(rate.currency):
            unresolved[rate.currency] = None
            continue
        if not euro:
            continue
        start, end = day_bounds(rate.day)
        where = first(rate)
        prices.append(
            Price(
                meta=ObservationMeta(
                    row_key=row_key(rate.currency, rate.day),
                    subjects=[meridian.SubjectRef(entity_id=euro)],
                    source=ops.Source(dataset=dataset),
                    valid_from_ns=start,
                    valid_until_ns=end,
                    business_date=rate.day,
                    source_times=(
                        [SourceTime(kind="published", at_ns=where.published_ns)]
                        if where.published_ns
                        else []
                    ),
                    raw=raw(where.key),
                ),
                kind="close",
                price=Money(rate.value, rate.currency),
                basis="per_unit",
            )
        )
    return Converted(tuple(prices), tuple(unresolved))
