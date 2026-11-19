"""The euro area yield curves into the lake as rates (`ecb_yc`): the portal's
`YC` answer read, the two curves resolved by their records, each curve's
spot rates recorded as zero rates and its par yields as par yields at each
tenor carried, continuously compounded as the ECB states them; forwards and
the Svensson parameters never read; a tenor the ECB leaves out no row; and
wants recorded against or declined -- beside the reference rates and €STR,
which it leaves as they were."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from meridian.operations import as_decimal
from meridian.plugin.v1 import operations_pb2 as ops
from meridian.receive import Heard
from meridian.suites import Recorder

from ecb.curve import CURVES, TENORS, NotCurve, parse
from ecb.declaration import DECLARATION
from ecb.declared import ECB_YC, ECB_YC_DATASET, TARGET_CALENDAR, YC_FROM
from ecb.portal import YC_SERIES, Fetched, SyntheticPortal

from conftest import (
    CURVE_AT,
    CURVE_DATASET,
    CURVE_IDS,
    CURVE_PUBLISHED_NS,
    curve_feed,
    lake_of,
    recorder,
)

AAA_CODE, ALL_CODE = (c.code for c in CURVES)
AAA, ALL = CURVE_IDS[AAA_CODE], CURVE_IDS[ALL_CODE]
#: The current range, 7 to 17 November: seven TARGET business days.
CURRENT_DAYS = 7
#: Each day, each curve: a spot rate and a par yield at each tenor carried.
A_DAY = len(CURVES) * 2 * len(TENORS)
HEADER = (
    "KEY,FREQ,REF_AREA,CURRENCY,PROVIDER_FM,INSTRUMENT_FM,PROVIDER_FM_ID,DATA_TYPE_FM,"
    "TIME_PERIOD,OBS_VALUE,OBS_STATUS"
)


def recorded_yc() -> str:
    """The recorded yield curves' SDMX-CSV, whole."""
    held = SyntheticPortal().recordings[YC_SERIES]
    return "\n".join([held.header, *held.rows]) + "\n"


def line(instrument: str, data_type: str, day: str, value: str, status: str = "A") -> str:
    key = f"YC.B.U2.EUR.4F.{instrument}.SV_C_YM.{data_type}"
    return f"{key},B,U2,EUR,4F,{instrument},SV_C_YM,{data_type},{day},{value},{status}"


def rows_of(plugin: Recorder) -> list[ops.Rate]:
    return [r for params in plugin.on("RecordRates") for r in params.rates]


def rate_want(
    want_id: str, subjects: list[str], *, day: str = "", data_type: str = "meridian.v1.Rate"
) -> Heard:  # type: ignore[type-arg]
    return Heard(
        row="ObservationsWanted",
        message=ops.ObservationsWantedEvent(
            want_id=want_id,
            dataset=CURVE_DATASET,
            data_type=data_type,
            subjects=[ops.SubjectRef(entity_id=s) for s in subjects],
            business_date=day,
        ),
    )


# ── Reading the portal's answer ─────────────────────────────────────────


def test_the_recorded_answer_reads_as_two_curves_spot_and_par() -> None:
    read = parse(recorded_yc())
    assert not read.unread
    assert read.days[0] == date(2026, 8, 3) and read.days[-1] == date(2026, 11, 17)
    assert len(read.points) == len(read.days) * A_DAY
    assert {p.curve for p in read.points} == set(CURVES)
    assert {p.kind for p in read.points} == {"zero", "par_yield"}
    par = next(
        p
        for p in read.points
        if p.curve.code == AAA_CODE
        and p.kind == "par_yield"
        and p.tenor == "10Y"
        and p.day == date(2026, 11, 17)
    )
    assert par.value.value == Decimal("3.3958170191") and not par.preliminary


def test_forwards_parameters_and_tenors_not_carried_are_not_read() -> None:
    text = "\n".join(
        [
            HEADER,
            line("G_N_A", "SR_10Y", "2026-11-17", "3.4245648137"),
            line("G_N_A", "IF_10Y", "2026-11-17", "3.9"),
            line("G_N_A", "BETA0", "2026-11-17", "1.63"),
            line("G_N_A", "TAU1", "2026-11-17", "2.1"),
            line("G_N_A", "SRS_10Y_1Y", "2026-11-17", "1.1"),
            line("G_N_A", "SR_10Y1M", "2026-11-17", "3.43"),
            line("G_N_C", "PY_2Y", "2026-11-17", "-0.512", "P"),
            line("G_N_C", "PY_5Y", "2026-11-17", ""),
        ]
    )
    read = parse(text)
    assert [(p.curve.code, p.kind, p.tenor, p.value.text) for p in read.points] == [
        (AAA_CODE, "zero", "10Y", "3.4245648137"),
        (ALL_CODE, "par_yield", "2Y", "-0.512"),
    ]
    assert read.points[1].preliminary
    assert read.unread == ("YC.B.U2.EUR.4F.G_N_C.SV_C_YM.PY_5Y 2026-11-17: empty",)


def test_an_answer_that_is_not_the_curves_is_refused() -> None:
    assert parse("").points == ()
    with pytest.raises(NotCurve, match="lack"):
        parse("KEY,TIME_PERIOD\nYC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y,2026-11-17\n")
    with pytest.raises(NotCurve, match="YC dataflow"):
        parse(f"{HEADER}\nEST.B.EU000A2X2A25.WT,B,U2,EUR,4F,x,y,WT,2026-11-17,2.4,A\n")


# ── Recording ───────────────────────────────────────────────────────────


async def test_the_current_range_is_recorded_as_zero_rates_and_par_yields(
    tmp_path: Path,
) -> None:
    work = curve_feed(tmp_path)
    done = await work.check()
    assert done is not None and not done.unresolved
    assert done.recorded == CURRENT_DAYS * A_DAY
    plugin = lake_of(work)
    sent = rows_of(plugin)
    assert len(sent) == CURRENT_DAYS * A_DAY
    assert {r.meta.source.dataset for r in sent} == {CURVE_DATASET}
    assert {r.meta.subjects[0].entity_id for r in sent} == {AAA, ALL}
    assert {r.kind for r in sent} == {ops.RATE_KIND_ZERO, ops.RATE_KIND_PAR_YIELD}
    # Continuously compounded, as the ECB states both its spot rates and its
    # par yields; the SDK's continuous convention, act/365 fixed.
    assert {(r.convention.day_count, r.convention.compounding) for r in sent} == {
        (ops.DAY_COUNT_ACT_365_FIXED, ops.COMPOUNDING_CONTINUOUS)
    }
    assert all(r.tenor.unit and r.tenor.count for r in sent)
    # Each curve resolved by its symbol at the ECB, a referential rate curve.
    resolved = plugin.on("ResolveIdentifier")
    asked = {tuple((i.scheme, i.value, i.source) for i in p.identifiers) for p in resolved}
    assert asked == {(("symbol", AAA_CODE, "ecb"),), (("symbol", ALL_CODE, "ecb"),)}
    assert all(p.stated_asset_class == ops.ASSET_CLASS_REFERENTIAL for p in resolved)
    assert all(p.stated_instrument_type == ops.INSTRUMENT_TYPE_RATE_CURVE for p in resolved)


async def test_a_point_is_its_curves_row_at_its_tenor(tmp_path: Path) -> None:
    work = curve_feed(tmp_path)
    await work.check()
    sent = rows_of(lake_of(work))

    def point(subject: str, kind: int, count: int, unit: int, day: str) -> ops.Rate:
        [held] = [
            r
            for r in sent
            if r.meta.subjects[0].entity_id == subject
            and r.kind == kind
            and (r.tenor.count, r.tenor.unit) == (count, unit)
            and r.meta.business_date == day
        ]
        return held

    par = point(AAA, ops.RATE_KIND_PAR_YIELD, 10, ops.TENOR_UNIT_YEAR, "2026-11-17")
    assert (
        str(as_decimal(par.value.value)) == "3.3958170191"
        and par.value.unit == ops.VALUE_UNIT_PERCENT
    )
    # The latest day states the portal's Last-Modified as its published time.
    assert par.meta.source_times[0].at_ns == CURVE_PUBLISHED_NS
    spot = point(ALL, ops.RATE_KIND_ZERO, 3, ops.TENOR_UNIT_MONTH, "2026-11-16")
    assert not spot.meta.source_times, "an earlier day's published time is not known"
    assert spot.meta.raw.key and not spot.preliminary
    assert (
        par.meta.row_key
        != point(AAA, ops.RATE_KIND_ZERO, 10, ops.TENOR_UNIT_YEAR, "2026-11-17").meta.row_key
    )


async def test_unchanged_is_not_asked_again(tmp_path: Path) -> None:
    work = curve_feed(tmp_path)
    await work.check()
    before = len(lake_of(work).on("RecordRates"))
    assert await work.check() is None
    assert work.status.not_modified == 1
    assert len(lake_of(work).on("RecordRates")) == before


async def test_a_curve_not_held_waits_and_is_reported(tmp_path: Path) -> None:
    plugin = recorder(missing=ALL_CODE)
    work = curve_feed(tmp_path, plugin)
    done = await work.check()
    assert done is not None and done.unresolved == (ALL_CODE,)
    assert {r.meta.subjects[0].entity_id for r in rows_of(plugin)} == {AAA}
    [reported] = plugin.on("ReportMissingInstrument")
    assert reported.identifiers[0].value == ALL_CODE
    assert work.status.records[ALL_CODE].miss


async def test_a_tenor_not_published_is_no_row(tmp_path: Path) -> None:
    class Gap(SyntheticPortal):
        async def get(self, path: str, modified_since: str = "") -> Fetched:
            got = await super().get(path, modified_since)
            kept = [
                row
                for row in got.text.splitlines()
                if not row.startswith("YC.B.U2.EUR.4F.G_N_A.SV_C_YM.PY_7Y,")
                or ",2026-11-17," not in row
            ]
            return Fetched(
                path,
                got.status,
                "\n".join(kept).encode(),
                got.fetched_at,
                got.last_modified,
                got.date,
            )

    work = curve_feed(tmp_path, portal=Gap(lambda: CURVE_AT))
    await work.check()
    on_17th = [
        r
        for r in rows_of(lake_of(work))
        if r.meta.business_date == "2026-11-17"
        and r.meta.subjects[0].entity_id == AAA
        and r.kind == ops.RATE_KIND_PAR_YIELD
    ]
    assert len(on_17th) == len(TENORS) - 1
    assert (7, ops.TENOR_UNIT_YEAR) not in {(r.tenor.count, r.tenor.unit) for r in on_17th}


async def test_the_next_curves_are_expected_by_targets_calendar(tmp_path: Path) -> None:
    work = curve_feed(tmp_path)
    await work.check()
    # Tuesday's curves stated; Wednesday's are published on Thursday.
    assert work.status.next_rate_day == date(2026, 11, 18)
    assert work.status.next_release == date(2026, 11, 19)


# ── Wants ───────────────────────────────────────────────────────────────


async def test_a_past_day_wanted_is_recorded_against_the_want(tmp_path: Path) -> None:
    work = curve_feed(tmp_path)
    await work.fx.on_observations_wanted(rate_want("w-1", [AAA], day="2026-09-25"))
    [batch] = lake_of(work).on("RecordRates")
    assert batch.want_id == "w-1"
    assert len(batch.rates) == 2 * len(TENORS)
    assert {r.meta.subjects[0].entity_id for r in batch.rates} == {AAA}
    assert {r.meta.business_date for r in batch.rates} == {"2026-09-25"}
    assert not any(r.meta.source_times for r in batch.rates)
    assert not lake_of(work).on("DeclineWant")


async def test_other_subjects_and_kinds_are_not_covered(tmp_path: Path) -> None:
    work = curve_feed(tmp_path)
    await work.fx.on_observations_wanted(rate_want("w-2", [AAA, "LCL-EUR"], day="2026-09-25"))
    [declined] = lake_of(work).on("DeclineWant")
    assert [s.entity_id for s in declined.subjects] == ["LCL-EUR"]
    assert declined.reason == ops.UNANSWERED_REASON_NOT_COVERED
    await work.fx.on_observations_wanted(
        rate_want("w-3", [AAA], day="2026-09-25", data_type="meridian.v1.Price")
    )
    assert lake_of(work).on("DeclineWant")[-1].reason == ops.UNANSWERED_REASON_NOT_COVERED


async def test_a_closing_day_is_silent_without_a_request(tmp_path: Path) -> None:
    work = curve_feed(tmp_path)
    await work.fx.on_observations_wanted(rate_want("w-4", [AAA], day="2026-11-14"))
    [declined] = lake_of(work).on("DeclineWant")
    assert declined.reason == ops.UNANSWERED_REASON_SOURCE_SILENT
    assert not [p for p in work.fx.portal.asked if p.startswith(YC_SERIES)]  # type: ignore[attr-defined]


async def test_before_the_curves_is_beyond_their_history(tmp_path: Path) -> None:
    work = curve_feed(tmp_path)
    await work.fx.on_observations_wanted(rate_want("w-5", [AAA], day="2004-09-03"))
    [declined] = lake_of(work).on("DeclineWant")
    assert declined.reason == ops.UNANSWERED_REASON_BEYOND_HISTORY
    assert date(2004, 9, 6) == YC_FROM


# ── The catalogue ───────────────────────────────────────────────────────


def test_the_dataset_is_declared_with_the_ecbs_terms() -> None:
    held = ECB_YC_DATASET
    assert held.key == ECB_YC == "ecb_yc"
    assert held in DECLARATION.catalogue
    assert list(held.data_types) == ["meridian.v1.Rate"]
    assert held.cadence == 86_400 and held.calendar_id == TARGET_CALENDAR
    assert held.day_time_zone == "Europe/Berlin" and held.gap_recovery == "backfill"
    # Every TARGET day from 6 September 2004.
    assert held.history == 8_100
    # The ECB's terms, its sources and what the curves are not for, in words.
    for said in ("cited as the source", "MTS", "Fitch", "price or yield quotations"):
        assert said in held.terms_and_pricing
    assert "forward" in held.terms_and_pricing
