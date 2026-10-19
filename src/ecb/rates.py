"""The euro foreign exchange reference rates, read from the portal's
SDMX-CSV as it writes them.

Each line is one rate: a currency's units per euro on one day, "for
information purposes only", set at the ECB's daily concertation around
14:10 CET and published around 16:00 CET. What is read here, and nothing
else:

- `CURRENCY`, the currency's ISO 4217 code, as the ECB names it;
- `CURRENCY_DENOM`, which must be `EUR`: every rate is per euro;
- `TIME_PERIOD`, the rate's day, a plain date;
- `OBS_VALUE`, the rate, as the text the portal wrote (`5.738`, its
  trailing zero dropped; `20736.99`);
- `UNIT_MULT`, which must be `0` (units, not thousands);
- `OBS_STATUS`, kept with the rate (`A`, normal);
- `TITLE`, for the currency's name as the ECB gives it (`Australian
  dollar/Euro ECB reference exchange rate`: `Australian dollar`), shown on
  the Datasets page and never used to name a subject.

Every number is made a Decimal from its text, never a float. An empty value,
or one that is not a number, is no rate, never a zero: it is kept as not
read, and shown on the Datasets page. An empty answer is no rate at all (a
weekend, a TARGET closing day). An answer that does not hold these columns
is refused with why, and nothing is recorded from it.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal

#: The columns every answer must hold.
COLUMNS = ("CURRENCY", "CURRENCY_DENOM", "TIME_PERIOD", "OBS_VALUE")
#: The currency every rate is per unit of.
EUR = "EUR"

_NUMBER = re.compile(r"^\d+(?:\.\d+)?$")
_CODE = re.compile(r"^[A-Z]{3}$")


class NotRates(ValueError):
    """The answer is not the reference rates this plugin can read."""


@dataclass(frozen=True)
class Rate:
    """One currency's reference rate on one day: units of it per euro."""

    currency: str
    day: date
    value: Decimal
    text: str
    status: str = ""


@dataclass(frozen=True)
class Rates:
    """An answer's rates, and what in it was not a rate."""

    rates: tuple[Rate, ...] = ()
    #: Each line that named a currency and a day but no rate that reads, as
    #: `CODE day: text`.
    unread: tuple[str, ...] = field(default=())
    #: Each currency's name, as the ECB's title gives it.
    names: dict[str, str] = field(default_factory=dict)

    @property
    def days(self) -> tuple[date, ...]:
        return tuple(sorted({r.day for r in self.rates}))

    @property
    def currencies(self) -> tuple[str, ...]:
        """Each currency the answer rates, once, in its order."""
        return tuple(dict.fromkeys(r.currency for r in self.rates))


def parse(text: str) -> Rates:
    """The rates `text` holds, or NotRates saying why it holds none."""
    if not text.strip():
        return Rates()
    reader = csv.DictReader(io.StringIO(text))
    held = reader.fieldnames or []
    missing = [c for c in COLUMNS if c not in held]
    if missing:
        raise NotRates(f"its columns lack {', '.join(missing)}: {held[:8]!r}")
    rates: list[Rate] = []
    unread: list[str] = []
    names: dict[str, str] = {}
    for line in reader:
        code = (line.get("CURRENCY") or "").strip()
        denominated = (line.get("CURRENCY_DENOM") or "").strip()
        period = (line.get("TIME_PERIOD") or "").strip()
        value = (line.get("OBS_VALUE") or "").strip()
        multiplier = (line.get("UNIT_MULT") or "0").strip()
        if denominated != EUR:
            raise NotRates(f"a rate is not per euro: {code}/{denominated}")
        if multiplier != "0":
            raise NotRates(f"{code}'s rate is not in units (UNIT_MULT {multiplier!r})")
        if not _CODE.match(code):
            raise NotRates(f"a currency is not an ISO 4217 code: {code!r}")
        try:
            day = date.fromisoformat(period)
        except ValueError as failed:
            raise NotRates(f"{code}'s period is not a day: {period!r}") from failed
        title = (line.get("TITLE") or "").strip()
        if title and code not in names:
            names[code] = title.split("/", 1)[0].strip()
        if not _NUMBER.match(value):
            unread.append(f"{code} {period}: {value or 'empty'}")
            continue
        rates.append(Rate(code, day, Decimal(value), value, (line.get("OBS_STATUS") or "").strip()))
    return Rates(tuple(rates), tuple(unread), names)


def last_modified_ns(header: str) -> int:
    """An HTTP Last-Modified header's moment, in nanoseconds since the epoch;
    0 where there is none or it does not read."""
    try:
        moment = datetime.strptime(header.strip(), "%a, %d %b %Y %H:%M:%S GMT")
    except ValueError:
        return 0
    return int(moment.replace(tzinfo=UTC).timestamp()) * 10**9
