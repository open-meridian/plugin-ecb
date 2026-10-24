"""Shared stand-ins: the ECB's recorded answers, a fixed clock, TARGET's
calendar as core answers it, the platform's seeded €STR records, and the
lake's wants as the sidecar delivers them."""

from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import Any

from meridian.plugin.v1 import operations_pb2 as ops
from meridian.receive import Heard
from meridian.suites import Recorder

from ecb.declared import TARGET_CALENDAR
from ecb.estr import SERIES
from ecb.estr_feed import EstrFeed
from ecb.feed import Feed
from ecb.portal import SyntheticPortal
from ecb.raw import RawStore

#: After the recording: 16:30 UTC on Monday 19 October 2026, the day's rates
#: published at 13:56:57 UTC.
AT = datetime(2026, 10, 19, 16, 30, tzinfo=UTC)
INSTANCE = "ecb"
DATASET = f"{INSTANCE}:ecb_fx"
#: Every currency the recording rates, in its order.
CODES = [
    "AUD", "BRL", "CAD", "CHF", "CNY", "CZK", "DKK", "GBP", "HKD", "HUF",
    "IDR", "ILS", "INR", "ISK", "JPY", "KRW", "MXN", "MYR", "NOK", "NZD",
    "PHP", "PLN", "RON", "SEK", "SGD", "THB", "TRY", "USD", "ZAR",
]  # fmt: skip
#: The Last-Modified the recording states, in nanoseconds.
PUBLISHED_NS = 1792418217 * 10**9
#: After the €STR recording: 09:00 UTC on Friday 23 October 2026, €STR of
#: Thursday 22 October published at 07:20:16 UTC.
ESTR_AT = datetime(2026, 10, 23, 9, 0, tzinfo=UTC)
ESTR_DATASET = f"{INSTANCE}:ecb_estr"
ESTR_PUBLISHED_NS = 1792740016 * 10**9
#: The platform's seeded records, as the recorder resolves them: `INS-ESTR0`
#: for €STR, then its averages, then the index, in estr.SERIES's order.
ESTR_IDS = {s.code: f"INS-ESTR{n}" for n, s in enumerate(SERIES)}


def recorded() -> str:
    """The recorded answer's SDMX-CSV."""
    held = resources.files("ecb").joinpath("responses")
    index = json.loads(held.joinpath("index.json").read_text(encoding="utf-8"))
    return gzip.decompress(held.joinpath(index["response"]["file"]).read_bytes()).decode()


def target_2026(params: ops.ReadCalendarParams) -> ops.ReadCalendarResult:
    """TARGET's calendar as core answers it: Saturday and Sunday, and 2026's
    six closing days, covered from 2016 to 2028."""
    assert params.calendar_id == TARGET_CALENDAR
    closed = ["2026-01-01", "2026-04-03", "2026-04-06", "2026-05-01", "2026-12-25", "2026-12-26"]
    return ops.ReadCalendarResult(
        found=True,
        calendar_id=TARGET_CALENDAR,
        version=1,
        days=[ops.CalendarDay(date=d, kind=ops.CALENDAR_DAY_KIND_CLOSED) for d in closed],
        weekends=[
            ops.CalendarWeekend(
                weekdays=[ops.WEEKDAY_SATURDAY, ops.WEEKDAY_SUNDAY], valid_from_date="2016-01-01"
            )
        ],
        coverage=ops.CalendarCoverage(from_date="2016-01-01", to_date="2028-12-31"),
    )


def recorder(ambiguous: str = "", missing: str = "") -> Recorder:
    """The suite's recorder answering each ISO code with `LCL-<code>`
    (`ambiguous` with two records, `missing` with none), each €STR record by
    its seed's symbol at the ECB with `ESTR_IDS`'s (`missing` with none),
    and TARGET's calendar; the SDK's recorder counts each batch of rates."""
    plugin = Recorder(INSTANCE)

    def resolved(params: ops.ResolveIdentifierParams) -> ops.ResolveIdentifierResult:
        code = params.identifiers[0].value
        if params.identifiers[0].source == "ecb":
            if code == missing:
                return ops.ResolveIdentifierResult(
                    found=False, miss_reason=ops.MISS_REASON_NOT_FOUND
                )
            return ops.ResolveIdentifierResult(found=True, instrument_id=ESTR_IDS[code])
        if code == ambiguous:
            return ops.ResolveIdentifierResult(found=False, miss_reason=ops.MISS_REASON_AMBIGUOUS)
        if code == missing:
            return ops.ResolveIdentifierResult(found=False, miss_reason=ops.MISS_REASON_NOT_FOUND)
        return ops.ResolveIdentifierResult(found=True, instrument_id=f"LCL-{code}")

    plugin.answer("ResolveIdentifier", resolved)
    plugin.answer("ReadCalendar", target_2026)
    return plugin


def feed(tmp: Path, plugin: Recorder | None = None, at: datetime = AT, portal: Any = None) -> Feed:
    """The plugin's work on the suite's recorder and the recorded answer, at `at`."""
    return Feed(
        plugin or recorder(),
        portal or SyntheticPortal(lambda: at),
        RawStore(tmp),
        now=lambda: at,
    )


def estr_feed(
    tmp: Path, plugin: Recorder | None = None, at: datetime = ESTR_AT, portal: Any = None
) -> EstrFeed:
    """€STR's work beside the reference rates', on the recorder and the
    recorded answers, at `at`."""
    return EstrFeed(feed(tmp, plugin, at, portal))


def want(
    want_id: str,
    subjects: list[str],
    *,
    day: str = "",
    standing: bool = False,
    kinds: tuple[Any, ...] = (ops.PRICE_KIND_CLOSE,),
    data_type: str = "meridian.v1.Price",
    dataset: str = DATASET,
    valid_from_ns: int = 0,
    valid_until_ns: int = 0,
) -> Heard:  # type: ignore[type-arg]
    return Heard(
        row="ObservationsWanted",
        message=ops.ObservationsWantedEvent(
            want_id=want_id,
            dataset=dataset,
            data_type=data_type,
            subjects=[ops.SubjectRef(entity_id=s) for s in subjects],
            kinds=list(kinds),
            business_date=day,
            standing=standing,
            valid_from_ns=valid_from_ns,
            valid_until_ns=valid_until_ns,
        ),
    )
