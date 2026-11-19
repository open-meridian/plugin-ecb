"""What this version declares beside its role, `data` (W8.1, W4.1; the
catalogue from contract v18), built from code and used twice: `__main__`
registers with it, and `meridian plugin upload` reads it from the built image
(pyproject.toml's `[tool.meridian] declaration`).

**The catalogue: one dataset, `ecb_fx`** (spec/a-public-rates-and-filings-
data-plugin §3, its key approved with the batch, 2026-10-14). The ECB's euro
foreign exchange reference rates, each day's pushed when the ECB publishes
it, and any past day pulled when the lake wants it:

- `vendor` the European Central Bank; no aggregator, since the plugin reads
  the ECB's portal itself;
- `data_types` prices alone: an FX rate is the price of a currency's cash
  instrument (convert.py);
- `modes` `push` (each day's rates recorded when they appear) and `pull` (a
  past day, on a want);
- `cadence` a day, in seconds: the ECB publishes each TARGET business day;
- `history` about 10,100 days, as the spec's table has it: the series begin
  on 4 January 1999;
- its day Frankfurt's, ending at midnight (`Europe/Berlin`, 0), and its
  calendar the euro's, TARGET's closing days (`calendar_id`, the platform's
  "Euro (TARGET)" calendar): the ECB publishes no rate on a TARGET closing
  day, and the plugin reads that calendar to know when the next rates are
  due (feed.py);
- no venue: the rates are the ECB's reference rates, no venue's;
- its terms and pricing (contract 30, ruling 1032) the ECB's, in plain
  words (`FX_TERMS`), and no licence declared: free, citing the ECB as the
  source and saying where a figure is changed, the rates for information
  only. A deployment's licence, set on the Data sources page, is the one
  enforced; the plugin says nothing of whether a deployment meets anyone's
  terms;
- a gap asked again (`gap_recovery` `backfill`, W10.14): the portal serves
  every past day.

**`ecb_estr`** (stage 1, the rates slice of contract v27). The euro
short-term rate, its compounded averages and its compounded index (estr.py),
each TARGET business day's pushed when the ECB publishes them, the history
backfilled once, and any past day pulled when the lake wants it:

- `vendor` the European Central Bank, no aggregator, as `ecb_fx`;
- `data_types` rates (`meridian.v1.Rate`), with the optional fields the ECB
  states for €STR itself: its volume, its number of transactions and its
  25th and 75th percentiles;
- `modes` `push` and `pull`; `cadence` a day;
- `history` about 2,600 days, as the spec's table has it: €STR from
  1 October 2019 (its compounded index from the same day, the averages as
  each first had a full period);
- its day Frankfurt's, ending at midnight, and its calendar TARGET's: the
  ECB computes €STR for each TARGET business day and publishes it at 08:00
  CET the next one;
- its terms the ECB's, in plain words (`ESTR_TERMS`), and a gap asked
  again (`backfill`), as `ecb_fx`'s.

**`ecb_yc`** (the product owner, item 128, 2026-11-19; its key proposed,
the product owner's to approve). The euro area's government bond yield
curves, AAA-rated and all ratings, each TARGET business day's pushed when
the ECB publishes them and any past day pulled when the lake wants it
(curve.py, curve_feed.py):

- `vendor` the European Central Bank, no aggregator: the ECB estimates the
  curves itself, from MTS's bond prices and Fitch's ratings, which its
  terms name;
- `data_types` rates (`meridian.v1.Rate`), each curve's spot rate as a zero
  rate and its par yield as a par yield at each tenor carried; never its
  forwards or Svensson parameters (items 130 and 131);
- `modes` `push` and `pull`; `cadence` a day;
- `history` about 8,100 days: the curves from 6 September 2004;
- its day Frankfurt's, ending at midnight, and its calendar TARGET's: the
  ECB estimates the curves for each TARGET business day and publishes them
  at noon CET the next one;
- its terms the ECB's, in plain words (`YC_TERMS`): the website's, then the
  curves' own page -- the sources it names, and that the curves are for
  information only, not for calculating price or yield quotations -- and a
  gap asked again (`backfill`): the portal serves every past day.

**Storage:** the portal's answers (raw.py), archivable, ten years by default.
"""

from __future__ import annotations

from datetime import date

from meridian import DatasetDeclaration
from meridian.declaration import RecordKind

from .convert import DAY_END_MINUTE, DAY_TIME_ZONE
from .raw import DEFAULT_WINDOW_DAYS, RESPONSES

#: The dataset's key: its rows name `<instance>:ecb_fx`.
ECB_FX = "ecb_fx"
VENDOR = "European Central Bank"
#: A day, in seconds.
CADENCE = 86_400
#: The series since 4 January 1999, in days, as the spec's catalogue states it.
HISTORY = 10_100
#: The ECB's terms, in plain words (contract 30, ruling 1032): its website's
#: copyright notice and the reference rates' own page, as docs/terms.md
#: summarises them.
ECB_TERMS = (
    "The ECB's public Data Portal: free, no key or account. The ECB allows free use of "
    "information from its website provided it is reproduced accurately and the ECB is cited "
    "as the source; a modification must be stated, and buyers of anything sold that "
    "includes it told that it is free from the ECB."
)
FX_TERMS = ECB_TERMS + (
    " The euro foreign exchange reference rates are published for information only: the ECB "
    "discourages their use for transactions and accepts no liability for decisions made in "
    "reliance on them."
)
ESTR_TERMS = ECB_TERMS + " The ECB does not charge for the euro short-term rate or license its use."
#: The yield curves' own page and technical notes, read on 2026-11-19.
YC_TERMS = ECB_TERMS + (
    " The euro area yield curves are the ECB's estimates from euro area central government "
    "bonds: bond and price information provided by MTS Markets, ratings by Fitch Ratings. "
    "They are published for public information only, not to be used for any other purpose, "
    "including calculating price or yield quotations, nor to identify trading opportunities "
    "or as a basis for advice on pricing financial assets; the ECB accepts no liability for "
    "errors, delays or action taken in reliance on them. This dataset carries each curve's "
    "spot rates and par yields; its forward rates and model parameters are not carried."
)
#: The platform's "Euro (TARGET)" currency calendar, read from the platform
#: on 2026-10-19: TARGET's closing days, which the ECB's Governing Council
#: set, on which it publishes no reference rate.
TARGET_CALENDAR = "CAL-01M4VF0F5ZRTY7AZ3B36ZVWN11"

ECB_FX_DATASET = DatasetDeclaration(
    key=ECB_FX,
    vendor=VENDOR,
    data_types=["meridian.v1.Price"],
    modes=["push", "pull"],
    cadence=CADENCE,
    history=HISTORY,
    terms_and_pricing=FX_TERMS,
    gap_recovery="backfill",
    day_time_zone=DAY_TIME_ZONE,
    day_end_minute=DAY_END_MINUTE,
    calendar_id=TARGET_CALENDAR,
)

#: The €STR dataset's key: its rows name `<instance>:ecb_estr`.
ECB_ESTR = "ecb_estr"
#: €STR's history, in days, as the spec's catalogue states it: from
#: October 2019, about 2,600 days.
ESTR_HISTORY = 2_600
#: The first day the ECB published €STR for.
ESTR_FROM = date(2019, 10, 1)

ECB_ESTR_DATASET = DatasetDeclaration(
    key=ECB_ESTR,
    vendor=VENDOR,
    data_types=[
        "meridian.v1.Rate",
        "meridian.v1.Rate.volume",
        "meridian.v1.Rate.transaction_count",
        "meridian.v1.Rate.percentiles",
    ],
    modes=["push", "pull"],
    cadence=CADENCE,
    history=ESTR_HISTORY,
    terms_and_pricing=ESTR_TERMS,
    gap_recovery="backfill",
    day_time_zone=DAY_TIME_ZONE,
    day_end_minute=DAY_END_MINUTE,
    calendar_id=TARGET_CALENDAR,
)

#: The yield curves' dataset key (proposed: the product owner approves a new
#: dataset name): its rows name `<instance>:ecb_yc`.
ECB_YC = "ecb_yc"
#: The curves' history, in days: from 6 September 2004, about 8,100.
YC_HISTORY = 8_100
#: The first day the ECB published the curves for.
YC_FROM = date(2004, 9, 6)

ECB_YC_DATASET = DatasetDeclaration(
    key=ECB_YC,
    vendor=VENDOR,
    data_types=["meridian.v1.Rate"],
    modes=["push", "pull"],
    cadence=CADENCE,
    history=YC_HISTORY,
    terms_and_pricing=YC_TERMS,
    gap_recovery="backfill",
    day_time_zone=DAY_TIME_ZONE,
    day_end_minute=DAY_END_MINUTE,
    calendar_id=TARGET_CALENDAR,
)

RESPONSES_KIND = RecordKind(RESPONSES, "Raw responses", window_days=DEFAULT_WINDOW_DAYS)
