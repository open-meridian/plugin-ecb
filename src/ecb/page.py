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
  stream. Then **Sources**, one line per source: its state, the last day
  published, the next expected by TARGET's calendar, its calls, its last
  error.
- **Datasets** (`/datasets`): "Served", "Wants" and "Subjects", then
  **Lag**, the median and longest published-minus-valid time, and
  **Records**, each currency the ECB rates and the deployment's instrument
  for it or why there is none -- one line a row, searched and paged by the
  kit's om-pager to fit one screen.

Neither shows an account's data, since the plugin reaches none, nor a rate:
prices are the reading roles' to show.
"""

from __future__ import annotations

import statistics
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import meridian
from meridian.roles import data

from . import records
from .declared import ECB_FX_DATASET
from .feed import Feed, Status
from .portal import BASE, SERIES
from .rates import EUR

TITLE = "European Central Bank"
#: The kit these pages are built on: 0.12.0's "Facts" and "Next step".
KIT = "0.12.0"

pages = meridian.Pages(TITLE, templates=Path(__file__).parent / "templates", kit=KIT)

CONNECTION = "/"
DATASETS = "/datasets"

#: The longest search the Datasets tab reads.
MOST_QUERY = 100
#: How many wants the Datasets tab lists; read_datasets answers every one held.
SHOWN_WANTS = 3
#: The attribution the ECB's terms ask for, which the contract's licence has
#: no field for until the rates slice (the spec's item 4).
ATTRIBUTION = (
    "Source: European Central Bank. Cite the ECB as the source, reproduce the "
    "rates accurately, and say so where they are changed."
)
SOURCE_NAME = "ECB euro foreign exchange reference rates"

_held: dict[str, Feed] = {}


def hold(feed: Feed) -> None:
    """The feed the pages read, once the plugin has registered."""
    _held["feed"] = feed


def _status() -> tuple[Status, Feed | None]:
    feed = _held.get("feed")
    return (feed.status if feed is not None else Status(), feed)


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


def _state(status: Status) -> tuple[str, str, str]:
    """The head's status: its state, what it means, and its detail."""
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


def connection_read(status: Status, feed: Feed | None) -> records.ConnectionRead:
    state, said, _ = _state(status)
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
        calls=status.fetches,
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
                state=said,
                last_release=_day(status.latest_day),
                next_expected=_day(status.next_release),
                calls=status.fetches,
                last_error=status.error,
            )
        ],
        not_modified=status.not_modified,
        responses_kept=len(kept),
        kept_for=window,
    )


def _duration(seconds: int) -> str:
    hours, rest = divmod(max(seconds, 0), 3600)
    return f"{hours} h {rest // 60:02d} m"


def lag_read(status: Status, dataset: str) -> records.LagRead:
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
    answered = status.read_at is not None or status.mode == "synthetic"
    served = data.served(
        [ECB_FX_DATASET],
        instance,
        feed.wants if feed is not None else None,
        "Yes: no key needed" if answered else "Not asked yet",
    )
    served = [replace(s, default_terms="kept, derived use, display; cite the ECB") for s in served]
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
        lag=[lag_read(status, dataset)],
        unread=[f"{line} ({n} reads)" for line, n in sorted(status.unread.items())],
    )


def figures(status: Status, feed: Feed | None) -> list[meridian.Figure]:
    """The data role's figures, in its order (`meridian.roles.data`); the
    ECB's plugin reports none of its own."""
    state, said, why = _state(status)
    if status.mode == "synthetic" and state == "ok":
        connection: Any = "Sample data"
    elif said == "Not answering":
        connection = meridian.Figure("", said, state="error", why=why[:200])
    else:
        connection = meridian.Figure(
            "", "Answering", state="warn" if status.error else None, why=status.error[:200]
        )
    last = feed.wants.counts.last_ns if feed is not None else 0
    return data.figures(
        connection=connection,
        entitled_at_vendor="1 of 1 datasets",
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
    return pages.answer("connection.html", read, detail=_state(status)[2])


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
    # A browser's search narrows the currencies drawn, and it is drawn the
    # latest wants; a tool answers them all.
    query = request.query.get("q", "").strip()[:MOST_QUERY]
    shown = [r for r in read.records if matching(query, r.code, r.name)]
    drawn = read if request.tool_name else replace(read, wants=read.wants[:SHOWN_WANTS])
    return pages.answer(
        "datasets.html",
        drawn,
        query=query,
        shown=shown,
        state=_state(status),
        checked_at=_iso(status.checked_at),
        wants=len(read.wants),
    )
