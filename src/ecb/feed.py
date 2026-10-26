"""The ECB's reference rates into the lake: each day's pushed when the ECB
publishes it, and any past day recorded when the lake wants it (W10.4,
W10.7).

**Push.** The current rates -- the last ten days to today -- are read at
start and every hour. The first read after a start is recorded whole, in
batches of at most 500, and the lake answers each rate it holds unchanged,
so nothing is kept between starts but the answers in storage
(decisions/028: a plugin's process holds nothing it cannot lose). After it,
each read says `If-Modified-Since`, and an hour with nothing new is a 304
that records nothing. A rate the ECB corrects within the range is the same
row's next version.

**Subjects.** Before anything is recorded, the euro and every currency an
answer rates are resolved to the deployment's cash instruments by ISO 4217
code (W3.1), as of the moment each is asked, said; one that does not
resolve, or resolves to two records, is reported missing (W3.2) with why,
its rates left out until it does, and tried again on the next read. The
plugin mints no currency: core answers a code the deployment does not hold
with the platform master's currency, pulled through the conductor. The
euro's instrument is the subject of every rate (convert.py).

**Wants.** The lake asks for what a reader read and it does not hold
(ObservationsWanted): a business date, a range, or the latest. The plugin
covers one subject, the euro's cash instrument, and declines any other
`not_covered` (the lake never inverts a rate, and neither does the plugin).
The days asked are read from TARGET's calendar first (target.py): a day the
ECB publishes nothing on, or one not come yet, is declined `source_silent`
without a request; one before the history the catalogue declares,
`beyond_history`. The rest are read from the portal in one request, at most
a quarter, and recorded against the want. A standing want asks the subjects
kept current, which the push does; it is kept until it is withdrawn
(WantWithdrawn). The SDK's `meridian.roles.data.Wants` keeps the wants,
declines by reason, sends the batches and counts them; only the ECB's part
is here.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

import meridian
from meridian.plugin.v1 import operations_pb2 as ops
from meridian.roles import Latency, data

from . import target
from .convert import First, day_bounds, frankfurt_day, to_prices
from .declared import ECB_ESTR, ECB_FX, HISTORY
from .portal import Fetched, Portal, PortalUnreachable, path_for, utc_now
from .rates import EUR, NotRates, Rate, Rates, last_modified_ns, parse
from .raw import RawStore

log = logging.getLogger("ecb")

#: The source this plugin names on what it reports missing.
SOURCE = "ecb"
#: The most days one want is answered for: a quarter.
MOST_DAYS = 92
#: How many published-minus-valid times are kept for the Lag figure.
LAGS = 2000
PRICE = "meridian.v1.Price"

#: How a dataset's feed answers a want: what it declines, by subject.
Answer = Callable[
    [ops.ObservationsWantedEvent, str, list[str], tuple[int, ...]], Awaitable[dict[str, str]]
]


def _ns(moment: datetime) -> int:
    return int(moment.timestamp() * 1_000_000) * 1000


@dataclass
class Currency:
    """One currency as the plugin last saw it: the ECB's name for it, and
    the deployment's instrument for it, or why there is none."""

    code: str
    name: str = ""
    instrument_id: str = ""
    miss: str = ""


@dataclass(frozen=True)
class Outcome:
    recorded: int = 0
    restated: int = 0
    unchanged: int = 0
    unresolved: tuple[str, ...] = ()


@dataclass
class Status:
    """What the plugin last did, for its pages; held in memory, lost on a
    restart and read again by the first check."""

    mode: str = "live"
    started_at: datetime | None = None
    checked_at: datetime | None = None
    #: When the portal last answered with rates, and when it said nothing changed.
    read_at: datetime | None = None
    error: str = ""
    #: The current range's first and latest day with a rate, and the
    #: portal's Last-Modified for it.
    first_day: date | None = None
    latest_day: date | None = None
    last_modified: str = ""
    currencies: dict[str, Currency] = field(default_factory=dict)
    #: Lines that named a rate but held none that reads, each with how often seen.
    unread: dict[str, int] = field(default_factory=dict)
    fetches: int = 0
    not_modified: int = 0
    #: Published minus valid-from, in seconds, of each rate first read with
    #: its published time since the plugin started.
    lags: list[int] = field(default_factory=list)
    #: TARGET's calendar as last read, and the next rates expected.
    calendar: target.Days | None = None
    next_release: date | None = None


class Feed:
    """The plugin's work, on its typed operations -- `plugin` is the
    connected `meridian.Plugin`, or the suite's `Recorder` in its tests --
    reading the portal, resolving, recording, answering wants."""

    def __init__(
        self,
        plugin: Any,
        portal: Portal,
        raw: RawStore,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        self.plugin = plugin
        self.portal = portal
        self.raw = raw
        self.now = now
        # One Wants for the plugin's two datasets: their licences read
        # together, each want heard here and answered by its dataset's feed.
        self.wants = data.Wants(plugin, (ECB_FX, ECB_ESTR), clock_ns=lambda: _ns(self.now()))
        # Contract v28 (ruling 518): each row recorded unasked or for a
        # standing want has its age at the edge recorded where it states its
        # published time, reported every 10 seconds (`__main__`).
        self.latency = Latency(plugin, clock_ns=lambda: _ns(self.now()))
        self.wants.latency = self.latency
        self.status = Status(mode=portal.mode, started_at=now())
        #: The other datasets' answers to a want, by key: `ecb_estr`'s, set
        #: by its feed (estr_feed.py).
        self.answers: dict[str, Answer] = {}
        self._recorded_digest = ""
        self._modified = ""

    @property
    def dataset(self) -> str:
        return self.wants.dataset(ECB_FX)

    def today(self) -> date:
        return frankfurt_day(_ns(self.now()))

    def use(self, portal: Portal) -> None:
        """Read from `portal` from now on: sample data turned on or off."""
        if portal.mode != self.portal.mode:
            self.portal = portal
            self.status.mode = portal.mode
            self._recorded_digest = ""
            self._modified = ""

    # ── Reading the portal ──────────────────────────────────────────────

    async def read(
        self, start: date, end: date, modified_since: str = ""
    ) -> tuple[Rates, Fetched, str] | None:
        """The rates from `start` to `end`, the answer and its key in
        storage; None where the portal says nothing changed (304).
        PortalUnreachable or NotRates otherwise."""
        fetched = await self.portal.get(path_for(start, end), modified_since)
        self.status.fetches += 1
        if fetched.status == 304:
            self.status.not_modified += 1
            return None
        key = self.raw.keep(fetched)
        if fetched.status != 200:
            raise PortalUnreachable(f"{fetched.url} answered {fetched.status}")
        return parse(fetched.text), fetched, key

    # ── Resolving ───────────────────────────────────────────────────────

    async def resolve(self, wanted: Iterable[str]) -> dict[str, str]:
        """Each ISO code's cash instrument, resolved now where not yet; a
        code that does not resolve reported missing, with why."""
        for code in wanted:
            held = self.status.currencies.setdefault(code, Currency(code))
            if held.instrument_id:
                continue
            identifier = ops.Identifier(scheme="iso4217", value=code)
            # As of now, said: an as-of left out is the epoch, which no
            # identifier window the deployment keeps from a date covers.
            found = await self.plugin.resolve_identifier(
                identifiers=[identifier],
                as_of_ns=_ns(self.now()),
                stated_asset_class="cash",
                stated_currency=code,
                stated_description=f"{code} cash",
            )
            if found.found and found.instrument_id:
                held.instrument_id, held.miss = found.instrument_id, ""
                continue
            reason = found.miss_reason or ops.MISS_REASON_NOT_FOUND
            held.miss = ops.MissReason.Name(reason).removeprefix("MISS_REASON_").lower()
            await self.plugin.report_missing_instrument(
                source=SOURCE,
                asset_class="cash",
                identifiers=[identifier],
                reason=reason,
                as_of_ns=_ns(self.now()),
                observed_at_ns=_ns(self.now()),
            )
        return self.instruments()

    def instruments(self) -> dict[str, str]:
        return {c.code: c.instrument_id for c in self.status.currencies.values() if c.instrument_id}

    def euro(self) -> str:
        held = self.status.currencies.get(EUR)
        return held.instrument_id if held is not None else ""

    # ── Recording ───────────────────────────────────────────────────────

    def _note(self, rates: Rates) -> None:
        self.status.currencies.setdefault(EUR, Currency(EUR, "Euro"))
        for code in rates.currencies:
            held = self.status.currencies.setdefault(code, Currency(code))
            held.name = rates.names.get(code, held.name)
        for line in rates.unread:
            self.status.unread[line] = self.status.unread.get(line, 0) + 1

    async def record(
        self,
        rates: Rates,
        fetched: Fetched,
        key: str,
        *,
        want_id: str = "",
        days: Sequence[date] | None = None,
    ) -> Outcome:
        """Record `rates` -- on `days` where given -- in batches, against
        `want_id` where given."""
        self._note(rates)
        instruments = await self.resolve([EUR, *rates.currencies])
        published = last_modified_ns(fetched.last_modified)

        def first(rate: Rate) -> First:
            where, noted = self.raw.first(rate, key, published)
            if noted and where.published_ns:
                lag = (where.published_ns - day_bounds(rate.day)[0]) // 10**9
                self.status.lags = [*self.status.lags[-(LAGS - 1) :], lag]
            return where

        converted = to_prices(
            rates.rates,
            instruments,
            dataset=self.dataset,
            first=first,
            raw=self.plugin.raw_record,
            days=days,
        )
        self.raw.save_firsts()
        counts = self.wants.sent_to(ECB_FX)
        before = (counts.recorded, counts.restated, counts.unchanged)
        await self.wants.record("prices", list(converted.prices), ECB_FX, want_id)
        return Outcome(
            counts.recorded - before[0],
            counts.restated - before[1],
            counts.unchanged - before[2],
            converted.unresolved,
        )

    async def check(self) -> Outcome | None:
        """Read the current rates; record them where this process has not
        recorded them as they read now. None where nothing was recorded."""
        self.status.checked_at = self.now()
        start, end = self.portal.current(self.today())
        try:
            read = await self.read(start, end, self._modified if self._recorded_digest else "")
        except (PortalUnreachable, NotRates) as failed:
            self.status.error = str(failed)
            log.warning("the current rates were not read: %s", failed)
            return None
        self.status.error = ""
        if read is None:
            await self.expect()
            return None
        rates, fetched, key = read
        self.status.read_at = self.now()
        self.status.last_modified = fetched.last_modified
        if rates.days:
            self.status.first_day, self.status.latest_day = rates.days[0], rates.days[-1]
        await self.expect()
        digest = digest_of(rates)
        if digest == self._recorded_digest:
            return None
        outcome = await self.record(rates, fetched, key)
        if not outcome.unresolved:
            self._recorded_digest, self._modified = digest, fetched.last_modified
        log.info(
            "the rates of %s to %s: %d recorded, %d restated, %d unchanged%s",
            self.status.first_day,
            self.status.latest_day,
            outcome.recorded,
            outcome.restated,
            outcome.unchanged,
            f"; not resolved: {', '.join(outcome.unresolved)}" if outcome.unresolved else "",
        )
        return outcome

    async def expect(self) -> None:
        """The next rates expected, by TARGET's calendar: the first day after
        the latest stated (or yesterday, before any) the ECB publishes on."""
        after = self.status.latest_day or self.today() - timedelta(days=1)
        days = await target.read(
            self.plugin, after, after + timedelta(days=target.AHEAD), _ns(self.now())
        )
        self.status.calendar = days
        self.status.next_release = target.next_publication(days, after)

    # ── Wants ───────────────────────────────────────────────────────────

    async def on_want(self, heard: meridian.Heard[ops.ObservationsWantedEvent]) -> None:
        """Record what the lake wants of the plugin's dataset, or decline it
        (the SDK's `Wants.hear`, answered by `answer`)."""
        await self.wants.hear(heard, self.answer)

    async def on_withdrawn(self, heard: meridian.Heard[ops.WantWithdrawnEvent]) -> None:
        """A standing want withdrawn: no longer kept current."""
        self.wants.withdraw(heard.message.want_id)
        log.info("standing want %s withdrawn", heard.message.want_id)

    def _days(self, want: ops.ObservationsWantedEvent) -> list[date]:
        if want.business_date:
            return [date.fromisoformat(want.business_date)]
        if want.valid_from_ns or want.valid_until_ns:
            start = frankfurt_day(want.valid_from_ns)
            # Valid times end before `valid_until_ns`: a range to midnight
            # holds no day after it.
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
        """One want answered from the portal: its rates recorded against it,
        and each subject declined, with why. A want of another of the
        plugin's datasets is its feed's to answer."""
        other = self.answers.get(key)
        if other is not None:
            return await other(want, key, subjects, kinds)
        serves = key == ECB_FX and want.data_type in ("", PRICE)
        if not serves or (kinds and ops.PRICE_KIND_CLOSE not in kinds):
            return {s: "not_covered" for s in subjects}
        if not self.euro():
            await self.resolve([EUR])
        euro = self.euro()
        declined = {s: "not_covered" for s in subjects if s != euro}
        if euro not in subjects:
            return declined
        if want.standing:
            self.wants.stand(want, [euro], kinds)
        if not want.business_date and not want.valid_from_ns and not self.status.latest_day:
            await self.check()
        reason = await self._record_days(want, self._days(want))
        if reason:
            declined[euro] = reason
        return declined

    async def _record_days(self, want: ops.ObservationsWantedEvent, days: list[date]) -> str:
        """Record the days asked against the want; the reason the euro is
        declined, or empty where a rate was recorded."""
        today = self.today()
        oldest = today - timedelta(days=HISTORY)
        if days and all(d < oldest for d in days):
            return "beyond_history"
        asked = [d for d in days if oldest <= d <= today]
        if not asked:
            return "source_silent"
        calendar = await target.read(self.plugin, min(asked), max(asked), _ns(self.now()))
        shut = set(target.closed(calendar, asked))
        open_days = [d for d in asked if d not in shut]
        if not open_days:
            return "source_silent"
        try:
            read = await self.read(min(open_days), max(open_days))
        except (PortalUnreachable, NotRates) as failed:
            log.warning("want %s: the portal was not read: %s", want.want_id, failed)
            return "source_silent"
        if read is None:
            return "source_silent"
        rates, fetched, key = read
        done = await self.record(rates, fetched, key, want_id=want.want_id, days=open_days)
        if done.recorded + done.restated + done.unchanged == 0:
            return "source_silent"
        return ""


def digest_of(rates: Rates) -> str:
    """What an answer states, as a short digest: its rates, never the
    answer's other bytes."""
    stated = repr([(r.currency, r.day, r.text) for r in rates.rates]).encode()
    return hashlib.sha256(stated).hexdigest()[:16]
