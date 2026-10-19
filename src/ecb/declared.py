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
- the licence the ECB's terms suggest: kept, derived use and display, with
  no limit on retention, and not one person's terms (`personal_use` false).
  The ECB asks to be cited as the source, and a change to its figures to be
  said: the contract's licence has no attribution field until the rates
  slice (the spec's item 4), so the attribution is stated in docs/terms.md
  and on the Datasets page. A deployment's licence confirms or replaces the
  default on the Data sources page; the plugin says nothing of whether a
  deployment meets anyone's terms.

**Storage:** the portal's answers (raw.py), archivable, ten years by default.
"""

from __future__ import annotations

from meridian import DatasetDeclaration, DatasetLicence
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
    licence_default=DatasetLicence(kept=True, derived_use=True, display=True),
    day_time_zone=DAY_TIME_ZONE,
    day_end_minute=DAY_END_MINUTE,
    calendar_id=TARGET_CALENDAR,
)

RESPONSES_KIND = RecordKind(RESPONSES, "Raw responses", window_days=DEFAULT_WINDOW_DAYS)
