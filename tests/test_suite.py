"""The data suite (meridian.suites), each case the ECB's reference rates and
€STR present mapped to the plugin's own conversion of the ECB's recorded
answers, the whole suite passing: stage 0's cases and the rates slice's as
spec/a-public-rates-and-filings-data-plugin §6 lists them.

The reference rates are one rate a day for each currency the ECB publishes
against the euro. A case about a kind of data they never state (`about`) is
not presented, with why (`NOT_PRESENTED`): a daily bar (one rate a day, no
open, high, low or volume), a stablecoin's price, prices on a venue (the
ECB's rates are no venue's), a security's price another source named,
trades and quotes; a case about a field of a trade, or a restart's gap of
trades backfilled, is about trades the same way. Contract v22's settlement
dates are not presented either: the plugin records each rate as published
and never asks for one; nor contract v23's outcomes and v26's event groups
reported, the ECB listing no event contract.

Presented beside them, as §6 says: `reads-a-calendar`, the plugin reading
TARGET's calendar (the dataset's) to know when the next rates are due and
which days asked it publishes nothing on; and `reads-its-datasets-licences`.

`the-forming-day-restated`: the ECB's day is never forming once published,
but the ECB does correct a published rate; the plugin records the corrected
rate under the same row key, which the lake keeps as the row's next version.
That is the case's outcome, and the producer gives the plugin a correction.

Contract v27's rates cases (`about: rates`), for €STR (estr_feed.py):
`a-rate-fixing`, €STR itself with its volume, percentiles and convention;
`a-same-day-revision`, the ECB revising a published €STR by 09:00, the same
row key again with its later published time; and `an-index-level`, the
compounded index. The ECB publishes no curve, so the four curve cases are
not presented, each with why. Nor are contract v27's
`records-a-datasets-liveness` (the plugin polls hourly and streams nothing)
and `queries-the-lake-within-bounds`, about trades from v27 (the plugin
records none and asks the lake nothing). From contract v28
`reports-its-feed-delay` is presented (ruling 518): the current rates read
unasked, each one's age at the edge from its published time; the chains,
filings, holdings, dividends and ratings cases are about kinds the ECB never
publishes, and the quality cases about quotes. The cases every suite holds that the SDK
answers (a replacement, the template catalogue, an event group heard) are
the SDK's.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

from meridian.plugin.v1 import operations_pb2 as ops
from meridian.roles.data.testing import feed_delay
from meridian.suites import ANSWERED_BY_SDK, Recorder, run, suite

from ecb.estr_feed import EstrFeed
from ecb.feed import Feed
from ecb.portal import Fetched, SyntheticPortal
from ecb.raw import RawStore

from conftest import AT, DATASET, ESTR_AT, ESTR_IDS, target_2026, want

#: Why each kind of data a case may be about is never published here.
NEVER = {
    "bars": "the ECB states one reference rate a day: no open, high, low or volume",
    "a crypto asset's price": "the ECB rates currencies against the euro: no token",
    "prices on a venue": "the ECB's reference rates are its own, no venue's",
    "a security's price": "the ECB rates currencies: no security another source named",
    "trades": "the ECB states one reference rate a day: no trades",
    "quotes": "the ECB states one reference rate a day: no quotes",
    "settlement dates": "records daily rates as published; never computes a settlement date",
    "outcomes": "the ECB rates currencies: no event contract, so no outcome",
    "disputed outcomes": "the ECB rates currencies: no event contract, so no outcome disputed",
    "streams": "it polls the ECB's portal hourly; it streams nothing",
    # Contract v28 (ruling 602).
    "option chains": "the ECB rates currencies and publishes €STR: no option chain",
    "filings": "the ECB publishes reference rates: no company's filings",
    "holdings": "the ECB publishes reference rates: no holdings report",
    "corporate actions": "the ECB publishes reference rates: no declared dividend",
    "ratings": "the ECB publishes reference rates: no rating",
}
#: The rates cases the ECB never presents: it publishes €STR, its averages
#: and its index, and no curve.
NO_CURVE = {
    "a-curve-for-a-date": "the ECB publishes €STR, its averages and its index: no curve",
    "a-tenor-not-published": "the ECB publishes no curve, so no tenor goes unpublished",
    "two-conventions-one-tenor": "the ECB publishes no bill: one convention a record",
    "a-curve-point-from-another-source": "the ECB publishes no curve point another source does",
}

NOT_PRESENTED = {
    **{case.name: NEVER[case.about] for case in suite("data").cases if case.about in NEVER},
    **NO_CURVE,
    # From contract v27 about trades, which the plugin never records.
    "queries-the-lake-within-bounds": "it records no trades",
}


class Revised(SyntheticPortal):
    """The ECB's portal, €STR's current range read twice: as recorded, then
    with 22 October's €STR revised at 08:05 UTC."""

    def __init__(self) -> None:
        super().__init__(lambda: ESTR_AT)
        self.reads = 0

    async def get(self, path: str, modified_since: str = "") -> Fetched:
        self.reads += 1
        got = await super().get(path)
        if self.reads == 1:
            return got
        body = got.text.replace(",WT,2026-10-22,2.442,", ",WT,2026-10-22,2.452,")
        later = got.fetched_at + timedelta(minutes=5)
        return Fetched(path, 200, body.encode(), later, "Fri, 23 Oct 2026 08:05:00 GMT", got.date)


class Corrected(SyntheticPortal):
    """The ECB's portal, the current rates read twice: as recorded, then a
    second later with the dollar's rate of 16 October corrected."""

    def __init__(self) -> None:
        super().__init__(lambda: AT)
        self.reads = 0

    async def get(self, path: str, modified_since: str = "") -> Fetched:
        self.reads += 1
        got = await super().get(path)
        if self.reads == 1:
            return got
        body = got.text.replace(",USD,EUR,SP00,A,2026-10-16,", ",USD,EUR,SP00,A,2026-10-16,9")
        later = got.fetched_at + timedelta(seconds=1)
        return Fetched(path, 200, body.encode(), later, got.last_modified, got.date)


def _resolving(recorder: Recorder, ambiguous: str = "") -> None:
    """Each ISO code resolved to `LCL-<code>`, each €STR record to its seed's;
    `ambiguous` to two records; TARGET's calendar answered."""

    def answer(params: ops.ResolveIdentifierParams) -> ops.ResolveIdentifierResult:
        code = params.identifiers[0].value
        if params.identifiers[0].source == "ecb":
            return ops.ResolveIdentifierResult(found=True, instrument_id=ESTR_IDS[code])
        if code == ambiguous:
            return ops.ResolveIdentifierResult(found=False, miss_reason=ops.MISS_REASON_AMBIGUOUS)
        return ops.ResolveIdentifierResult(found=True, instrument_id=f"LCL-{code}")

    recorder.answer("ResolveIdentifier", answer)
    recorder.answer("ReadCalendar", target_2026)


def producers(tmp: Path) -> dict[str, Callable[[Recorder], Awaitable[None]]]:
    def work(recorder: Recorder, portal: Any = None) -> Feed:
        return Feed(recorder, portal or SyntheticPortal(lambda: AT), RawStore(tmp), now=lambda: AT)

    async def the_rates_read(recorder: Recorder) -> None:
        _resolving(recorder)
        await work(recorder).check()

    async def the_rate_corrected(recorder: Recorder) -> None:
        _resolving(recorder)
        feed = work(recorder, Corrected())
        await feed.check()
        # Read again in full, as the next check after the portal changed.
        feed._modified = ""
        feed._recorded_digest = "read"
        await feed.check()
        keys = [[p.meta.row_key for p in b.prices] for b in recorder.on("RecordPrices")]
        assert len(keys) == 2 and keys[0] == keys[1]

    async def two_records(recorder: Recorder) -> None:
        _resolving(recorder, ambiguous="GBP")
        await work(recorder).check()

    def wanted(message: Any) -> Callable[[Recorder], Awaitable[None]]:
        async def produce(recorder: Recorder) -> None:
            _resolving(recorder)
            feed = work(recorder)
            recorder.answer("ObservationsWanted", lambda _: message)
            await recorder.receive(observations_wanted=feed.on_want)

        return produce

    async def licences(recorder: Recorder) -> None:
        # On start and every minute, its own declared datasets' licences.
        recorder.answer(
            "ListDatasets",
            lambda _: ops.ListDatasetsResult(licences=[ops.DatasetLicence(dataset=DATASET)]),
        )
        feed = work(recorder)
        await feed.wants.read_licences()
        assert feed.wants.licensed == {DATASET}

    async def withdrawn(recorder: Recorder) -> None:
        _resolving(recorder)
        feed = work(recorder)
        recorder.answer(
            "WantWithdrawn",
            lambda _: ops.WantWithdrawnEvent(want_id="w-standing", dataset=DATASET),
        )
        await recorder.receive(want_withdrawn=feed.on_withdrawn)

    def estr(recorder: Recorder, portal: Any = None) -> EstrFeed:
        fx = Feed(
            recorder, portal or SyntheticPortal(lambda: ESTR_AT), RawStore(tmp),
            now=lambda: ESTR_AT,
        )  # fmt: skip
        return EstrFeed(fx)

    async def estr_read(recorder: Recorder) -> None:
        _resolving(recorder)
        await estr(recorder).check()

    async def estr_revised(recorder: Recorder) -> None:
        # Read again in full, as the next hourly check after the revision.
        _resolving(recorder)
        work = estr(recorder, Revised())
        await work.check()
        work._modified = ""
        await work.check()
        current = [
            sorted(r.meta.row_key for r in p.rates if r.meta.business_date >= "2026-10-12")
            for p in recorder.on("RecordRates")
        ]
        assert current[0] == current[-1]

    async def delayed(recorder: Recorder, latency: Any) -> None:
        # Contract v28 (ruling 518): the current rates read unasked, each
        # one's age at the edge recorded from its published time, reported.
        _resolving(recorder)
        feed = work(recorder)
        feed.wants.latency = latency
        await feed.check()

    async def a_calendar_read(recorder: Recorder) -> None:
        # The next rates expected, after the current rates are read.
        _resolving(recorder)
        feed = work(recorder)
        await feed.check()
        assert feed.status.next_release is not None

    return {
        "a-daily-close": the_rates_read,
        "the-forming-day-restated": the_rate_corrected,
        "an-exact-price": the_rates_read,
        "an-fx-rate": the_rates_read,
        "an-asset-that-does-not-resolve": two_records,
        "a-want-recorded-against": wanted(want("w-1", ["LCL-EUR"], day="2026-09-25").message),
        "a-subject-declined": wanted(want("w-2", ["LCL-USD"], day="2026-10-02").message),
        "a-standing-want-withdrawn": withdrawn,
        "reads-its-datasets-licences": licences,
        "reads-a-calendar": a_calendar_read,
        "a-rate-fixing": estr_read,
        "a-same-day-revision": estr_revised,
        "an-index-level": estr_read,
        "reports-its-feed-delay": feed_delay(delayed),
    }


def test_the_data_suite_passes(tmp_path: Path) -> None:
    report = run("data", producers(tmp_path), not_presented=NOT_PRESENTED, instance_id="ecb")
    assert report.passed, report.failures
    assert sorted(report.not_presented) == sorted(NOT_PRESENTED)
    # The plugin's own fourteen -- stage 0's ten, the rates slice's three
    # and v28's feed delay -- and the cases every suite holds that the SDK answers (contract v24's
    # two, v26's event group).
    assert len(report.passed_cases) == 14 + len(ANSWERED_BY_SDK)
    assert report.answered_by_sdk == list(ANSWERED_BY_SDK)
    assert "reads-a-calendar" in report.passed_cases


def test_an_exact_price_never_passes_through_a_float(tmp_path: Path) -> None:
    import asyncio

    from meridian.operations import as_decimal

    recorder = Recorder("ecb")
    _resolving(recorder)
    feed = Feed(recorder, SyntheticPortal(lambda: AT), RawStore(tmp_path), now=lambda: AT)
    asyncio.run(feed.check())
    amounts = {
        p.meta.row_key: str(as_decimal(p.price.amount))
        for p in recorder.on("RecordPrices")[0].prices
    }
    assert amounts["USD:2026-10-19"] == "1.1225"
    assert all("e" not in a.lower() for a in amounts.values())
