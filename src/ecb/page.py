"""The plugin's pages, under Manage alone: the data role's common pages
(spec/plugin-pages-follow-their-role), Connection and Datasets, in its
order, each also a read tool for agents on the deployment's MCP under the
role's names (`read_connection`, `read_datasets`). Each record is the
role's (`meridian.roles.data`), extended with the ECB's fields; each
template is the role's, with the ECB's nuance at its blocks only.

A data plugin shows its connectivity, its data subscriptions and how its
entitlements resolve, and no market data (the product owner, 2026-10-03).
So, as spec/a-public-rates-and-filings-data-plugin §5 has them:

- **Connection** (`/`): "Key" -- the mode (Live or Sample data), "No key
  needed", what the ECB serves; "Limits and use" -- the ECB states no
  limit, the requests made, the last check and error; "Stream": it does not
  stream. Then, a tab of its own (`?tab=sources`, from 0.6.0, to keep each
  to one screen), **Sources**, one line per source -- the reference rates,
  €STR and the yield curves: its state, the last day published, the next
  expected by TARGET's calendar, its calls, its last error, and in its
  detail how far its history is recorded.
- **Datasets** (`/datasets`): "Served", "Wants" and "Subjects", each with
  the three datasets, **Lag** a column of "Served", the median published-
  minus-valid time of each; then, a tab of its own (`?tab=records`, from
  0.6.0), **Records**: the seven €STR records, the two
  yield curves and each currency the ECB rates, with the deployment's
  instrument for each or why there is none -- one line a row, searched and
  paged by the kit's om-pager to fit one screen.

Neither shows an account's data, since the plugin reaches none, nor a rate:
prices are the reading roles' to show.
"""

from __future__ import annotations

import statistics
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import meridian
from meridian.roles import data

from . import records
from .curve_feed import CurveFeed, CurveStatus
from .declared import ECB_ESTR_DATASET, ECB_FX_DATASET, ECB_YC_DATASET
from .estr_feed import EstrFeed, EstrStatus
from .feed import Feed, Status
from .portal import BASE, ESTR_SERIES, SERIES
from .rates import EUR

TITLE = "European Central Bank"
#: The kit these pages are built on: 0.12.0's "Facts" and "Next step".
KIT = "0.12.0"

pages = meridian.Pages(TITLE, templates=Path(__file__).parent / "templates", kit=KIT)

CONNECTION = "/"
DATASETS = "/datasets"

#: The longest search the Datasets tab reads.
MOST_QUERY = 100
#: Connection's tabs, by the name its links carry (as plugin-fed-board's).
CONNECTION_TABS = {"connection": "Connection", "sources": "Sources"}
#: Datasets' tabs, by the name its links carry.
TABS = {"served": "Served", "records": "Records"}
#: The attribution the ECB's terms ask for, said on the Datasets page beside
#: each dataset's terms in words.
ATTRIBUTION = (
    "Source: European Central Bank. Cite the ECB as the source, reproduce the "
    "rates accurately, and say so where they are changed."
)
SOURCE_NAME = "ECB euro foreign exchange reference rates"
ESTR_SOURCE_NAME = "ECB euro short-term rate (€STR)"
CURVE_SOURCE_NAME = "ECB euro area yield curves"
#: What each kind of €STR record, and a curve, is recorded as, for a person.
RECORDED_AS = {
    "fixing": "fixings",
    "average": "averages",
    "index_level": "index levels",
    "curve": "zero rates and par yields",
}

_held: dict[str, Any] = {}


def hold(feed: Feed, estr: EstrFeed | None = None, curve: CurveFeed | None = None) -> None:
    """The feeds the pages read, once the plugin has registered."""
    _held["feed"] = feed
    _held["estr"] = estr
    _held["curve"] = curve


def _status() -> tuple[Status, Feed | None]:
    feed = _held.get("feed")
    return (feed.status if feed is not None else Status(), feed)


def _estr() -> EstrFeed | None:
    estr: EstrFeed | None = _held.get("estr")
    return estr


def _curve() -> CurveFeed | None:
    curve: CurveFeed | None = _held.get("curve")
    return curve


def _iso(moment: datetime | None) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds") if moment else ""


def _day(day: date | None) -> str:
    return day.isoformat() if day else ""


def _published(last_modified: str) -> str:
    try:
        moment = datetime.strptime(last_modified, "%a, %d %b %Y %H:%M:%S GMT")
    except ValueError:
        return ""
    return moment.replace(tzinfo=UTC).isoformat(timespec="seconds")


def _state(
    status: Status, estr: EstrStatus | None = None, curve: CurveStatus | None = None
) -> tuple[str, str, str]:
    """The head's status: its state, what it means, and its detail -- the
    reference rates' first, then €STR's, then the yield curves', each where
    the ones before say nothing worse."""
    state = _fx_state(status)
    if state[0] in ("error", "busy"):
        return state
    if estr is not None and estr.error:
        return "warn", "Answering", f"€STR: {estr.error}"
    if curve is not None and curve.error:
        return "warn", "Answering", f"Yield curves: {curve.error}"
    if state[0] != "ok":
        return state
    misses = [r for r in estr.records.values() if r.miss] if estr is not None else []
    if misses:
        codes = ", ".join(r.series.code for r in misses)
        plural = "record" if len(misses) == 1 else "records"
        return "warn", f"{len(misses)} €STR {plural} not resolved", codes
    curves = [r for r in curve.records.values() if r.miss] if curve is not None else []
    if curves:
        codes = ", ".join(r.curve.code for r in curves)
        plural = "curve" if len(curves) == 1 else "curves"
        return "warn", f"{len(curves)} yield {plural} not resolved", codes
    return state


def _fx_state(status: Status) -> tuple[str, str, str]:
    """The reference rates' state, what it means, and its detail."""
    misses = [c for c in status.currencies.values() if c.miss]
    read = status.read_at is not None or status.not_modified
    if status.error and not read:
        return "error", "Not answering", status.error
    if status.error:
        return "warn", "Answering", status.error
    if not read:
        return "busy", "Checking the ECB", ""
    if misses:
        codes = ", ".join(sorted(c.code for c in misses))
        plural = "currency" if len(misses) == 1 else "currencies"
        return "warn", f"{len(misses)} {plural} not resolved", codes
    if status.mode == "synthetic":
        return "ok", "Sample data", ""
    return "ok", "Answering", ""


def _calendar(status: Status) -> str:
    days = status.calendar
    if days is None:
        return ""
    if days.unread:
        return f"Not read: {days.unread}; Monday to Friday assumed"
    return f"TARGET closing days, version {days.version}"


def _estr_source(estr: EstrFeed, instance: str) -> records.SourceRead:
    """€STR's line in "Sources"."""
    held = estr.status
    if held.error and held.read_at is None:
        said = "Not answering"
    elif held.error:
        said = "Answering"
    elif held.read_at is None and not held.not_modified:
        said = "Checking the ECB"
    else:
        said = "Sample data" if held.mode == "synthetic" else "Answering"
    around = "around 08:00 CET"
    if held.next_rate_day:
        around += f", the rate of {held.next_rate_day:%a %d %b}"
    return records.SourceRead(
        source=ESTR_SOURCE_NAME,
        dataset=f"{instance}:{ECB_ESTR_DATASET.key}",
        state=said,
        last_release=_day(held.latest_day),
        next_expected=_day(held.next_release),
        calls=held.fetches,
        last_error=held.error,
        reads=(
            "The answer recorded on 2026-10-23, committed with the plugin"
            if held.mode == "synthetic"
            else f"{BASE}{ESTR_SERIES}, every €STR series"
        ),
        published_at=_published(held.last_modified),
        published_around=around,
        not_modified=held.not_modified,
        history=held.backfill,
    )


def _curve_source(curve: CurveFeed, instance: str) -> records.SourceRead:
    """The yield curves' line in "Sources"."""
    held = curve.status
    if held.error and held.read_at is None:
        said = "Not answering"
    elif held.error:
        said = "Answering"
    elif held.read_at is None and not held.not_modified:
        said = "Checking the ECB"
    else:
        said = "Sample data" if held.mode == "synthetic" else "Answering"
    around = "around 12:00 CET"
    if held.next_rate_day:
        around += f", the curves of {held.next_rate_day:%a %d %b}"
    return records.SourceRead(
        source=CURVE_SOURCE_NAME,
        dataset=f"{instance}:{ECB_YC_DATASET.key}",
        state=said,
        last_release=_day(held.latest_day),
        next_expected=_day(held.next_release),
        calls=held.fetches,
        last_error=held.error,
        reads=(
            "The answer recorded on 2026-11-19, committed with the plugin"
            if held.mode == "synthetic"
            else f"{BASE}/service/data/YC, the AAA and all-ratings curves' spot rates and par "
            "yields, 3 months to 30 years"
        ),
        published_at=_published(held.last_modified),
        published_around=around,
        not_modified=held.not_modified,
        history="Any past day from 6 September 2004, when the lake wants it",
    )


def _statuses() -> tuple[EstrStatus | None, CurveStatus | None]:
    estr, curve = _estr(), _curve()
    return (
        estr.status if estr is not None else None,
        curve.status if curve is not None else None,
    )


def connection_read(status: Status, feed: Feed | None) -> records.ConnectionRead:
    estr, curve = _estr(), _curve()
    state, said, _ = _state(status, *_statuses())
    beside = [f.status for f in (estr, curve) if f is not None]
    kept = feed.raw.keys() if feed is not None else []
    window = ""
    if feed is not None and feed.raw.granted:
        window = "in the storage the deployment grants, as its responses settings say"
    elif feed is not None:
        window = "in a directory of the plugin's own: this deployment grants no storage"
    instance = feed.plugin.identity.instance_id if feed is not None else "ecb"
    answered = status.read_at is not None or status.mode == "synthetic"
    return records.ConnectionRead(
        mode="Sample data" if status.mode == "synthetic" else "Live",
        credentials=[],
        entitled_at_vendor=(
            "Every euro reference rate the ECB publishes: no key" if answered else ""
        ),
        limit=(
            "The ECB states none; the plugin asks one request at a time, at most one every "
            "two seconds, and checks for new rates every hour"
        ),
        calls=status.fetches + sum(b.fetches for b in beside),
        last_call_at=_iso(status.checked_at),
        last_error=status.error,
        sessions=None,
        state=state,
        said=said,
        source=(
            "The answer recorded on 2026-10-19, committed with the plugin"
            if status.mode == "synthetic"
            else f"{BASE}{SERIES}, every currency against the euro"
        ),
        checked_at=_iso(status.checked_at),
        first_day=_day(status.first_day),
        latest_day=_day(status.latest_day),
        published_at=_published(status.last_modified),
        next_release=_day(status.next_release),
        calendar=_calendar(status),
        sources=[
            records.SourceRead(
                source=SOURCE_NAME,
                dataset=f"{instance}:{ECB_FX_DATASET.key}",
                state=_fx_state(status)[1],
                last_release=_day(status.latest_day),
                next_expected=_day(status.next_release),
                calls=status.fetches,
                last_error=status.error,
                reads=(
                    "The answer recorded on 2026-10-19, committed with the plugin"
                    if status.mode == "synthetic"
                    else f"{BASE}{SERIES}, every currency against the euro"
                ),
                published_at=_published(status.last_modified),
                published_around="around 16:00 CET",
                not_modified=status.not_modified,
                history="Any past day, when the lake wants it",
            ),
            *([_estr_source(estr, instance)] if estr is not None else []),
            *([_curve_source(curve, instance)] if curve is not None else []),
        ],
        not_modified=status.not_modified + sum(b.not_modified for b in beside),
        responses_kept=len(kept),
        kept_for=window,
    )


def _duration(seconds: int) -> str:
    hours, rest = divmod(max(seconds, 0), 3600)
    return f"{hours} h {rest // 60:02d} m"


def lag_read(status: Status | EstrStatus | CurveStatus, dataset: str) -> records.LagRead:
    lags = status.lags
    if not lags:
        return records.LagRead(dataset=dataset, said="No rate read with its published time yet")
    median, longest = int(statistics.median(lags)), max(lags)
    return records.LagRead(
        dataset=dataset,
        rates=len(lags),
        median_seconds=median,
        longest_seconds=longest,
        median=f"{_duration(median)} median",
        said=f"{_duration(median)} median, {_duration(longest)} longest, of {len(lags)} rates",
    )


def datasets_read(status: Status, feed: Feed | None) -> records.DatasetsRead:
    instance = feed.plugin.identity.instance_id if feed is not None else "ecb"
    dataset = f"{instance}:{ECB_FX_DATASET.key}"
    estr, curve = _estr(), _curve()
    answered = status.read_at is not None or status.mode == "synthetic"
    served = data.served(
        [ECB_FX_DATASET, ECB_ESTR_DATASET, ECB_YC_DATASET],
        instance,
        feed.wants if feed is not None else None,
        "Yes: no key needed" if answered else "Not asked yet",
    )
    # Each row's terms are the dataset's own words (contract 30, ruling 1032).
    currencies = sorted(status.currencies.values(), key=lambda c: (c.code != EUR, c.code))
    priced = sum(1 for c in currencies if c.code != EUR)
    return records.DatasetsRead(
        served=served,
        wants=list(data.want_rows(feed.wants)) if feed is not None else [],
        reads_instruments=True,
        attribution=ATTRIBUTION,
        records=[
            records.RecordRead(
                code=c.code,
                name=c.name,
                price_of=(
                    f"the subject of every rate, priced in {priced} currencies"
                    if c.code == EUR
                    else f"EUR in {c.code}"
                ),
                instrument_id=c.instrument_id,
                miss=c.miss.replace("_", " "),
            )
            for c in currencies
        ],
        lag=[
            lag_read(status, dataset),
            *(
                [lag_read(estr.status, f"{instance}:{ECB_ESTR_DATASET.key}")]
                if estr is not None
                else []
            ),
            *(
                [lag_read(curve.status, f"{instance}:{ECB_YC_DATASET.key}")]
                if curve is not None
                else []
            ),
        ],
        unread=[
            f"{line} ({n} reads)"
            for line, n in sorted(
                [
                    *status.unread.items(),
                    *(estr.status.unread.items() if estr else []),
                    *(curve.status.unread.items() if curve else []),
                ]
            )
        ],
        rates=[
            records.RateRecordRead(
                code=r.series.code,
                name=r.series.name,
                kind=r.series.kind,
                series=r.series.key,
                instrument_id=r.instrument_id,
                miss=r.miss,
                latest_day=_day(r.latest_day),
            )
            # Listed once €STR has been checked: before, nothing is resolved.
            for r in (estr.status.records.values() if estr and estr.status.checked_at else [])
        ],
        curves=[
            records.RateRecordRead(
                code=r.curve.code,
                name=r.curve.name,
                kind="curve",
                series=f"{r.curve.code}.SR_* and .PY_*, 3M to 30Y",
                instrument_id=r.instrument_id,
                miss=r.miss,
                latest_day=_day(r.latest_day),
            )
            # Listed once the curves have been checked: before, nothing is resolved.
            for r in (curve.status.records.values() if curve and curve.status.checked_at else [])
        ],
    )


def figures(
    status: Status,
    feed: Feed | None,
    estr: EstrStatus | None = None,
    curve: CurveStatus | None = None,
) -> list[meridian.Figure]:
    """The data role's figures, in its order (`meridian.roles.data`); the
    ECB's plugin reports none of its own."""
    state, said, why = _state(status, estr, curve)
    error = (
        status.error
        or (f"€STR: {estr.error}" if estr is not None and estr.error else "")
        or (f"Yield curves: {curve.error}" if curve is not None and curve.error else "")
    )
    if status.mode == "synthetic" and state == "ok":
        connection: Any = "Sample data"
    elif said == "Not answering":
        connection = meridian.Figure("", said, state="error", why=why[:200])
    else:
        connection = meridian.Figure(
            "", "Answering", state="warn" if error else None, why=error[:200]
        )
    last = feed.wants.counts.last_ns if feed is not None else 0
    return data.figures(
        connection=connection,
        entitled_at_vendor="3 of 3 datasets",
        stream="Does not stream",
        last_recorded=(datetime.fromtimestamp(last / 10**9, UTC) if last else None),
    )


def _moment(value: str) -> str:
    """An ISO moment as a person reads it, to the minute in UTC."""
    if not value:
        return ""
    if len(value) == 10:
        return value
    return datetime.fromisoformat(value).astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


def _weekday(value: str) -> str:
    return date.fromisoformat(value).strftime("%a %d %b") if value else ""


def matching(query: str, *texts: str) -> bool:
    """Whether every word of a search is in one of `texts`, case aside."""
    words = query.lower().split()
    held = " ".join(texts).lower()
    return all(word in held for word in words)


pages.environment.filters["moment"] = _moment
pages.environment.filters["day"] = _weekday


@pages.page(
    CONNECTION,
    "Connection",
    levels="admin",
    answers=records.ConnectionRead,
    name="read_connection",
    description=(
        "How this plugin reaches the European Central Bank's Data Portal, as every data "
        "plugin's Connection answers it: the mode (Live or Sample data), no key needed, "
        "what the ECB serves, its limits (none stated) and the requests made, the last "
        "check and why it failed if it did; it does not stream. Then the ECB's own: each "
        "source with its state, the latest day it published, the next day expected by "
        "TARGET's calendar, its calls and last error; and how many answers are kept. "
        "No rate."
    ),
)
async def connection(request: meridian.Request) -> meridian.Response:
    status, feed = _status()
    read = connection_read(status, feed)
    detail = _state(status, *_statuses())[2]
    tab = request.query.get("tab", "connection")
    return pages.answer(
        "connection.html",
        read,
        detail=detail,
        # Named apart from the SDK's own `tab` and `tabs` (0.32.3), which
        # would draw the data role's section row in their place.
        view=tab if tab in CONNECTION_TABS else "connection",
        views=CONNECTION_TABS,
    )


@pages.page(
    DATASETS,
    "Datasets",
    levels="admin",
    answers=records.DatasetsRead,
    name="read_datasets",
    description=(
        "What this plugin serves the lake, as every data plugin's Datasets answers it: its "
        "one dataset as the catalogue declares it (the ECB's daily euro reference rates, "
        "Frankfurt's day, TARGET's calendar, kept with the ECB cited), whether a deployment "
        "admin has licensed it, what it recorded and declined; the standing wants it keeps "
        "current and the wants it answered. Then the ECB's own: the attribution its terms "
        "ask for, the lag between a rate's day and its publication, and each currency the "
        "ECB rates with the deployment's instrument for it or why there is none. No rate."
    ),
)
async def datasets(request: meridian.Request) -> meridian.Response:
    status, feed = _status()
    read = datasets_read(status, feed)
    # A browser draws one tab, its search narrowing the records drawn; the
    # wants are all drawn, paged by the kit; a tool answers every tab.
    query = request.query.get("q", "").strip()[:MOST_QUERY]
    tab = request.query.get("tab", "served")
    tab = "records" if query else tab if tab in TABS else "served"
    shown = [r for r in read.records if matching(query, r.code, r.name)]
    shown_rates = [r for r in read.rates if matching(query, r.code, r.name, r.series)]
    shown_curves = [r for r in read.curves if matching(query, r.code, r.name, r.series)]
    return pages.answer(
        "datasets.html",
        read,
        query=query,
        tab=tab,
        tabs=TABS,
        shown=shown,
        shown_rates=shown_rates,
        shown_curves=shown_curves,
        recorded_as=RECORDED_AS,
        state=_state(status, *_statuses()),
        checked_at=_iso(status.checked_at),
    )
