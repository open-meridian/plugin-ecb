"""The euro short-term rate (€STR), read from the portal's SDMX-CSV as it
writes them: the rate, its compounded averages and its compounded index.

The ECB computes €STR for each TARGET business day from the previous day's
overnight unsecured borrowing, and publishes it at 08:00 CET the next TARGET
business day; a rate out by more than 2 basis points is revised by 09:00
(its €STR methodology). The compounded averages and the index are published
with it, computed from €STR up to that day. All come from one dataflow,
`EST`, one series each, named by the ISIN the ECB gives it and the data type
(`EST.B.<ISIN>.<type>`). What is read here, and nothing else:

- `KEY`, the series; `TIME_PERIOD`, the day the rate is for (the reference
  date), a plain date; `OBS_VALUE`, the value as the text the portal wrote;
  `UNIT_MULT`, its scale (6 for the volume, in millions of euros; else 0);
  `OBS_STATUS`, `A` normal or `P` provisional;
- for €STR itself (`EU000A2X2A25`): the rate (`WT`, the volume-weighted
  trimmed mean), its 25th and 75th percentiles (`R25`, `R75`), its total
  volume (`TT`) and its number of transactions (`NT`). The answer's other
  series of it -- the number of banks, the five largest banks' share, the
  calculation method and the publication type -- are kept in the raw answer
  and not converted;
- each compounded average (`CR`) and the compounded index (`CI`).

Every number is made a Decimal from its text, never a float; a rate may be
negative (it was until 2022). An empty value, or one that is not a number,
is no value, never a zero: a rate's own value missing is no rate, kept as not
read and shown on the Datasets page; a percentile, volume or count missing
is left out of its rate. An answer that does not hold these columns is
refused with why, and nothing is recorded from it.

**Subjects.** Each series is one of the platform's seeded referential records
(contract v27; spec/a-public-rates-and-filings-data-plugin §2), named by the
administrator's code as a source-scoped `symbol` at `ecb`, the seed's own
names; €STR also by its ISIN, as the seed carries it.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

#: The columns every answer must hold.
COLUMNS = ("KEY", "TIME_PERIOD", "OBS_VALUE")
#: The administrator: the symbol's source on each seeded record.
ADMINISTRATOR = "ecb"
#: €STR's own ISIN, and its data types the plugin converts.
ESTR_ISIN = "EU000A2X2A25"
RATE, P25, P75, VOLUME, COUNT = "WT", "R25", "R75", "TT", "NT"
AVERAGE, INDEX = "CR", "CI"
#: The compounded index's base, as the ECB states it ("1 Oct 2019 = 100").
INDEX_BASE = "2019-10-01=100"

_NUMBER = re.compile(r"^-?\d+(?:\.\d+)?$")
_KEY = re.compile(r"^EST\.B\.([A-Z0-9]{12})\.([A-Z0-9]+)$")


@dataclass(frozen=True)
class Series:
    """One of the seven records the dataset rates: the ECB's ISIN and data
    type for it, the seed's code (its symbol at `ecb`), the kind of rate,
    the record's type, and a short name for the pages."""

    isin: str
    data_type: str
    code: str
    kind: str
    instrument_type: str
    name: str

    @property
    def key(self) -> str:
        """The ECB's series key: `EST.B.EU000A2X2A25.WT`."""
        return f"EST.B.{self.isin}.{self.data_type}"

    def identifiers(self) -> tuple[tuple[str, str, str], ...]:
        """The identifiers the seeded record carries: the code as a symbol at
        the ECB, and €STR's ISIN."""
        named = [("symbol", self.code, ADMINISTRATOR)]
        if self.isin == ESTR_ISIN:
            named.append(("isin", self.isin, ""))
        return tuple(named)


#: The seven, in the order the pages list them, each as the platform's seed
#: names it (`ecb:<code>`).
SERIES: tuple[Series, ...] = (
    Series(ESTR_ISIN, RATE, "ESTR", "fixing", "interest_rate", "Euro short-term rate (€STR)"),
    Series(
        "EU000A2QQF16", AVERAGE, "ESTR 1-week compounded average", "average",
        "interest_rate", "€STR compounded average rate, 1 week",
    ),
    Series(
        "EU000A2QQF24", AVERAGE, "ESTR 1-month compounded average", "average",
        "interest_rate", "€STR compounded average rate, 1 month",
    ),
    Series(
        "EU000A2QQF32", AVERAGE, "ESTR 3-month compounded average", "average",
        "interest_rate", "€STR compounded average rate, 3 months",
    ),
    Series(
        "EU000A2QQF40", AVERAGE, "ESTR 6-month compounded average", "average",
        "interest_rate", "€STR compounded average rate, 6 months",
    ),
    Series(
        "EU000A2QQF57", AVERAGE, "ESTR 12-month compounded average", "average",
        "interest_rate", "€STR compounded average rate, 12 months",
    ),
    Series(
        "EU000A2QQF08", INDEX, "ESTR compounded index", "index_level", "index",
        "€STR compounded index",
    ),
)  # fmt: skip
BY_KEY = {s.key: s for s in SERIES}
#: The parts of €STR's own day beside its rate, by data type.
PARTS = (P25, P75, VOLUME, COUNT)


class NotEstr(ValueError):
    """The answer is not the €STR series this plugin can read."""


@dataclass(frozen=True)
class Value:
    """One value the portal stated: its text, as a Decimal scaled by its
    unit multiplier, and its status."""

    text: str
    value: Decimal
    status: str = ""


@dataclass(frozen=True)
class Fixing:
    """One record's value on one day: the rate, average or index level, and
    for €STR itself its percentiles, volume and count where stated."""

    series: Series
    day: date
    value: Value
    parts: dict[str, Value] = field(default_factory=dict)

    @property
    def preliminary(self) -> bool:
        """The ECB marks a provisional value `P`."""
        return self.value.status == "P"

    @property
    def stated(self) -> str:
        """Everything the row states, as one text: a change to any of it is
        the row's next version (raw.py notes where each was first read)."""
        parts = "|".join(f"{name}={self.parts[name].text}" for name in PARTS if name in self.parts)
        return f"{self.value.text}|{self.value.status}|{parts}"


@dataclass(frozen=True)
class Fixings:
    """An answer's values, by record and day, and what in it was not a value."""

    fixings: tuple[Fixing, ...] = ()
    #: Each line naming one of the seven records' values with none that
    #: reads, as `<series key> <day>: <text>`.
    unread: tuple[str, ...] = ()

    @property
    def days(self) -> tuple[date, ...]:
        return tuple(sorted({f.day for f in self.fixings}))

    def latest(self, series: Series) -> date | None:
        """The latest day the answer states a value of `series` for."""
        days = [f.day for f in self.fixings if f.series == series]
        return max(days) if days else None


def _value(text: str, multiplier: str, status: str) -> Value | None:
    if not _NUMBER.match(text):
        return None
    scale = int(multiplier) if multiplier.isdigit() else 0
    return Value(text, Decimal(text) * 10**scale, status)


def parse(text: str) -> Fixings:
    """The values `text` holds, or NotEstr saying why it holds none."""
    if not text.strip():
        return Fixings()
    reader = csv.DictReader(io.StringIO(text))
    held = reader.fieldnames or []
    missing = [c for c in COLUMNS if c not in held]
    if missing:
        raise NotEstr(f"its columns lack {', '.join(missing)}: {held[:8]!r}")
    values: dict[tuple[str, str, date], Value] = {}
    unread: list[str] = []
    for line in reader:
        key = (line.get("KEY") or "").strip()
        found = _KEY.match(key)
        if found is None:
            raise NotEstr(f"a series is not one of the EST dataflow's: {key!r}")
        isin, data_type = found.groups()
        converted = f"EST.B.{isin}.{data_type}" in BY_KEY or (
            isin == ESTR_ISIN and data_type in PARTS
        )
        if not converted:
            continue
        period = (line.get("TIME_PERIOD") or "").strip()
        try:
            day = date.fromisoformat(period)
        except ValueError as failed:
            raise NotEstr(f"{key}'s period is not a day: {period!r}") from failed
        text_value = (line.get("OBS_VALUE") or "").strip()
        multiplier = (line.get("UNIT_MULT") or "0").strip()
        status = (line.get("OBS_STATUS") or "").strip()
        value = _value(text_value, multiplier, status)
        if value is None:
            unread.append(f"{key} {period}: {text_value or 'empty'}")
            continue
        values[(isin, data_type, day)] = value
    fixings: list[Fixing] = []
    for (isin, data_type, day), value in sorted(values.items(), key=lambda kv: kv[0][2]):
        series = BY_KEY.get(f"EST.B.{isin}.{data_type}")
        if series is None:
            continue
        parts: dict[str, Value] = {}
        if series.isin == ESTR_ISIN:
            parts = {p: values[(isin, p, day)] for p in PARTS if (isin, p, day) in values}
        fixings.append(Fixing(series, day, value, parts))
    return Fixings(tuple(fixings), tuple(unread))
