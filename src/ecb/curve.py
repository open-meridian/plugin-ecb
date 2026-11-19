"""The euro area's government bond yield curves, read from the portal's
SDMX-CSV as it writes them: each curve's spot rates and par yields at the
tenors carried, and nothing else.

The ECB estimates a zero-coupon curve from euro area central government
bonds every TARGET business day (the Svensson model, bond prices from MTS,
ratings from Fitch) and derives its forward and par yield curves from it,
publishing them at noon CET the next TARGET business day, for two sets of
bonds: the AAA-rated, and all ratings (its yield-curve page and technical
notes). All come from one dataflow, `YC`, one series each, named by the
curve and the data type: `YC.B.U2.EUR.4F.<curve>.SV_C_YM.<type>_<tenor>`.

**What is read here**, and nothing else (the product owner, items 130 and
131, 2026-11-19):

- each curve's **spot rate** (`SR_`) as a **zero** rate and its **par
  yield** (`PY_`) as a **par yield**, both in per cent, continuously
  compounded as the ECB states them (its technical notes: the spot rate
  continuously compounded, the par yield "the continuously compounded par
  yield");
- at the **tenors carried** (`TENORS`): 3, 6 and 9 months and every whole
  year from 1 to 30 -- the curve's constant maturities a reader asks for.
  The ECB states every month from 3 months to 30 years; the months between
  are not read;
- never the instantaneous **forwards** (`IF_`), the **Svensson parameters**
  (`BETA0` to `BETA3`, `TAU1`, `TAU2`) or the **spreads** (`SRS_`): the
  contract has no kind for them, and the analytics engine derives a forward
  from the zero curve (item 131).

From each line: `KEY`, the series; `TIME_PERIOD`, the day the curve is
for, a plain date; `OBS_VALUE`, the value as the text the portal wrote;
`OBS_STATUS`, `A` normal or `P` provisional. Every number is made a Decimal
from its text, never a float; a yield may be negative (it was until 2022).
An empty value, or one that is not a number, is no value, never a zero:
kept as not read and shown on the Datasets page. An answer that does not
hold these columns, or names a series of another dataflow, is refused with
why, and nothing is recorded from it.

**Subjects.** Each curve is one record, its points rows (spec/a-public-rates-
and-filings-data-plugin §2: "a curve is one record; its points are rows"),
named by the ECB's own key for the curve -- `YC.B.U2.EUR.4F.G_N_A.SV_C_YM`
-- as a source-scoped `symbol` at `ecb`, as the platform names its other
ECB records. The plugin never mints one: a curve the deployment does not
hold is reported missing, and its rows wait (curve_feed.py).
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

#: The columns every answer must hold.
COLUMNS = ("KEY", "TIME_PERIOD", "OBS_VALUE")
#: The administrator: the symbol's source on each curve's record.
ADMINISTRATOR = "ecb"
#: The model every curve is estimated by: Svensson, continuous compounding,
#: yield error minimisation.
MODEL = "SV_C_YM"
#: The ECB's data types read, and the kind of rate each is recorded as.
KINDS = {"SR": "zero", "PY": "par_yield"}
#: The tenors carried: the constant maturities, 3, 6 and 9 months and every
#: whole year to 30, each as the ECB writes it in a series key.
TENORS: tuple[str, ...] = ("3M", "6M", "9M", *(f"{n}Y" for n in range(1, 31)))

_NUMBER = re.compile(r"^-?\d+(?:\.\d+)?$")
_KEY = re.compile(r"^YC\.B\.U2\.EUR\.4F\.([A-Z0-9_]+)\.([A-Z0-9_]+)\.([A-Z0-9_]+)$")


@dataclass(frozen=True)
class Curve:
    """One curve: the ECB's code for its set of bonds, its record's code
    (the ECB's key for the curve, its symbol at `ecb`), and its name."""

    instrument: str
    name: str

    @property
    def code(self) -> str:
        """The ECB's key for the curve: `YC.B.U2.EUR.4F.G_N_A.SV_C_YM`."""
        return f"YC.B.U2.EUR.4F.{self.instrument}.{MODEL}"

    def identifiers(self) -> tuple[tuple[str, str, str], ...]:
        return (("symbol", self.code, ADMINISTRATOR),)


#: The two, in the order the pages list them.
CURVES: tuple[Curve, ...] = (
    Curve("G_N_A", "Euro area AAA government bond yield curve (ECB)"),
    Curve("G_N_C", "Euro area all-ratings government bond yield curve (ECB)"),
)
BY_INSTRUMENT = {c.instrument: c for c in CURVES}


class NotCurve(ValueError):
    """The answer is not the yield curves this plugin can read."""


@dataclass(frozen=True)
class Value:
    """One value the portal stated: its text, as a Decimal, and its status."""

    text: str
    value: Decimal
    status: str = ""


@dataclass(frozen=True)
class Point:
    """One curve's spot rate or par yield at one tenor on one day."""

    curve: Curve
    kind: str
    tenor: str
    day: date
    value: Value

    @property
    def preliminary(self) -> bool:
        """The ECB marks a provisional value `P`."""
        return self.value.status == "P"

    @property
    def key(self) -> str:
        """The ECB's series key: `YC.B.U2.EUR.4F.G_N_A.SV_C_YM.PY_10Y`."""
        prefix = next(t for t, k in KINDS.items() if k == self.kind)
        return f"{self.curve.code}.{prefix}_{self.tenor}"

    @property
    def stated(self) -> str:
        """Everything the row states, as one text: a change to any of it is
        the row's next version (raw.py notes where each was first read)."""
        return f"{self.value.text}|{self.value.status}"


@dataclass(frozen=True)
class Points:
    """An answer's points, by curve, kind, tenor and day, and what in it was
    not a value."""

    points: tuple[Point, ...] = ()
    #: Each line naming a point carried with no value that reads, as
    #: `<series key> <day>: <text>`.
    unread: tuple[str, ...] = ()

    @property
    def days(self) -> tuple[date, ...]:
        return tuple(sorted({p.day for p in self.points}))

    def latest(self, curve: Curve) -> date | None:
        """The latest day the answer states a point of `curve` for."""
        days = [p.day for p in self.points if p.curve == curve]
        return max(days) if days else None


def carried(data_type: str) -> tuple[str, str] | None:
    """A data type's kind and tenor where it is one carried (`PY_10Y`:
    `par_yield`, `10Y`); None for any other -- a forward, a parameter, a
    spread, a month between the tenors carried."""
    prefix, _, tenor = data_type.partition("_")
    kind = KINDS.get(prefix)
    return (kind, tenor) if kind and tenor in TENORS else None


def parse(text: str) -> Points:
    """The points `text` holds, or NotCurve saying why it holds none."""
    if not text.strip():
        return Points()
    reader = csv.DictReader(io.StringIO(text))
    held = reader.fieldnames or []
    missing = [c for c in COLUMNS if c not in held]
    if missing:
        raise NotCurve(f"its columns lack {', '.join(missing)}: {held[:8]!r}")
    points: list[Point] = []
    unread: list[str] = []
    for line in reader:
        key = (line.get("KEY") or "").strip()
        found = _KEY.match(key)
        if found is None:
            raise NotCurve(f"a series is not one of the YC dataflow's: {key!r}")
        instrument, model, data_type = found.groups()
        curve = BY_INSTRUMENT.get(instrument)
        read = carried(data_type)
        if curve is None or model != MODEL or read is None:
            continue
        period = (line.get("TIME_PERIOD") or "").strip()
        try:
            day = date.fromisoformat(period)
        except ValueError as failed:
            raise NotCurve(f"{key}'s period is not a day: {period!r}") from failed
        text_value = (line.get("OBS_VALUE") or "").strip()
        if not _NUMBER.match(text_value):
            unread.append(f"{key} {period}: {text_value or 'empty'}")
            continue
        status = (line.get("OBS_STATUS") or "").strip()
        kind, tenor = read
        points.append(
            Point(curve, kind, tenor, day, Value(text_value, Decimal(text_value), status))
        )
    points.sort(key=lambda p: (p.day, CURVES.index(p.curve), p.kind, TENORS.index(p.tenor)))
    return Points(tuple(points), tuple(unread))
