"""The euro area yield curves into the lake, as rates (contract v27, the
rates slice; the product owner, items 128, 130 and 131, 2026-11-19): each
day's pushed when the ECB publishes them, and any past day recorded when
the lake wants it (W10.4, W10.7).

It works beside the reference rates' feed (feed.py) and €STR's
(estr_feed.py), sharing their portal, storage and `Wants`: the plugin's one
connection to the lake hears every want, and hands one of `ecb_yc` to this
feed (`Feed.answers`). The rows are built and recorded by the SDK's rates
helpers (`meridian.roles.data.rates`, ruling 345); only the ECB's part is
here.

**The rows.** Each TARGET business day, for each of the two curves
curve.py names, one `Rate` of the dataset `ecb_yc` per tenor carried and
kind:

- the spot rate a **zero** rate and the par yield a **par yield**, in per
  cent, each with its tenor (3M to 30Y), so a curve is one record and its
  points its rows (spec/a-public-rates-and-filings-data-plugin §2);
- both continuously compounded, as the ECB states them, on the SDK's
  continuous convention (`rates.CONTINUOUS`, act/365 fixed), as
  plugin-fed-board records the Board's zero curve: the ECB measures a
  curve's term in years and states no other day count for it;
- `preliminary` where the ECB marks a value provisional;
- its business date the day the curve is for, Frankfurt's day; its row key
  the SDK's, from the curve's code, the kind, the tenor, the convention, the
  day and the record, never the published time, so a revision is the same
  row's next version;
- its source time `published` where the plugin knows it: the portal's
  Last-Modified, kept only for the latest day a current read states, and
  only when it falls within five days after it -- the ECB publishes a
  day's curves at noon CET the next TARGET business day. A value read
  later -- a reader's want -- states no published time rather than a wrong
  one;
- its raw reference the answer it was first read from (raw.py).

A tenor the ECB leaves out of a day is no row, never a zero.

**Revisions.** The current range -- the last ten days -- is read at start
and every hour, `If-Modified-Since` the last answer recorded; a value the
ECB revises is recorded under the same row key, the lake keeping it as the
row's next version.

**History.** Nothing is backfilled unasked: the curves reach back to 2004,
some 34,000 rows a year, and a reader's want of a past day or range is read
from the portal and recorded against it (the dataset's `gap_recovery`
`backfill`).

**Subjects.** Each curve is resolved by its symbol at the ECB (curve.py),
as of now, once per process, by the SDK's `rates.Feed`; one the deployment
does not hold is reported missing once a day, never minted, asked again by
the SDK, and its rows wait until it resolves.

**Wants.** A want of `ecb_yc`'s rates for either curve, a business date, a
range of at most a quarter, or the latest: the days are read from TARGET's
calendar first, a day it closes or one not come yet declined
`source_silent` without a request, one before 6 September 2004
`beyond_history`; the rest are read from the portal in one request and
recorded against the want. Any other subject is declined `not_covered`, and
a want for another kind of data too.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from meridian.plugin.v1 import operations_pb2 as ops
from meridian.roles.data import rates

from . import target
from .convert import DAY_TIME_ZONE, day_bounds, frankfurt_day
from .curve import CURVES, Curve, NotCurve, Point, Points, parse
from .declared import ECB_YC, YC_FROM
from .feed import LAGS, MOST_DAYS, SOURCE, Feed, Outcome
from .portal import YC_SERIES, Fetched, PortalUnreachable, path_for
from .rates import last_modified_ns

log = logging.getLogger("ecb")

RATE = "meridian.v1.Rate"
#: Both kinds' convention: continuously compounded, as the ECB states them.
CONVENTION = rates.CONTINUOUS
#: The most days after a curve's day its published time may fall: a long
#: weekend, Good Friday to Easter Monday, and the next noon.
PUBLISHED_WITHIN = 5


def _ns(moment: datetime) -> int:
    return int(moment.timestamp() * 1_000_000) * 1000


@dataclass
class CurveRecord:
    """One curve as the plugin last saw it: the deployment's record for it,
    or why there is none, and the latest day it stated."""

    curve: Curve
    instrument_id: str = ""
    miss: str = ""
    latest_day: date | None = None


@dataclass
class CurveStatus:
    """What the curves' feed last did, for the pages; held in memory, lost
    on a restart and read again by the first check."""

    mode: str = "live"
    checked_at: datetime | None = None
    read_at: datetime | None = None
    error: str = ""
    first_day: date | None = None
    latest_day: date | None = None
    last_modified: str = ""
    records: dict[str, CurveRecord] = field(
        default_factory=lambda: {c.code: CurveRecord(c) for c in CURVES}
    )
    unread: dict[str, int] = field(default_factory=dict)
    fetches: int = 0
    not_modified: int = 0
    lags: list[int] = field(default_factory=list)
    #: The day the next curves are for, and the day they are published, by
    #: TARGET's calendar.
    next_rate_day: date | None = None
    next_release: date | None = None


class CurveFeed:
    """The yield curves' work beside the reference rates' (see the module),
    on the same portal, storage and wants as `fx`."""

    def __init__(self, fx: Feed) -> None:
        self.fx = fx
        self.rates = rates.Feed(
            fx, SOURCE, wants=fx.wants, day_zone=DAY_TIME_ZONE, clock_ns=lambda: _ns(fx.now())
        )
        self.status = CurveStatus(mode=fx.portal.mode)
        self._mode = fx.portal.mode
        self._recorded_digest = ""
        self._modified = ""
        fx.answers[ECB_YC] = self.answer

    @property
    def now(self) -> Callable[[], datetime]:
        return self.fx.now

    def today(self) -> date:
        return frankfurt_day(_ns(self.now()))

    def _follow_mode(self) -> None:
        """Sample data turned on or off (`Feed.use`): read afresh."""
        if self.fx.portal.mode != self._mode:
            self._mode = self.status.mode = self.fx.portal.mode
            self._recorded_digest = self._modified = ""

    async def read(
        self, start: date, end: date, modified_since: str = ""
    ) -> tuple[Points, Fetched, str] | None:
        """The curves' points from `start` to `end`, the answer and its key
        in storage; None where the portal says nothing changed (304).
        PortalUnreachable or NotCurve otherwise."""
        fetched = await self.fx.portal.get(path_for(start, end, YC_SERIES), modified_since)
        self.status.fetches += 1
        if fetched.status == 304:
            self.status.not_modified += 1
            return None
        key = self.fx.raw.keep(fetched)
        if fetched.status != 200:
            raise PortalUnreachable(f"{fetched.url} answered {fetched.status}")
        points = parse(fetched.text)
        for line in points.unread:
            self.status.unread[line] = self.status.unread.get(line, 0) + 1
        return points, fetched, key

    async def resolve(self) -> dict[str, str]:
        """Each curve's record, by its symbol at the ECB, resolved where not
        yet; empty for one the deployment does not hold, reported missing."""
        for record in self.status.records.values():
            if record.instrument_id:
                continue
            found = await self.rates.subject(
                *record.curve.identifiers(),
                description=record.curve.name,
                instrument_type="rate_curve",
            )
            record.instrument_id = found
            record.miss = "" if found else "not held: reported missing"
        return {code: r.instrument_id for code, r in self.status.records.items()}

    def _published(self, point: Point, points: Points, published_ns: int) -> int:
        """The answer's published time where it is this value's: the latest
        day its curve states, published within `PUBLISHED_WITHIN` days after."""
        if not published_ns or points.latest(point.curve) != point.day:
            return 0
        after = (frankfurt_day(published_ns) - point.day).days
        return published_ns if 0 < after <= PUBLISHED_WITHIN else 0

    async def record(
        self,
        points: Points,
        fetched: Fetched,
        key: str,
        *,
        want_id: str = "",
        days: Sequence[date] | None = None,
        subjects: set[str] | None = None,
        current: bool = False,
    ) -> tuple[Outcome, set[str]]:
        """Record `points` -- on `days` and for `subjects` where given -- in
        the lake's batches, against `want_id` where given; with `current`, a
        current read's, the answer's published time where it is the value's.
        What the lake answered, and the subjects a row was sent for."""
        instruments = await self.resolve()
        published = last_modified_ns(fetched.last_modified) if current else 0
        wanted = set(days) if days is not None else None
        rows: list[Any] = []
        sent: set[str] = set()
        unresolved: dict[str, None] = {}
        for point in points.points:
            if wanted is not None and point.day not in wanted:
                continue
            subject = instruments.get(point.curve.code, "")
            if not subject:
                unresolved[point.curve.code] = None
                continue
            if subjects is not None and subject not in subjects:
                continue
            name = f"{point.key}:{point.day.isoformat()}={point.stated}"
            first, noted = self.fx.raw.noted(
                name, point.day, key, self._published(point, points, published)
            )
            if noted and first.published_ns:
                lag = (first.published_ns - day_bounds(point.day)[0]) // 10**9
                self.status.lags = [*self.status.lags[-(LAGS - 1) :], lag]
            rows.append(
                self.rates.rate(
                    subject,
                    ECB_YC,
                    point.kind,
                    rates.percent(point.value.text),
                    business_date=point.day,
                    published_ns=first.published_ns,
                    convention=CONVENTION,
                    tenor=point.tenor,
                    preliminary=point.preliminary,
                    series=point.curve.code,
                    raw_key=first.key,
                )
            )
            sent.add(subject)
            record = self.status.records[point.curve.code]
            if record.latest_day is None or point.day > record.latest_day:
                record.latest_day = point.day
        self.fx.raw.save_firsts()
        counts = self.fx.wants.sent_to(ECB_YC)
        before = (counts.recorded, counts.restated, counts.unchanged)
        await self.rates.record(ECB_YC, rows, want_id)
        outcome = Outcome(
            counts.recorded - before[0],
            counts.restated - before[1],
            counts.unchanged - before[2],
            tuple(unresolved),
        )
        return outcome, sent

    async def check(self) -> Outcome | None:
        """Read the current range; record it where this process has not
        recorded it as it reads now. None where nothing was recorded."""
        self._follow_mode()
        self.status.checked_at = self.now()
        start, end = self.fx.portal.current(self.today(), YC_SERIES)
        try:
            read = await self.read(start, end, self._modified if self._recorded_digest else "")
        except (PortalUnreachable, NotCurve) as failed:
            self.status.error = str(failed)
            log.warning("the yield curves were not read: %s", failed)
            return None
        self.status.error = ""
        outcome = None
        if read is not None:
            points, fetched, key = read
            self.status.read_at = self.now()
            self.status.last_modified = fetched.last_modified
            if points.days:
                self.status.first_day, self.status.latest_day = points.days[0], points.days[-1]
            digest = digest_of(points)
            if digest != self._recorded_digest:
                outcome, _ = await self.record(points, fetched, key, current=True)
                if not outcome.unresolved:
                    self._recorded_digest, self._modified = digest, fetched.last_modified
                log.info(
                    "the yield curves of %s to %s: %d recorded, %d restated, %d unchanged%s",
                    self.status.first_day,
                    self.status.latest_day,
                    outcome.recorded,
                    outcome.restated,
                    outcome.unchanged,
                    f"; not resolved: {', '.join(outcome.unresolved)}"
                    if outcome.unresolved
                    else "",
                )
        await self.expect()
        return outcome

    async def expect(self) -> None:
        """The next curves expected, by TARGET's calendar: those of the first
        business day after the latest stated (or yesterday, before any),
        published the business day after that."""
        after = self.status.latest_day or self.today() - timedelta(days=1)
        days = await target.read(
            self.fx, after, after + timedelta(days=target.AHEAD), _ns(self.now())
        )
        day = target.next_publication(days, after)
        self.status.next_rate_day = day
        self.status.next_release = target.next_publication(days, day) if day else None

    # ── Wants ───────────────────────────────────────────────────────────

    def _days(self, want: ops.ObservationsWantedEvent) -> list[date]:
        if want.business_date:
            return [date.fromisoformat(want.business_date)]
        if want.valid_from_ns or want.valid_until_ns:
            start = frankfurt_day(want.valid_from_ns)
            end = frankfurt_day(want.valid_until_ns - 1 if want.valid_until_ns else _ns(self.now()))
            days = [start + timedelta(days=n) for n in range((end - start).days + 1)]
            return days[-MOST_DAYS:]
        return [self.status.latest_day] if self.status.latest_day else []

    async def answer(
        self,
        want: ops.ObservationsWantedEvent,
        key: str,
        subjects: list[str],
        kinds: tuple[int, ...],
    ) -> dict[str, str]:
        """One want of `ecb_yc` answered from the portal: its rates recorded
        against it, and each subject declined, with why."""
        if want.data_type not in ("", RATE):
            return {s: "not_covered" for s in subjects}
        held = {i for i in (await self.resolve()).values() if i}
        declined = {s: "not_covered" for s in subjects if s not in held}
        asked = [s for s in subjects if s in held]
        if not asked:
            return declined
        if want.standing:
            self.fx.wants.stand(want, asked, kinds)
        if not want.business_date and not want.valid_from_ns and not self.status.latest_day:
            await self.check()
        reason, sent = await self._record_days(want, self._days(want), set(asked))
        for subject in asked:
            if subject not in sent:
                declined[subject] = reason or "source_silent"
        return declined

    async def _record_days(
        self, want: ops.ObservationsWantedEvent, days: list[date], subjects: set[str]
    ) -> tuple[str, set[str]]:
        """Record the days asked for `subjects` against the want; why none
        was, and the subjects a rate was sent for."""
        today = self.today()
        if days and all(d < YC_FROM for d in days):
            return "beyond_history", set()
        asked = [d for d in days if YC_FROM <= d <= today]
        if not asked:
            return "source_silent", set()
        calendar = await target.read(self.fx, min(asked), max(asked), _ns(self.now()))
        shut = set(target.closed(calendar, asked))
        open_days = [d for d in asked if d not in shut]
        if not open_days:
            return "source_silent", set()
        try:
            read = await self.read(min(open_days), max(open_days))
        except (PortalUnreachable, NotCurve) as failed:
            log.warning("want %s: the yield curves were not read: %s", want.want_id, failed)
            return "source_silent", set()
        if read is None:
            return "source_silent", set()
        points, fetched, key = read
        _, sent = await self.record(
            points, fetched, key, want_id=want.want_id, days=open_days, subjects=subjects
        )
        return ("" if sent else "source_silent"), sent


def digest_of(points: Points) -> str:
    """What an answer states, as a short digest: its values, never the
    answer's other bytes."""
    stated = repr([(p.key, p.day, p.stated) for p in points.points]).encode()
    return hashlib.sha256(stated).hexdigest()[:16]
