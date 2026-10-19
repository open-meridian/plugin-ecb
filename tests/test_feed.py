"""The plugin's work on its typed operations: the current rates pushed,
subjects resolved or reported, wants recorded against or declined."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from meridian.operations import as_decimal
from meridian.plugin.v1 import operations_pb2 as ops
from meridian.receive import Heard
from meridian.suites import Recorder

from ecb.convert import day_bounds
from ecb.portal import Fetched, PortalUnreachable, SyntheticPortal

from conftest import AT, CODES, PUBLISHED_NS, feed, recorder, want

EURO = "LCL-EUR"
#: The current range's days with a rate: 9 October, then 12 to 16 and 19.
CURRENT_DAYS = 7


class Corrected(SyntheticPortal):
    """The recording, read twice in full: the second time with the dollar's
    rate of 16 October corrected."""

    def __init__(self) -> None:
        super().__init__(lambda: AT)
        self.reads = 0

    async def get(self, path: str, modified_since: str = "") -> Fetched:
        self.reads += 1
        got = await super().get(path)
        if self.reads > 1:
            # Read a second later, so kept under a key of its own.
            later = got.fetched_at + timedelta(seconds=1)
            body = got.text.replace(",USD,EUR,SP00,A,2026-10-16,", ",USD,EUR,SP00,A,2026-10-16,9")
            return Fetched(path, 200, body.encode(), later, got.last_modified, got.date)
        return got


async def test_the_current_rates_pushed_whole(tmp_path: Path) -> None:
    work = feed(tmp_path)
    done = await work.check()
    assert done is not None and done.recorded == CURRENT_DAYS * len(CODES) == 203
    plugin = work.plugin
    assert isinstance(plugin, Recorder)
    [batch] = plugin.on("RecordPrices")
    assert not batch.want_id
    assert len(plugin.on("ResolveIdentifier")) == len(CODES) + 1
    # Every rate is the price of the euro, in the other currency, as quoted.
    assert {p.meta.subjects[0].entity_id for p in batch.prices} == {EURO}
    usd = next(p for p in batch.prices if p.meta.row_key == "USD:2026-10-19")
    assert str(as_decimal(usd.price.amount)) == "1.1225" and usd.price.currency_code == "USD"
    assert usd.kind == ops.PRICE_KIND_CLOSE and usd.meta.business_date == "2026-10-19"
    assert (usd.meta.valid_from_ns, usd.meta.valid_until_ns) == day_bounds(date(2026, 10, 19))
    # The answer kept first, and every row names it.
    [key] = work.raw.keys()
    assert {p.meta.raw.key for p in batch.prices} == {key}
    assert work.status.latest_day == date(2026, 10, 19)


async def test_only_a_rate_read_on_its_day_states_its_published_time(tmp_path: Path) -> None:
    work = feed(tmp_path)
    await work.check()
    prices = work.plugin.on("RecordPrices")[0].prices
    published = {p.meta.row_key: [t.at_ns for t in p.meta.source_times] for p in prices}
    assert all(published[f"{c}:2026-10-19"] == [PUBLISHED_NS] for c in CODES)
    assert all(not published[f"{c}:2026-10-16"] for c in CODES)
    # 13:56:57 UTC is 15:56:57 in Frankfurt: the rate's lag from its day's start.
    assert set(work.status.lags) == {15 * 3600 + 56 * 60 + 57}


async def test_rates_unchanged_are_not_asked_again(tmp_path: Path) -> None:
    work = feed(tmp_path)
    await work.check()
    assert await work.check() is None
    assert len(work.plugin.on("RecordPrices")) == 1
    assert work.status.not_modified == 1 and len(work.raw.keys()) == 1


async def test_a_restart_names_the_answer_first_read(tmp_path: Path) -> None:
    first = feed(tmp_path)
    await first.check()
    again = feed(tmp_path, recorder(), at=AT + timedelta(hours=1))
    await again.check()
    batches = [w.plugin.on("RecordPrices")[0].prices for w in (first, again)]
    named = [
        {p.meta.row_key: (p.meta.raw.key, list(p.meta.source_times)) for p in b} for b in batches
    ]
    assert named[0] == named[1]
    assert len(again.raw.keys()) == 2


async def test_a_corrected_rate_is_the_same_rows_next_version(tmp_path: Path) -> None:
    work = feed(tmp_path, portal=Corrected())
    await work.check()
    work._modified = ""  # read in full again, as after a change
    work._recorded_digest = "x"
    await work.check()
    first, second = (b.prices for b in work.plugin.on("RecordPrices"))
    assert [p.meta.row_key for p in first] == [p.meta.row_key for p in second]
    changed = [
        (a.meta.row_key, a.meta.raw.key != b.meta.raw.key)
        for a, b in zip(first, second, strict=True)
        if a.price != b.price
    ]
    assert changed == [("USD:2026-10-16", True)]


async def test_a_currency_that_resolves_to_two_records_is_reported(tmp_path: Path) -> None:
    plugin = recorder(ambiguous="GBP")
    work = feed(tmp_path, plugin)
    done = await work.check()
    assert done is not None and done.unresolved == ("GBP",)
    [missed] = plugin.on("ReportMissingInstrument")
    assert missed.reason == ops.MISS_REASON_AMBIGUOUS and missed.source == "ecb"
    assert missed.identifiers[0].scheme == "iso4217" and missed.identifiers[0].value == "GBP"
    assert work.status.currencies["GBP"].miss == "ambiguous"
    prices = plugin.on("RecordPrices")[0].prices
    assert len(prices) == 196 and not any(p.meta.row_key.startswith("GBP") for p in prices)
    # Not marked recorded: the next check reads in full and tries again.
    assert await work.check() is not None


async def test_no_rate_goes_while_the_euro_does_not_resolve(tmp_path: Path) -> None:
    plugin = recorder(missing="EUR")
    work = feed(tmp_path, plugin)
    done = await work.check()
    assert done is not None and done.unresolved == ("EUR",) and done.recorded == 0
    assert not plugin.on("RecordPrices")
    assert work.status.currencies["EUR"].miss == "not_found"


async def test_a_past_day_wanted_is_recorded_against_the_want(tmp_path: Path) -> None:
    work = feed(tmp_path)
    await work.check()
    await work.on_want(want("w-1", [EURO], day="2026-09-25"))
    batch = work.plugin.on("RecordPrices")[-1]
    assert batch.want_id == "w-1" and len(batch.prices) == len(CODES)
    assert {p.meta.business_date for p in batch.prices} == {"2026-09-25"}
    assert {p.meta.subjects[0].entity_id for p in batch.prices} == {EURO}
    # Read later than its day: no published time is stated for it.
    assert not any(p.meta.source_times for p in batch.prices)
    [heard] = work.wants.heard
    assert heard.recorded == len(CODES) and heard.declined == 0


async def test_a_range_wanted_is_read_in_one_request(tmp_path: Path) -> None:
    work = feed(tmp_path)
    start, _ = day_bounds(date(2026, 9, 14))
    _, end = day_bounds(date(2026, 9, 20))
    portal = work.portal
    assert isinstance(portal, SyntheticPortal)
    await work.on_want(want("w-r", [EURO], valid_from_ns=start, valid_until_ns=end))
    batch = work.plugin.on("RecordPrices")[-1]
    assert {p.meta.business_date for p in batch.prices} == {f"2026-09-{d}" for d in range(14, 19)}
    assert portal.asked[-1].endswith("startPeriod=2026-09-14&endPeriod=2026-09-18")


async def test_another_currency_is_declined_not_covered(tmp_path: Path) -> None:
    work = feed(tmp_path)
    await work.check()
    await work.on_want(want("w-2", ["LCL-CHF", EURO, "LCL-elsewhere"], day="2026-10-02"))
    [declined] = work.plugin.on("DeclineWant")
    assert declined.reason == ops.UNANSWERED_REASON_NOT_COVERED
    assert [s.entity_id for s in declined.subjects] == ["LCL-CHF", "LCL-elsewhere"]
    batch = work.plugin.on("RecordPrices")[-1]
    assert batch.want_id == "w-2" and len(batch.prices) == len(CODES)


async def test_a_target_closing_day_is_declined_without_a_request(tmp_path: Path) -> None:
    work = feed(tmp_path)
    portal = work.portal
    assert isinstance(portal, SyntheticPortal)
    await work.on_want(want("w-3", [EURO], day="2026-10-17"))
    [declined] = work.plugin.on("DeclineWant")
    assert declined.reason == ops.UNANSWERED_REASON_SOURCE_SILENT
    assert portal.asked == []
    [read] = work.plugin.on("ReadCalendar")
    assert (read.from_date, read.to_date) == ("2026-10-17", "2026-10-17")


async def test_a_day_the_portal_states_nothing_for_is_declined_silent(tmp_path: Path) -> None:
    work = feed(tmp_path)
    # Friday 31 July 2026, before the recording: the portal answers no rate.
    await work.on_want(want("w-4", [EURO], day="2026-07-31"))
    [declined] = work.plugin.on("DeclineWant")
    assert declined.reason == ops.UNANSWERED_REASON_SOURCE_SILENT
    # A day not come yet is silent too.
    await work.on_want(want("w-5", [EURO], day="2026-10-21"))
    assert work.plugin.on("DeclineWant")[-1].reason == ops.UNANSWERED_REASON_SOURCE_SILENT


async def test_a_day_past_the_history_is_declined(tmp_path: Path) -> None:
    work = feed(tmp_path)
    await work.on_want(want("w-6", [EURO], day="1990-01-02"))
    [declined] = work.plugin.on("DeclineWant")
    assert declined.reason == ops.UNANSWERED_REASON_BEYOND_HISTORY


async def test_a_kind_or_a_type_not_served_is_declined(tmp_path: Path) -> None:
    work = feed(tmp_path)
    await work.on_want(want("w-7", [EURO], day="2026-10-02", kinds=(ops.PRICE_KIND_NAV,)))
    await work.on_want(want("w-8", [EURO], day="2026-10-02", data_type="meridian.v1.Bar"))
    await work.on_want(want("w-9", [EURO], day="2026-10-02", dataset="other:daily"))
    reasons = [d.reason for d in work.plugin.on("DeclineWant")]
    assert reasons == [ops.UNANSWERED_REASON_NOT_COVERED] * 3
    assert not work.plugin.on("RecordPrices")


async def test_the_latest_wanted_is_the_latest_day_published(tmp_path: Path) -> None:
    work = feed(tmp_path)
    await work.on_want(want("w-l", [EURO]))
    batch = work.plugin.on("RecordPrices")[-1]
    assert batch.want_id == "w-l"
    assert {p.meta.business_date for p in batch.prices} == {"2026-10-19"}


async def test_a_standing_want_is_kept_until_withdrawn(tmp_path: Path) -> None:
    work = feed(tmp_path)
    await work.check()
    await work.on_want(want("w-s", [EURO], standing=True))
    assert "w-s" in work.wants.standing
    await work.on_withdrawn(
        Heard(
            row="WantWithdrawn",
            message=ops.WantWithdrawnEvent(want_id="w-s", dataset="ecb:ecb_fx"),
        )
    )
    assert "w-s" not in work.wants.standing


async def test_the_portal_unreachable_is_said(tmp_path: Path) -> None:
    class Offline(SyntheticPortal):
        mode = "live"

        async def get(self, path: str, modified_since: str = "") -> Fetched:
            raise PortalUnreachable(f"https://data-api.ecb.europa.eu{path}: ConnectionRefusedError")

    work = feed(tmp_path, portal=Offline())
    assert await work.check() is None
    assert "ConnectionRefusedError" in work.status.error
    assert not work.plugin.on("RecordPrices")


async def test_the_next_rates_are_expected_by_targets_calendar(tmp_path: Path) -> None:
    work = feed(tmp_path)
    await work.check()
    assert work.status.next_release == date(2026, 10, 20)
    assert work.status.calendar is not None and work.status.calendar.version == 1


async def test_a_calendar_not_held_assumes_monday_to_friday(tmp_path: Path) -> None:
    plugin = Recorder("ecb")
    plugin.answer(
        "ResolveIdentifier",
        lambda p: ops.ResolveIdentifierResult(
            found=True, instrument_id=f"LCL-{p.identifiers[0].value}"
        ),
    )
    work = feed(tmp_path, plugin, at=datetime(2026, 10, 16, 16, 0, tzinfo=UTC))
    await work.check()
    assert work.status.calendar is not None and work.status.calendar.unread
    # The recording's current range ends on Monday 19 October; Tuesday is next.
    assert work.status.next_release == date(2026, 10, 20)


async def test_each_currency_is_resolved_as_of_now(tmp_path: Path) -> None:
    plugin = recorder()
    asked: list[int] = []

    def resolved(params: ops.ResolveIdentifierParams) -> ops.ResolveIdentifierResult:
        asked.append(params.as_of_ns)
        (identifier,) = params.identifiers
        assert identifier.scheme == "iso4217" and params.stated_asset_class == ops.ASSET_CLASS_CASH
        return ops.ResolveIdentifierResult(found=True, instrument_id=f"INS-{identifier.value}")

    plugin.answer("ResolveIdentifier", resolved)
    await feed(tmp_path, plugin).check()
    assert asked and set(asked) == {int(AT.timestamp() * 1_000_000_000)}
    rows = {sent.row for sent in plugin.sent}
    assert rows <= {"ResolveIdentifier", "RecordPrices", "ReadCalendar"}, rows
