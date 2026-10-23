"""€STR into the lake as rates: the portal's answer read, the seven records
resolved by the platform's seed, the rows the rates slice's, a revision the
row's next version, the history backfilled once, and wants recorded against
or declined -- beside the reference rates, which it leaves as they were."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from meridian.operations import as_decimal
from meridian.plugin.v1 import operations_pb2 as ops
from meridian.receive import Heard
from meridian.roles.data.testing import Lake
from meridian.suites import Recorder

from ecb.convert import day_bounds
from ecb.declared import ECB_ESTR_DATASET, ESTR_FROM
from ecb.estr import SERIES, NotEstr, parse
from ecb.estr_feed import EstrFeed
from ecb.feed import Feed
from ecb.portal import ESTR_SERIES, Fetched, PortalUnreachable, SyntheticPortal
from ecb.raw import RawStore

from conftest import (
    ESTR_AT,
    ESTR_DATASET,
    ESTR_IDS,
    ESTR_PUBLISHED_NS,
    estr_feed,
    recorder,
    target_2026,
)

ESTR = ESTR_IDS["ESTR"]
INDEX = ESTR_IDS["ESTR compounded index"]
#: The current range, 12 to 22 October: nine TARGET business days.
CURRENT_DAYS = 9
HEADER = "KEY,FREQ,BENCHMARK_ITEM,DATA_TYPE_EST,TIME_PERIOD,OBS_VALUE,OBS_STATUS,UNIT_MULT"


def recorded_estr() -> str:
    """The recorded €STR answer's SDMX-CSV, whole."""
    held = SyntheticPortal().recordings[ESTR_SERIES]
    return "\n".join([held.header, *held.rows]) + "\n"


def rows_of(plugin: Recorder) -> list[ops.Rate]:
    return [r for params in plugin.on("RecordRates") for r in params.rates]


class Revised(SyntheticPortal):
    """The ECB's portal, the current range read twice: as recorded, then
    with €STR of 22 October revised from 2.442 to 2.452 at 08:05 UTC."""

    REVISED = "Fri, 23 Oct 2026 08:05:00 GMT"

    def __init__(self, at: datetime = ESTR_AT) -> None:
        super().__init__(lambda: at)
        self.reads = 0

    async def get(self, path: str, modified_since: str = "") -> Fetched:
        got = await super().get(path)
        if not path.startswith(ESTR_SERIES):
            return got
        self.reads += 1
        if self.reads == 1:
            return got
        body = got.text.replace(
            "EST.B.EU000A2X2A25.WT,B,EU000A2X2A25,WT,2026-10-22,2.442,",
            "EST.B.EU000A2X2A25.WT,B,EU000A2X2A25,WT,2026-10-22,2.452,",
        )
        later = got.fetched_at + timedelta(minutes=5)
        return Fetched(path, 200, body.encode(), later, self.REVISED, got.date)


# ── Reading the portal's answer ─────────────────────────────────────────


def test_the_recorded_answer_reads_as_seven_records() -> None:
    read = parse(recorded_estr())
    assert not read.unread
    assert read.days[0] == date(2026, 8, 3) and read.days[-1] == date(2026, 10, 22)
    assert {f.series for f in read.fixings} == set(SERIES)
    estr = next(f for f in read.fixings if f.series.code == "ESTR" and f.day == date(2026, 10, 22))
    assert estr.value.value == Decimal("2.442") and not estr.preliminary
    # The volume in millions of euros, made euros exactly.
    assert estr.parts["TT"].value == Decimal("61438000000") and estr.parts["NT"].text == "847"
    assert (estr.parts["R25"].text, estr.parts["R75"].text) == ("2.41", "2.45")


def test_a_negative_rate_reads_and_an_empty_one_is_no_rate() -> None:
    text = "\n".join(
        [
            HEADER,
            "EST.B.EU000A2X2A25.WT,B,EU000A2X2A25,WT,2019-10-01,-0.549,A,0",
            "EST.B.EU000A2X2A25.WT,B,EU000A2X2A25,WT,2019-10-02,,A,0",
            "EST.B.EU000A2QQF16.CR,B,EU000A2QQF16,CR,2019-10-08,-0.55255,P,0",
            "EST.B.EU000A2X2A25.VL,B,EU000A2X2A25,VL,2019-10-01,54,A,0",
        ]
    )
    read = parse(text)
    assert [(f.series.code, str(f.value.value)) for f in read.fixings] == [
        ("ESTR", "-0.549"),
        ("ESTR 1-week compounded average", "-0.55255"),
    ]
    assert read.fixings[1].preliminary
    assert read.unread == ("EST.B.EU000A2X2A25.WT 2019-10-02: empty",)


def test_an_answer_that_is_not_estr_is_refused() -> None:
    assert parse("").fixings == ()
    with pytest.raises(NotEstr, match="lack"):
        parse("KEY,TIME_PERIOD\nEST.B.EU000A2X2A25.WT,2026-10-22\n")
    with pytest.raises(NotEstr, match="EST dataflow"):
        parse(f"{HEADER}\nEXR.D.USD.EUR.SP00.A,D,USD,EUR,2026-10-22,1.1,A,0\n")


# ── The current range ──────────────────────────────────────────────────


async def test_the_current_range_is_recorded_as_rates(tmp_path: Path) -> None:
    work = estr_feed(tmp_path)
    done = await work.check()
    assert done is not None and not done.unresolved
    assert done.recorded == CURRENT_DAYS * len(SERIES)
    plugin = work.plugin
    first = plugin.on("RecordRates")[0]
    assert not first.want_id
    current = [r for r in first.rates if r.meta.business_date >= "2026-10-12"]
    assert len(current) == CURRENT_DAYS * len(SERIES)
    assert {r.meta.source.dataset for r in current} == {ESTR_DATASET}
    # Each record resolved by the seed's symbol at the ECB, €STR by its ISIN too.
    asked = {
        tuple((i.scheme, i.value, i.source) for i in p.identifiers)
        for p in plugin.on("ResolveIdentifier")
    }
    assert (("symbol", "ESTR", "ecb"), ("isin", "EU000A2X2A25", "")) in asked
    assert (("symbol", "ESTR compounded index", "ecb"),) in asked
    resolved = plugin.on("ResolveIdentifier")
    assert all(p.stated_asset_class == ops.ASSET_CLASS_REFERENTIAL for p in resolved)
    index = next(p for p in resolved if p.identifiers[0].value == "ESTR compounded index")
    assert index.stated_instrument_type == ops.INSTRUMENT_TYPE_INDEX


async def test_estr_is_a_fixing_with_its_volume_and_percentiles(tmp_path: Path) -> None:
    work = estr_feed(tmp_path)
    await work.check()
    rows = rows_of(work.plugin)
    [fixing] = [
        r
        for r in rows
        if r.meta.subjects[0].entity_id == ESTR and r.meta.business_date == "2026-10-22"
    ]
    assert fixing.kind == ops.RATE_KIND_FIXING
    assert str(as_decimal(fixing.value.value)) == "2.442"
    assert fixing.value.unit == ops.VALUE_UNIT_PERCENT
    assert fixing.convention.day_count == ops.DAY_COUNT_ACT_360
    assert fixing.convention.compounding == ops.COMPOUNDING_SIMPLE
    assert str(as_decimal(fixing.volume.amount)) == "61438000000"
    assert fixing.volume.currency_code == "EUR" and fixing.transaction_count == 847
    assert [(p.percentile, str(as_decimal(p.value))) for p in fixing.percentiles] == [
        (25, "2.41"),
        (75, "2.45"),
    ]
    assert not fixing.HasField("tenor") and not fixing.preliminary
    assert (fixing.meta.valid_from_ns, fixing.meta.valid_until_ns) == day_bounds(date(2026, 10, 22))
    assert fixing.meta.row_key == "EST.B.EU000A2X2A25.WT:fixing:-:act_360:simple:2026-10-22@" + ESTR


async def test_the_averages_and_the_index(tmp_path: Path) -> None:
    work = estr_feed(tmp_path)
    await work.check()
    on_22 = {
        r.meta.subjects[0].entity_id: r
        for r in rows_of(work.plugin)
        if r.meta.business_date == "2026-10-22"
    }
    month = on_22[ESTR_IDS["ESTR 1-month compounded average"]]
    assert month.kind == ops.RATE_KIND_AVERAGE and str(as_decimal(month.value.value)) == "2.44183"
    assert month.convention.compounding == ops.COMPOUNDING_SIMPLE
    assert not month.percentiles and not month.HasField("volume")
    index = on_22[INDEX]
    assert index.kind == ops.RATE_KIND_INDEX_LEVEL
    assert index.value.unit == ops.VALUE_UNIT_INDEX
    assert index.value.index_base == "2019-10-01=100"
    assert str(as_decimal(index.value.value)) == "110.05474139"
    assert not index.HasField("convention")


async def test_only_the_latest_day_states_its_published_time(tmp_path: Path) -> None:
    work = estr_feed(tmp_path)
    await work.check()
    rows = [r for r in rows_of(work.plugin) if r.meta.business_date >= "2026-10-12"]
    published = {r.meta.business_date for r in rows if r.meta.source_times}
    assert published == {"2026-10-22"}
    latest = next(r for r in rows if r.meta.source_times)
    assert latest.meta.source_times[0].at_ns == ESTR_PUBLISHED_NS
    assert work.status.lags == [33 * 3600 + 20 * 60 + 16] * len(SERIES)


async def test_every_row_names_the_answer_kept(tmp_path: Path) -> None:
    work = estr_feed(tmp_path)
    await work.check()
    kept_keys = work.fx.raw.keys()
    current = [k for k in kept_keys if "-est-20261012-20261022" in k]
    assert len(current) == 1
    kept = work.fx.raw.read(current[0])
    assert kept is not None and kept["last_modified"] == "Fri, 23 Oct 2026 07:20:16 GMT"
    # The whole answer kept, the series not converted too.
    assert "EST.B.EU000A2X2A25.VL" in kept["body"]
    on_22 = [r for r in rows_of(work.plugin) if r.meta.business_date == "2026-10-22"]
    assert {r.meta.raw.key for r in on_22} == set(current)


async def test_unchanged_is_not_asked_again(tmp_path: Path) -> None:
    work = estr_feed(tmp_path)
    await work.check()
    sent = len(work.plugin.on("RecordRates"))
    assert await work.check() is None
    assert len(work.plugin.on("RecordRates")) == sent
    assert work.status.not_modified == 1


async def test_a_revision_is_the_same_rows_next_version(tmp_path: Path) -> None:
    lake = Lake("ecb")
    lake.answer("ReadCalendar", target_2026)
    for n, series in enumerate(SERIES):
        lake.instruments.hold(
            f"INS-ESTR{n}", ops.Identifier(scheme="symbol", value=series.code, source="ecb")
        )
    work = EstrFeed(Feed(lake, Revised(), RawStore(tmp_path), now=lambda: ESTR_AT))
    await work.check()
    work._modified = ""
    revised = await work.check()
    assert revised is not None and revised.restated == 1
    assert revised.unchanged == CURRENT_DAYS * len(SERIES) - 1
    first, again = (
        [r for r in p.rates if r.meta.business_date >= "2026-10-12"]
        for p in lake.on("RecordRates")[:1] + lake.on("RecordRates")[-1:]
    )
    assert [r.meta.row_key for r in first] == [r.meta.row_key for r in again]
    [was] = [
        r
        for r in first
        if r.meta.row_key.startswith("EST.B.EU000A2X2A25.WT")
        and r.meta.business_date == "2026-10-22"
    ]
    [now] = [r for r in again if r.meta.row_key == was.meta.row_key]
    assert str(as_decimal(now.value.value)) == "2.452"
    # Its later published time, and the answer that revised it.
    assert now.meta.source_times[0].at_ns > was.meta.source_times[0].at_ns
    assert now.meta.raw.key != was.meta.raw.key


async def test_a_record_not_held_waits_and_is_reported(tmp_path: Path) -> None:
    plugin = recorder(missing="ESTR 12-month compounded average")
    work = estr_feed(tmp_path, plugin)
    done = await work.check()
    assert done is not None and done.unresolved == ("ESTR 12-month compounded average",)
    year = ESTR_IDS["ESTR 12-month compounded average"]
    assert year not in {r.meta.subjects[0].entity_id for r in rows_of(plugin)}
    [reported] = plugin.on("ReportMissingInstrument")
    assert reported.identifiers[0].value == "ESTR 12-month compounded average"
    assert work.status.records["ESTR 12-month compounded average"].miss
    # The backfill waits for every record.
    assert work.status.backfill == "Waiting: 1 of 7 records not held"
    assert work.fx.raw.backfilled() is None


async def test_the_portal_unreachable_is_said(tmp_path: Path) -> None:
    class Down(SyntheticPortal):
        async def get(self, path: str, modified_since: str = "") -> Fetched:
            raise PortalUnreachable("https://data-api.ecb.europa.eu: ConnectionRefusedError")

    work = estr_feed(tmp_path, portal=Down(lambda: ESTR_AT))
    assert await work.check() is None
    assert "ConnectionRefusedError" in work.status.error
    assert not work.plugin.on("RecordRates")


async def test_the_next_rate_is_expected_by_targets_calendar(tmp_path: Path) -> None:
    work = estr_feed(tmp_path)
    await work.check()
    # Thursday's rate stated; Friday's is published on Monday.
    assert work.status.next_rate_day == date(2026, 10, 23)
    assert work.status.next_release == date(2026, 10, 26)


# ── The backfill ────────────────────────────────────────────────────────


async def test_the_history_is_backfilled_once_a_year_a_request(tmp_path: Path) -> None:
    work = estr_feed(tmp_path)
    await work.check()
    asked = [p for p in work.fx.portal.asked if p.startswith(ESTR_SERIES)]  # type: ignore[attr-defined]
    # The current range, then 1 October 2019 to 11 October 2026, a calendar
    # year each.
    assert asked[0].endswith("startPeriod=2026-10-12&endPeriod=2026-10-22")
    assert asked[1].endswith("startPeriod=2019-10-01&endPeriod=2019-12-31")
    assert asked[2].endswith("startPeriod=2020-01-01&endPeriod=2020-12-31")
    assert asked[-1].endswith("endPeriod=2026-10-11")
    assert len(asked) == 1 + 8
    assert work.fx.raw.backfilled() == date(2026, 10, 11)
    assert work.status.backfill == "Done through 2026-10-11"
    backfilled = [r for r in rows_of(work.plugin) if r.meta.business_date < "2026-10-12"]
    # The recording's earlier days: 3 August to 9 October, 50 business days.
    assert len({r.meta.business_date for r in backfilled}) == 50
    assert not any(r.meta.source_times for r in backfilled)
    assert all(not p.want_id for p in work.plugin.on("RecordRates"))


async def test_a_restart_does_not_backfill_again(tmp_path: Path) -> None:
    await estr_feed(tmp_path).check()
    again = estr_feed(tmp_path)
    await again.check()
    asked = [p for p in again.fx.portal.asked if p.startswith(ESTR_SERIES)]  # type: ignore[attr-defined]
    assert len(asked) == 1
    assert again.status.backfill == "Done through 2026-10-11"


async def test_a_backfill_stopped_is_tried_on_the_next_check(tmp_path: Path) -> None:
    class Flaky(SyntheticPortal):
        down = True

        async def get(self, path: str, modified_since: str = "") -> Fetched:
            if self.down and "startPeriod=2021-01-01" in path:
                raise PortalUnreachable("timed out")
            return await super().get(path, modified_since)

    portal = Flaky(lambda: ESTR_AT)
    work = estr_feed(tmp_path, portal=portal)
    await work.check()
    assert work.status.backfill == "Stopped at 2021-01-01: timed out"
    assert work.fx.raw.backfilled() is None
    portal.down = False
    await work.check()
    assert work.status.backfill == "Done through 2026-10-11"


# ── Wants ───────────────────────────────────────────────────────────────


def rate_want(
    want_id: str,
    subjects: list[str],
    *,
    day: str = "",
    standing: bool = False,
    data_type: str = "meridian.v1.Rate",
    valid_from_ns: int = 0,
    valid_until_ns: int = 0,
) -> Heard:  # type: ignore[type-arg]
    return Heard(
        row="ObservationsWanted",
        message=ops.ObservationsWantedEvent(
            want_id=want_id,
            dataset=ESTR_DATASET,
            data_type=data_type,
            subjects=[ops.SubjectRef(entity_id=s) for s in subjects],
            business_date=day,
            standing=standing,
            valid_from_ns=valid_from_ns,
            valid_until_ns=valid_until_ns,
        ),
    )


async def test_a_past_day_wanted_is_recorded_against_the_want(tmp_path: Path) -> None:
    work = estr_feed(tmp_path)
    await work.fx.on_want(rate_want("w-1", [ESTR, INDEX], day="2026-09-25"))
    [batch] = work.plugin.on("RecordRates")
    assert batch.want_id == "w-1"
    assert sorted(r.meta.subjects[0].entity_id for r in batch.rates) == sorted([ESTR, INDEX])
    assert {r.meta.business_date for r in batch.rates} == {"2026-09-25"}
    assert not any(r.meta.source_times for r in batch.rates)
    assert not work.plugin.on("DeclineWant")


async def test_a_range_wanted_is_read_in_one_request(tmp_path: Path) -> None:
    work = estr_feed(tmp_path)
    start, _ = day_bounds(date(2026, 9, 1))
    _, end = day_bounds(date(2026, 9, 30))
    await work.fx.on_want(rate_want("w-r", [ESTR], valid_from_ns=start, valid_until_ns=end))
    asked = [p for p in work.fx.portal.asked if p.startswith(ESTR_SERIES)]  # type: ignore[attr-defined]
    assert asked == [f"{ESTR_SERIES}?format=csvdata&startPeriod=2026-09-01&endPeriod=2026-09-30"]
    [batch] = work.plugin.on("RecordRates")
    assert len(batch.rates) == 22


async def test_other_subjects_and_kinds_are_not_covered(tmp_path: Path) -> None:
    work = estr_feed(tmp_path)
    await work.fx.on_want(rate_want("w-2", [ESTR, "LCL-EUR"], day="2026-09-25"))
    [declined] = work.plugin.on("DeclineWant")
    assert [s.entity_id for s in declined.subjects] == ["LCL-EUR"]
    assert declined.reason == ops.UNANSWERED_REASON_NOT_COVERED
    await work.fx.on_want(rate_want("w-3", [ESTR], day="2026-09-25", data_type="meridian.v1.Price"))
    assert work.plugin.on("DeclineWant")[-1].reason == ops.UNANSWERED_REASON_NOT_COVERED


async def test_a_closing_day_is_silent_without_a_request(tmp_path: Path) -> None:
    work = estr_feed(tmp_path)
    await work.fx.on_want(rate_want("w-4", [ESTR], day="2026-10-17"))
    [declined] = work.plugin.on("DeclineWant")
    assert declined.reason == ops.UNANSWERED_REASON_SOURCE_SILENT
    assert not [p for p in work.fx.portal.asked if p.startswith(ESTR_SERIES)]  # type: ignore[attr-defined]


async def test_before_estr_is_beyond_its_history(tmp_path: Path) -> None:
    work = estr_feed(tmp_path)
    await work.fx.on_want(rate_want("w-5", [ESTR], day="2019-09-30"))
    [declined] = work.plugin.on("DeclineWant")
    assert declined.reason == ops.UNANSWERED_REASON_BEYOND_HISTORY
    assert date(2019, 10, 1) == ESTR_FROM


async def test_a_record_that_states_nothing_that_day_is_silent(tmp_path: Path) -> None:
    # The recording holds nothing before August: the portal answers empty.
    work = estr_feed(tmp_path)
    await work.fx.on_want(rate_want("w-6", [ESTR], day="2026-07-31"))
    [declined] = work.plugin.on("DeclineWant")
    assert declined.reason == ops.UNANSWERED_REASON_SOURCE_SILENT


async def test_a_standing_want_is_kept_current(tmp_path: Path) -> None:
    work = estr_feed(tmp_path)
    await work.fx.on_want(rate_want("w-s", [ESTR], standing=True))
    assert [w.want_id for w in work.fx.wants.standing_of("ecb_estr")] == ["w-s"]
    against = [p for p in work.plugin.on("RecordRates") if p.want_id == "w-s"]
    assert against and {r.meta.business_date for r in against[0].rates} == {"2026-10-22"}


# ── Beside the reference rates ──────────────────────────────────────────


async def test_the_reference_rates_are_counted_apart(tmp_path: Path) -> None:
    work = estr_feed(tmp_path, at=datetime(2026, 10, 19, 16, 30, tzinfo=UTC))
    await work.check()
    done = await work.fx.check()
    assert done is not None and done.recorded == 203 and done.restated == 0
    assert work.fx.wants.sent_to("ecb_fx").recorded == 203
    assert work.fx.wants.sent_to("ecb_estr").recorded > 0


async def test_sample_data_turned_off_reads_afresh(tmp_path: Path) -> None:
    work = estr_feed(tmp_path)
    await work.check()
    assert work.status.mode == "synthetic"

    class Live(SyntheticPortal):
        mode = "live"

    work.fx.use(Live(lambda: ESTR_AT))
    await work.check()
    assert work.status.mode == "live"
    # Read again in full, not If-Modified-Since the sample's answer.
    assert work.status.not_modified == 0


def test_the_dataset_is_declared_as_the_spec_has_it() -> None:
    declared = ECB_ESTR_DATASET
    assert declared.key == "ecb_estr" and declared.vendor == "European Central Bank"
    assert declared.data_types[0] == "meridian.v1.Rate"
    assert declared.history == 2_600 and declared.cadence == 86_400
    assert declared.day_time_zone == "Europe/Berlin" and declared.day_end_minute == 0
    licence = declared.licence_default
    assert licence is not None and licence.kept and licence.display
    assert licence.derived_use_terms == "not_restricted" and not licence.personal_use
