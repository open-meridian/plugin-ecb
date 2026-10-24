"""The euro short-term rate into the lake, as rates (contract v27, the rates
slice): each day's pushed when the ECB publishes it, the history backfilled
once, and any past day recorded when the lake wants it (W10.4, W10.7).

It works beside the reference rates' feed (feed.py), sharing its portal, its
storage and its `Wants`: the plugin's one connection to the lake hears every
want, and hands one of `ecb_estr` to this feed (`Feed.answers`). The rows are
built and recorded by the SDK's rates helpers (`meridian.roles.data.rates`,
ruling 345); only the ECB's part is here.

**The rows.** One a day for each of the seven records estr.py names, each a
`Rate` of the dataset `ecb_estr`:

- €STR itself a **fixing**, in per cent, its convention the money market's
  (actual/360, simple), with its total volume (in euros), its number of
  transactions and its 25th and 75th percentiles;
- each compounded average an **average**, in per cent, actual/360 and
  simple: the ECB annualises each average's compounded growth over its
  period on actual/360, as a simple rate (its compounded rates methodology);
- the compounded index an **index level**, its base 1 October 2019 = 100,
  its convention €STR compounded daily on actual/360 (periods 360);
- `preliminary` where the ECB marks the value provisional;
- its business date the day the rate is for, Frankfurt's day; its row key
  the SDK's, from the ECB's series key, the kind, the convention, the day
  and the record, never the published time, so a revision is the same row's
  next version;
- its source time `published` where the plugin knows it: the portal's
  Last-Modified, kept only for the latest day a current read states, and
  only when it falls within five days after it -- the ECB publishes the next
  TARGET business day at 08:00 CET, and revises by 09:00. A value read later
  -- the backfill, a reader's want -- states no published time rather than a
  wrong one;
- its raw reference the answer it was first read from (raw.py).

**Revisions.** The current range -- the last ten days -- is read at start and
every hour, `If-Modified-Since` the last answer recorded. A value the ECB
revises reads differently; it is recorded under the same row key with the
answer that revised it and its later published time, which the lake keeps as
the row's next version, ordered by published time.

**The backfill.** On its first check where storage notes none, after the
current range is recorded, the history before it is read from 1 October
2019, a calendar year a request (some 1,800 rows each), and recorded
without a published time; storage then notes the day it went through
(raw.py), so a restart does not read it again.
Its rows wait while any of the seven records is not resolved, and it is
tried again on the next check.

**Subjects.** Each record is resolved by the identifiers the platform's seed
gives it (estr.py), as of now, once per process, by the SDK's `rates.Feed`;
one the deployment does not hold is reported missing once a day, never
minted, asked again quietly at each check, and its rows wait until it
resolves.

**Wants.** A want of `ecb_estr`'s rates for one of the seven records, a
business date, a range of at most a quarter, or the latest: the days are read
from TARGET's calendar first, a day it closes or one not come yet declined
`source_silent` without a request, one before October 2019
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

from meridian import Money
from meridian.operations import RateConvention
from meridian.plugin.v1 import operations_pb2 as ops
from meridian.roles.data import rates

from . import target
from .convert import DAY_TIME_ZONE, day_bounds, frankfurt_day
from .declared import ECB_ESTR, ESTR_FROM
from .estr import (
    COUNT,
    ESTR_ISIN,
    INDEX_BASE,
    P25,
    P75,
    SERIES,
    VOLUME,
    Fixing,
    Fixings,
    NotEstr,
    Series,
    parse,
)
from .feed import LAGS, MOST_DAYS, SOURCE, Feed, Outcome
from .portal import ESTR_SERIES, Fetched, PortalUnreachable, path_for
from .rates import last_modified_ns

log = logging.getLogger("ecb")

RATE = "meridian.v1.Rate"
#: The compounded index's convention: €STR compounded each day on
#: actual/360, as the lake records an index level (it requires one).
INDEX_CONVENTION = RateConvention(
    day_count="act_360", compounding="compounded", periods_per_year=360
)
#: The most days after a rate's day its published time may fall: a long
#: weekend, Good Friday to Easter Monday, and the next morning.
PUBLISHED_WITHIN = 5


def _ns(moment: datetime) -> int:
    return int(moment.timestamp() * 1_000_000) * 1000


@dataclass
class Record:
    """One of the seven records as the plugin last saw it: the deployment's
    instrument for it, or why there is none, and the latest day it stated."""

    series: Series
    instrument_id: str = ""
    miss: str = ""
    latest_day: date | None = None


@dataclass
class EstrStatus:
    """What the €STR feed last did, for the pages; held in memory, lost on a
    restart and read again by the first check."""

    mode: str = "live"
    checked_at: datetime | None = None
    read_at: datetime | None = None
    error: str = ""
    first_day: date | None = None
    latest_day: date | None = None
    last_modified: str = ""
    records: dict[str, Record] = field(default_factory=lambda: {s.code: Record(s) for s in SERIES})
    unread: dict[str, int] = field(default_factory=dict)
    fetches: int = 0
    not_modified: int = 0
    lags: list[int] = field(default_factory=list)
    calendar: target.Days | None = None
    #: The day the next rate is for, and the day it is published, by TARGET's
    #: calendar.
    next_rate_day: date | None = None
    next_release: date | None = None
    #: The backfill: the day it went through, or what stopped it.
    backfilled_through: date | None = None
    backfill: str = "Not started"


class EstrFeed:
    """€STR's work beside the reference rates' (see the module), on the same
    portal, storage and wants as `fx`."""

    def __init__(self, fx: Feed) -> None:
        self.fx = fx
        self.rates = rates.Feed(
            fx.plugin,
            SOURCE,
            wants=fx.wants,
            day_zone=DAY_TIME_ZONE,
            clock_ns=lambda: _ns(fx.now()),
        )
        self.status = EstrStatus(mode=fx.portal.mode)
        self._mode = fx.portal.mode
        self._recorded_digest = ""
        self._modified = ""
        fx.answers[ECB_ESTR] = self.answer

    @property
    def plugin(self) -> Any:
        return self.fx.plugin

    @property
    def now(self) -> Callable[[], datetime]:
        return self.fx.now

    @property
    def dataset(self) -> str:
        return self.fx.wants.dataset(ECB_ESTR)

    def today(self) -> date:
        return frankfurt_day(_ns(self.now()))

    def _follow_mode(self) -> None:
        """Sample data turned on or off (`Feed.use`): read afresh."""
        if self.fx.portal.mode != self._mode:
            self._mode = self.status.mode = self.fx.portal.mode
            self._recorded_digest = self._modified = ""

    # ── Reading the portal ──────────────────────────────────────────────

    async def read(
        self, start: date, end: date, modified_since: str = ""
    ) -> tuple[Fixings, Fetched, str] | None:
        """€STR's series from `start` to `end`, the answer and its key in
        storage; None where the portal says nothing changed (304).
        PortalUnreachable or NotEstr otherwise."""
        fetched = await self.fx.portal.get(path_for(start, end, ESTR_SERIES), modified_since)
        self.status.fetches += 1
        if fetched.status == 304:
            self.status.not_modified += 1
            return None
        key = self.fx.raw.keep(fetched)
        if fetched.status != 200:
            raise PortalUnreachable(f"{fetched.url} answered {fetched.status}")
        fixings = parse(fetched.text)
        for line in fixings.unread:
            self.status.unread[line] = self.status.unread.get(line, 0) + 1
        return fixings, fetched, key

    # ── Resolving ───────────────────────────────────────────────────────

    async def resolve(self) -> dict[str, str]:
        """Each record's instrument, by the seed's code, resolved where not
        yet; empty for one the deployment does not hold, reported missing."""
        for record in self.status.records.values():
            if record.instrument_id:
                continue
            series = record.series
            found = await self.rates.subject(
                *series.identifiers(),
                description=series.name,
                instrument_type=series.instrument_type,
            )
            record.instrument_id = found
            record.miss = "" if found else "not held: reported missing"
        return {code: r.instrument_id for code, r in self.status.records.items()}

    async def ask_again(self) -> None:
        """Each record not held asked again, quietly, at each check: the SDK
        reports a miss once a day and answers it from memory till then, but
        a deployment may come to hold the record sooner -- its platform
        reached, the licence list naming the ECB read (ruling 545). Found,
        it is the SDK's subject from then on; not found, nothing is reported
        twice in a day."""
        for record in self.status.records.values():
            if record.instrument_id or not record.miss:
                continue
            series = record.series
            named = tuple((s, v, o) for s, v, o in series.identifiers())
            found = await self.plugin.resolve_identifier(
                identifiers=[ops.Identifier(scheme=s, value=v, source=o) for s, v, o in named],
                as_of_ns=_ns(self.now()),
                stated_asset_class="referential",
                stated_description=series.name,
                stated_instrument_type=series.instrument_type,
            )
            if found.found and found.instrument_id:
                self.rates.subjects[named] = str(found.instrument_id)
                self.rates.missed.pop(named, None)
                record.instrument_id, record.miss = str(found.instrument_id), ""

    # ── Recording ───────────────────────────────────────────────────────

    def _row(self, fixing: Fixing, subject: str, raw_key: str, published_ns: int) -> Any:
        series = fixing.series
        if series.kind == "index_level":
            value = rates.index_level(fixing.value.text, INDEX_BASE)
            convention = INDEX_CONVENTION
        else:
            value = rates.percent(fixing.value.text)
            convention = rates.MONEY_MARKET
        extra: dict[str, Any] = {}
        if series.isin == ESTR_ISIN:
            parts = fixing.parts
            if VOLUME in parts:
                extra["volume"] = Money(parts[VOLUME].value, "EUR")
            if COUNT in parts:
                extra["transaction_count"] = int(parts[COUNT].value)
            percentiles = {n: parts[p].text for n, p in ((25, P25), (75, P75)) if p in parts}
            if percentiles:
                extra["percentiles"] = percentiles
        return self.rates.rate(
            subject,
            ECB_ESTR,
            series.kind,
            value,
            business_date=fixing.day,
            published_ns=published_ns,
            convention=convention,
            preliminary=fixing.preliminary,
            series=series.key,
            raw_key=raw_key,
            **extra,
        )

    def _published(self, fixing: Fixing, fixings: Fixings, published_ns: int) -> int:
        """The answer's published time where it is this value's: the latest
        day its series states, published within `PUBLISHED_WITHIN` days after."""
        if not published_ns or fixings.latest(fixing.series) != fixing.day:
            return 0
        after = (frankfurt_day(published_ns) - fixing.day).days
        return published_ns if 0 < after <= PUBLISHED_WITHIN else 0

    async def record(
        self,
        fixings: Fixings,
        fetched: Fetched,
        key: str,
        *,
        want_id: str = "",
        days: Sequence[date] | None = None,
        subjects: set[str] | None = None,
        current: bool = False,
    ) -> tuple[Outcome, set[str]]:
        """Record `fixings` -- on `days` and for `subjects` where given -- in
        the lake's batches, against `want_id` where given; with `current`, a
        current read's, the answer's published time where it is the value's.
        What the lake answered, and the subjects a row was sent for."""
        instruments = await self.resolve()
        published = last_modified_ns(fetched.last_modified) if current else 0
        wanted = set(days) if days is not None else None
        rows: list[Any] = []
        sent: set[str] = set()
        unresolved: dict[str, None] = {}
        for fixing in fixings.fixings:
            if wanted is not None and fixing.day not in wanted:
                continue
            subject = instruments.get(fixing.series.code, "")
            if not subject:
                unresolved[fixing.series.code] = None
                continue
            if subjects is not None and subject not in subjects:
                continue
            name = f"{fixing.series.key}:{fixing.day.isoformat()}={fixing.stated}"
            first, noted = self.fx.raw.noted(
                name, fixing.day, key, self._published(fixing, fixings, published)
            )
            if noted and first.published_ns:
                lag = (first.published_ns - day_bounds(fixing.day)[0]) // 10**9
                self.status.lags = [*self.status.lags[-(LAGS - 1) :], lag]
            rows.append(self._row(fixing, subject, first.key, first.published_ns))
            sent.add(subject)
            record = self.status.records[fixing.series.code]
            if record.latest_day is None or fixing.day > record.latest_day:
                record.latest_day = fixing.day
        self.fx.raw.save_firsts()
        counts = self.fx.wants.sent_to(ECB_ESTR)
        before = (counts.recorded, counts.restated, counts.unchanged)
        await self.rates.record(ECB_ESTR, rows, want_id)
        outcome = Outcome(
            counts.recorded - before[0],
            counts.restated - before[1],
            counts.unchanged - before[2],
            tuple(unresolved),
        )
        return outcome, sent

    async def check(self) -> Outcome | None:
        """Read the current range; record it where this process has not
        recorded it as it reads now; then backfill the history once. None
        where nothing was recorded from the current range."""
        self._follow_mode()
        self.status.checked_at = self.now()
        await self.ask_again()
        start, end = self.fx.portal.current(self.today(), ESTR_SERIES)
        try:
            read = await self.read(start, end, self._modified if self._recorded_digest else "")
        except (PortalUnreachable, NotEstr) as failed:
            self.status.error = str(failed)
            log.warning("€STR was not read: %s", failed)
            return None
        self.status.error = ""
        outcome = None
        if read is not None:
            fixings, fetched, key = read
            self.status.read_at = self.now()
            self.status.last_modified = fetched.last_modified
            if fixings.days:
                self.status.first_day, self.status.latest_day = fixings.days[0], fixings.days[-1]
            digest = digest_of(fixings)
            if digest != self._recorded_digest:
                outcome, _ = await self.record(fixings, fetched, key, current=True)
                if not outcome.unresolved:
                    self._recorded_digest, self._modified = digest, fetched.last_modified
                log.info(
                    "€STR of %s to %s: %d recorded, %d restated, %d unchanged%s",
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
        await self.backfill(start)
        return outcome

    async def backfill(self, current_start: date) -> None:
        """€STR's history before the current range, once (see the module)."""
        if self.status.backfilled_through is None:
            self.status.backfilled_through = self.fx.raw.backfilled()
        if self.status.backfilled_through is not None:
            self.status.backfill = f"Done through {self.status.backfilled_through.isoformat()}"
            return
        instruments = await self.resolve()
        waiting = sorted(code for code, held in instruments.items() if not held)
        if waiting:
            self.status.backfill = f"Waiting: {len(waiting)} of {len(SERIES)} records not held"
            return
        through = current_start - timedelta(days=1)
        cursor = ESTR_FROM
        recorded = 0
        while cursor <= through:
            stop = min(date(cursor.year, 12, 31), through)
            self.status.backfill = f"Reading {cursor.isoformat()} to {stop.isoformat()}"
            try:
                read = await self.read(cursor, stop)
            except (PortalUnreachable, NotEstr) as failed:
                self.status.backfill = f"Stopped at {cursor.isoformat()}: {failed}"
                log.warning("€STR's history stopped at %s: %s", cursor, failed)
                return
            if read is not None:
                fixings, fetched, key = read
                done, _ = await self.record(fixings, fetched, key)
                recorded += done.recorded + done.restated + done.unchanged
            cursor = stop + timedelta(days=1)
        self.fx.raw.backfill_done(through)
        self.status.backfilled_through = through
        self.status.backfill = f"Done through {through.isoformat()}"
        log.info("€STR's history from %s to %s: %d rates sent", ESTR_FROM, through, recorded)

    async def expect(self) -> None:
        """The next rate expected, by TARGET's calendar: the rate of the first
        business day after the latest stated (or yesterday, before any),
        published the business day after that."""
        after = self.status.latest_day or self.today() - timedelta(days=1)
        days = await target.read(
            self.plugin, after, after + timedelta(days=target.AHEAD), _ns(self.now())
        )
        self.status.calendar = days
        rate_day = target.next_publication(days, after)
        self.status.next_rate_day = rate_day
        self.status.next_release = (
            target.next_publication(days, rate_day) if rate_day is not None else None
        )

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
        """One want of `ecb_estr` answered from the portal: its rates recorded
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
        if days and all(d < ESTR_FROM for d in days):
            return "beyond_history", set()
        asked = [d for d in days if ESTR_FROM <= d <= today]
        if not asked:
            return "source_silent", set()
        calendar = await target.read(self.plugin, min(asked), max(asked), _ns(self.now()))
        shut = set(target.closed(calendar, asked))
        open_days = [d for d in asked if d not in shut]
        if not open_days:
            return "source_silent", set()
        try:
            read = await self.read(min(open_days), max(open_days))
        except (PortalUnreachable, NotEstr) as failed:
            log.warning("want %s: €STR was not read: %s", want.want_id, failed)
            return "source_silent", set()
        if read is None:
            return "source_silent", set()
        fixings, fetched, key = read
        _, sent = await self.record(
            fixings, fetched, key, want_id=want.want_id, days=open_days, subjects=subjects
        )
        return ("" if sent else "source_silent"), sent


def digest_of(fixings: Fixings) -> str:
    """What an answer states, as a short digest: its values, never the
    answer's other bytes."""
    stated = repr([(f.series.key, f.day, f.stated) for f in fixings.fixings]).encode()
    return hashlib.sha256(stated).hexdigest()[:16]
