# Overview

The European Central Bank publishes its euro foreign exchange reference rates
every TARGET business day: one rate for each of about thirty currencies
against the euro. This plugin reads them from the ECB's Data Portal and puts
them into your deployment's lake, where a reporting plugin values your
positions in another currency.

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

## When rates arrive

The ECB sets its reference rates at a daily concertation between central
banks around 14:10 CET and publishes them around 16:00 CET, on every TARGET
business day. The plugin checks every hour and records a day's rates when
they appear. A rate belongs to its day, Frankfurt time, and its published
time is when the ECB's portal says the rates changed.

The plugin reads the euro's settlement calendar (TARGET's closing days) that
your deployment holds, so it knows which day the next rates are due and
which days the ECB publishes nothing on.

Asked for an older day, the plugin reads it from the portal and records it.
Asked for a weekend, a TARGET closing day or a day not published yet, it
says the source has not stated it.

## What it does not do

- It shows no rate on its own pages: rates are read by the plugins that
  value your book.
- It never inverts or crosses a rate, and never fills a closing day with a
  number.
- It records only the reference rates for now. The euro short-term rate
  (€STR) comes in a later version, once the lake holds interest rates.
