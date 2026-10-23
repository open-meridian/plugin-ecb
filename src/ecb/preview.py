"""The pages on sample data, each printed as one HTML file:
for looking at them without a deployment.

    python -m ecb.preview connection > preview/connection.html
    python -m ecb.preview datasets > preview/datasets.html

The plugin's work runs on the SDK's suite recorder in place of a sidecar --
every currency resolved to an instrument the recorder names, each €STR
record to one the platform seeded, every batch recorded -- against the
answers committed under responses/, at 16:30 UTC on 19 October 2026: the
current rates and €STR read, €STR's history backfilled from the recording,
a want for 25 September answered, one for Saturday 17 October declined (the
ECB publishes nothing on a weekend), a standing want kept current, and a
want of €STR for 1 October answered. Each page links the kit where
the dashboard serves it, /.meridian/ui/<version>/: served beside the kit it
is styled (meridian-ui's `make serve`, or `make preview SHOTS=...`, which
checks each in a browser); opened on its own it is the page without the kit,
unstyled, which works too. `connection-first` and `datasets-first` are the
pages before the first check, with no want yet: the role's "not set up yet"
states.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime

from meridian.plugin.v1 import operations_pb2 as ops
from meridian.receive import Heard
from meridian.suites import Recorder
from meridian.testing import PageClient

from .estr import SERIES
from .estr_feed import EstrFeed
from .feed import Feed
from .page import CONNECTION, DATASETS, hold, pages
from .portal import SyntheticPortal
from .raw import RawStore

AT = datetime(2026, 10, 19, 16, 30, tzinfo=UTC)
PAGES = {
    "connection": CONNECTION,
    "datasets": DATASETS,
    "datasets-search": DATASETS,
    "connection-first": CONNECTION,
    "datasets-first": DATASETS,
}
#: What the Datasets tab's search is shown with, as `datasets-search`.
SEARCHED = "krona"


def _want(want_id: str, subject: str, day: str = "", standing: bool = False) -> Heard:  # type: ignore[type-arg]
    return Heard(
        row="ObservationsWanted",
        message=ops.ObservationsWantedEvent(
            want_id=want_id,
            dataset="ecb:ecb_fx",
            data_type="meridian.v1.Price",
            subjects=[ops.SubjectRef(entity_id=subject)],
            kinds=[ops.PRICE_KIND_CLOSE],
            business_date=day,
            standing=standing,
        ),
    )


def _feed() -> tuple[Feed, EstrFeed]:
    recorder = Recorder("ecb")
    seeded = {s.code: f"INS-{s.isin}" for s in SERIES}

    def resolved(params: ops.ResolveIdentifierParams) -> ops.ResolveIdentifierResult:
        named = params.identifiers[0]
        if named.source == "ecb":
            return ops.ResolveIdentifierResult(found=True, instrument_id=seeded[named.value])
        return ops.ResolveIdentifierResult(found=True, instrument_id=f"INS-{named.value}")

    recorder.answer("ResolveIdentifier", resolved)
    recorder.answer("RecordRates", lambda p: ops.RecordRatesResult(recorded=len(p.rates)))
    feed = Feed(recorder, SyntheticPortal(lambda: AT), RawStore(), now=lambda: AT)
    return feed, EstrFeed(feed)


async def synthetic_feed() -> tuple[Feed, EstrFeed]:
    """The feeds as sample data leaves them, on the recorder."""
    feed, estr = _feed()
    await feed.check()
    await estr.check()
    euro = feed.euro()
    await feed.on_want(_want("want-0925", euro, "2026-09-25"))
    await feed.on_want(_want("want-1017", euro, "2026-10-17"))
    await feed.on_want(_want("want-standing", euro, standing=True))
    rate = ops.ObservationsWantedEvent(
        want_id="want-estr-1001",
        dataset="ecb:ecb_estr",
        data_type="meridian.v1.Rate",
        subjects=[ops.SubjectRef(entity_id=estr.status.records["ESTR"].instrument_id)],
        business_date="2026-10-01",
    )
    await feed.on_want(Heard(row="ObservationsWanted", message=rate))
    return feed, estr


def render(page: str) -> str:
    feed, estr = _feed() if page.endswith("-first") else asyncio.run(synthetic_feed())
    hold(feed, estr)
    query = {"q": SEARCHED} if page == "datasets-search" else {}
    answer = PageClient(pages).get(PAGES[page], "admin", **query)
    if answer.status != 200:
        raise SystemExit(f"{page} answered {answer.status}: {answer.text[:200]}")
    return answer.text


def main() -> None:
    page = sys.argv[1] if len(sys.argv) > 1 else "connection"
    if page not in PAGES:
        raise SystemExit(f"no page {page!r}: {', '.join(PAGES)}")
    sys.stdout.write(render(page))


if __name__ == "__main__":
    main()
