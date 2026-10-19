"""The typed records the pages answer, for a person's page and an agent's
tool alike (contract v12; spec/a-deployment-serves-its-mcp): the data role's
common records (`meridian.roles.data`, spec/plugin-pages-follow-their-role),
each extended with the ECB's own fields under the names
spec/a-public-rates-and-filings-data-plugin §5 gives its vendor sections:
Connection's **Sources**, and Datasets' **Records** and **Lag**. The
Connection tab is `read_connection`, the Datasets tab `read_datasets`, each
answering what its page shows, as data, under the role's names.

A data plugin's pages show its connection and its datasets, never a price
(plans/the-lake-prices-the-book, ruled 2026-10-03): prices are the reading
roles'. So neither record holds a rate; each says how the ECB was reached
and what the plugin serves of it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from meridian.roles import data


@dataclass(frozen=True)
class SourceRead:
    """One source the plugin reads, as "Sources" lists it: its state, the
    last day it published, the next expected by the dataset's calendar, the
    calls made of it, and its last error."""

    source: str
    dataset: str
    state: str
    last_release: str = ""
    next_expected: str = ""
    calls: int = 0
    last_error: str = ""


@dataclass(frozen=True)
class ConnectionRead(data.ConnectionRead):
    """Connection's common fields, then the ECB's: the head's status and what
    it means, where it reads, the last check, the current range's first and
    latest day and the portal's Last-Modified for it, the next rates
    expected by TARGET's calendar and how that calendar was read, each
    source as "Sources" lists it, and the answers kept."""

    #: The head's status: `ok`, `busy`, `warn` or `error`, and what it means.
    state: str = ""
    said: str = ""
    source: str = ""
    checked_at: str = ""
    first_day: str = ""
    latest_day: str = ""
    #: When the portal says the rates last changed, ISO 8601.
    published_at: str = ""
    #: The next day the ECB publishes on by TARGET's calendar, around 16:00 CET.
    next_release: str = ""
    calendar: str = ""
    sources: list[SourceRead] = field(default_factory=list)
    not_modified: int = 0
    responses_kept: int = 0
    kept_for: str = ""


@dataclass(frozen=True)
class RecordRead:
    """One currency the ECB rates, as "Records" lists it: the ECB's name for
    it, what its rates are the price of, and the deployment's instrument
    resolved for it, or why there is none."""

    code: str
    name: str
    price_of: str
    instrument_id: str
    miss: str


@dataclass(frozen=True)
class LagRead:
    """The "Lag" section: published minus valid time for the dataset's rates first read
    with their published time since the plugin started -- the median and
    the longest, in seconds and in words -- and how many."""

    dataset: str
    rates: int = 0
    median_seconds: int = 0
    longest_seconds: int = 0
    #: The median, and the whole, in words.
    median: str = ""
    said: str = ""


@dataclass(frozen=True)
class DatasetsRead(data.DatasetsRead):
    """Datasets' common fields, then the ECB's: the attribution its terms
    ask for, each currency it rates ("Records"), the lag of its rates
    ("Lag"), and the lines it could not read. Its rows are the role's."""

    served: list[data.Served] = field(default_factory=list)
    wants: list[data.WantHeard] = field(default_factory=list)  # type: ignore[assignment]
    attribution: str = ""
    records: list[RecordRead] = field(default_factory=list)
    lag: list[LagRead] = field(default_factory=list)
    #: The portal's lines that named a rate holding none that reads, each
    #: with how often seen.
    unread: list[str] = field(default_factory=list)
