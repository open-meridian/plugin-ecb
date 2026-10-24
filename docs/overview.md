# Overview

The European Central Bank publishes two things this plugin reads from its
Data Portal and puts into your deployment's lake, each TARGET business day:

- its **euro foreign exchange reference rates**, one rate for each of about
  thirty currencies against the euro, where a reporting plugin values your
  positions in another currency (the dataset `ecb_fx`);
- the **euro short-term rate (€STR)**, the euro area's overnight benchmark,
  with its compounded averages over 1 week, 1, 3, 6 and 12 months and its
  compounded index, for discounting, carry and accruals (the dataset
  `ecb_estr`).

It is a data plugin: its first-use path, its two pages and its Summary figures are every data plugin's, described once on [Using a data plugin](https://open-meridian.dev/how-to/using-a-data-plugin/). These sections cover what is the ECB's own.

## What a rate means here

A rate is a price: the price of one currency's cash in another. The ECB
quotes every currency per euro, and the plugin records each rate exactly as
quoted.

- **USD 1.1225** on 19 October 2026 means one euro cost 1.1225 US dollars:
  the price of the euro, in dollars.
- **JPY 177.63** means one euro cost 177.63 yen: the price of the euro, in
  yen.

Nothing is turned the other way round. A plugin that needs euros per dollar
divides, and says it did.

## What €STR means here

€STR is an interest rate, not a price: 2.442 is 2.442 per cent a year. The
plugin records seven rates a day, each about one of the platform's reference
rate records:

- **€STR** itself as a *fixing*, with the day's total volume, number of
  transactions and its 25th and 75th percentiles, actual/360, simple;
- each **compounded average** as an *average*, in per cent, actual/360,
  simple, as the ECB annualises it;
- the **compounded index** as an *index level*, based 1 October 2019 = 100,
  with the convention of the rate it compounds: €STR's, actual/360,
  simple.

A rate's day is the day it is for: €STR of Thursday is computed from
Thursday's borrowing and published on Friday. A value the ECB marks
provisional is recorded as preliminary.

## When rates arrive

The ECB sets its reference rates at a daily concertation between central
banks around 14:10 CET and publishes them around 16:00 CET, on every TARGET
business day. The plugin checks every hour and records a day's rates when
they appear. A rate belongs to its day, Frankfurt time, and its published
time is when the ECB's portal says the rates changed.

The plugin reads the euro's settlement calendar (TARGET's closing days) that
your deployment holds, so it knows which day the next rates are due and
which days the ECB publishes nothing on.

The ECB publishes €STR at 08:00 CET on the next TARGET business day, and
revises it by 09:00 if it was out by more than 2 basis points. The plugin
checks every hour; a revised value is recorded as the next version of the
same rate, with its later published time, so both the first and the revised
value can be read.

On its first start the plugin also records €STR's history, back to
1 October 2019, once. The reference rates' history is read when it is asked
for.

Asked for an older day, the plugin reads it from the portal and records it.
Asked for a weekend, a TARGET closing day or a day not published yet, it
says the source has not stated it.

## What it does not do

- It shows no rate on its own pages: rates are read by the plugins that
  value your book.
- It never inverts or crosses a rate, and never fills a closing day with a
  number.
- It builds no curve from €STR and mints no record: €STR and its averages
  are the platform's records, which your deployment pulls when the plugin
  first asks for them.
