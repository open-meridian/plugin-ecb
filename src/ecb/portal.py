"""The ECB Data Portal, where the euro foreign exchange reference rates are
published, and its stand-in.

One kind of request is made, and nothing else: the daily reference rates of
every currency against the euro over a range of days, as SDMX-CSV --
`/service/data/EXR/D..EUR.SP00.A?format=csvdata&startPeriod=<day>&endPeriod=<day>`
(the EXR dataflow; daily; any currency; against the euro; the spot reference
rate; its average). A range with no rate, a weekend or a TARGET closing
day, is answered 200 with an empty body.

The current rates are a range ending today, read hourly. That request says
`If-Modified-Since` with the Last-Modified the portal last stated, and the
portal answers 304 when nothing changed, so an hour with nothing new costs
one empty answer. The ECB updates the rates at around 16:00 CET on each
TARGET business day (its reference rates page); its Last-Modified is then
when it did.

Read from the ECB itself: no key, no account, and its terms are its
website's (docs/terms.md). It states no rate limit for the portal; the
plugin asks one request at a time, at most one every two seconds, says who
it is in its User-Agent, and checks the current rates once an hour. The
standard library's client: the SDK carries none, and one kind of request
needs nothing more.

`SyntheticPortal` answers from the real response committed under
responses/, recorded on 2026-10-19 (responses/index.json): every rate from
3 August to 19 October 2026. A request for a range is answered with the
recorded rows in it, under the recording's Last-Modified, and its current
range ends on 19 October 2026 whatever the clock says, so the plugin's tests
and its e2e run on it, offline, the same on any day.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from importlib import resources
from typing import Protocol

BASE = "https://data-api.ecb.europa.eu"
SERIES = "/service/data/EXR/D..EUR.SP00.A"
USER_AGENT = "meridian-ecb (+https://github.com/open-meridian/plugin-ecb)"
#: The least time between two requests to the portal, in seconds.
SPACING = 2.0
#: How long one request may take.
TIMEOUT = 60.0
#: The most of an answer read: a quarter of every currency is under 1 MB.
MOST_BYTES = 16 * 1024 * 1024
#: How many days the current range reaches back: a correction to a rate of
#: the last week or so is read as the same row's next version.
CURRENT_DAYS = 10


def path_for(start: date, end: date) -> str:
    """The address of every reference rate from `start` to `end`."""
    return f"{SERIES}?format=csvdata&startPeriod={start.isoformat()}&endPeriod={end.isoformat()}"


class PortalUnreachable(Exception):  # noqa: N818 - what the ECB's portal was
    """The portal could not be asked: no answer, or not in time."""


@dataclass(frozen=True)
class Fetched:
    """One answer of the portal's, as received."""

    path: str
    status: int
    body: bytes
    fetched_at: datetime
    last_modified: str = ""
    date: str = ""

    @property
    def url(self) -> str:
        return BASE + self.path

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


class Portal(Protocol):
    mode: str

    def current(self, today: date) -> tuple[date, date]: ...

    async def get(self, path: str, modified_since: str = "") -> Fetched: ...


def utc_now() -> datetime:
    return datetime.now(UTC)


class LivePortal:
    """The ECB Data Portal itself."""

    mode = "live"

    def __init__(self, now: Callable[[], datetime] = utc_now) -> None:
        self._now = now
        self._lock = asyncio.Lock()
        self._last = 0.0

    def current(self, today: date) -> tuple[date, date]:
        """The current range: the last `CURRENT_DAYS` days to today."""
        return today - timedelta(days=CURRENT_DAYS), today

    async def get(self, path: str, modified_since: str = "") -> Fetched:
        async with self._lock:
            wait = self._last + SPACING - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                return await asyncio.to_thread(self._get, path, modified_since)
            finally:
                self._last = time.monotonic()

    def _get(self, path: str, modified_since: str) -> Fetched:
        headers = {"User-Agent": USER_AGENT, "Accept": "text/csv"}
        if modified_since:
            headers["If-Modified-Since"] = modified_since
        request = urllib.request.Request(BASE + path, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:  # noqa: S310 - the ECB's https address
                body = answer.read(MOST_BYTES + 1)
                status = answer.status
                said = answer.headers
        except urllib.error.HTTPError as refused:
            body = refused.read(MOST_BYTES + 1) if refused.fp else b""
            status, said = refused.code, refused.headers
        except (urllib.error.URLError, TimeoutError, OSError) as failed:
            reason = getattr(failed, "reason", failed)
            raise PortalUnreachable(f"{BASE}{path}: {type(reason).__name__}") from failed
        if len(body) > MOST_BYTES:
            raise PortalUnreachable(f"{BASE}{path}: answered more than {MOST_BYTES} bytes")
        return Fetched(
            path,
            status,
            body,
            self._now(),
            last_modified=said.get("Last-Modified", "") if said else "",
            date=said.get("Date", "") if said else "",
        )


class SyntheticPortal:
    """The response committed under responses/: each range answered with
    the recorded rows in it, under the recording's headers."""

    mode = "synthetic"

    def __init__(self, now: Callable[[], datetime] = utc_now) -> None:
        self._now = now
        held = resources.files(__package__).joinpath("responses")
        index = json.loads(held.joinpath("index.json").read_text(encoding="utf-8"))
        entry = index["response"]
        text = gzip.decompress(held.joinpath(entry["file"]).read_bytes()).decode("utf-8")
        self.header, *self.rows = text.splitlines()
        self.last_modified = str(entry["last_modified"])
        self.said = str(entry["date"])
        self.first_day = date.fromisoformat(entry["first_day"])
        self.last_day = date.fromisoformat(entry["last_day"])
        self.asked: list[str] = []

    def current(self, today: date) -> tuple[date, date]:
        """The current range of the recording: its last `CURRENT_DAYS` days."""
        return self.last_day - timedelta(days=CURRENT_DAYS), self.last_day

    async def get(self, path: str, modified_since: str = "") -> Fetched:
        self.asked.append(path)
        if not path.startswith(SERIES + "?"):
            return Fetched(path, 404, b"No such dataflow", self._now())
        query = dict(part.partition("=")[::2] for part in path.split("?", 1)[1].split("&"))
        try:
            start = date.fromisoformat(query.get("startPeriod", ""))
            end = date.fromisoformat(query.get("endPeriod", ""))
        except ValueError:
            return Fetched(path, 400, b"Invalid period", self._now())
        if modified_since and modified_since == self.last_modified:
            return Fetched(path, 304, b"", self._now(), self.last_modified, self.said)
        kept = [row for row in self.rows if start.isoformat() <= _period(row) <= end.isoformat()]
        body = "\n".join([self.header, *kept]) + "\n" if kept else ""
        return Fetched(path, 200, body.encode(), self._now(), self.last_modified, self.said)


def _period(row: str) -> str:
    """A recorded row's TIME_PERIOD: its seventh field, before any quoted one."""
    fields = row.split(",", 7)
    return fields[6] if len(fields) > 6 else ""


def portal(synthetic: bool, now: Callable[[], datetime] = utc_now) -> Portal:
    return SyntheticPortal(now) if synthetic else LivePortal(now)
