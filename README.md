# meridian-ecb

The European Central Bank's public reference data for
[Open Meridian](https://open-meridian.com): an Open Meridian plugin that puts
the ECB's
[euro foreign exchange reference rates](https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html)
into a deployment's lake, each TARGET business day's rate for about thirty
currencies against the euro, each rate the price of the euro's cash
instrument in the other currency, as the ECB quotes it; and the
[euro short-term rate](https://www.ecb.europa.eu/stats/financial_markets_and_interest_rates/euro_short-term_rate/html/index.en.html)
(€STR), its compounded averages and its compounded index, as rates. It
reads the ECB's Data Portal (SDMX), and holds the `data` role, a data
plugin. This is release 0.2.0, not released yet. How to set it up and use it is in
[docs/](docs/README.md); how a plugin like it is built is documented at
[open-meridian.dev](https://open-meridian.dev).

It is built on the SDK it pins, `open-meridian==0.32.1`, which declares
contract v27. It is stages 0 and 1 of the ECB's data plugin (meridian-design
`spec/a-public-rates-and-filings-data-plugin.md`, §8): the reference rates
as prices (stage 0), and €STR on contract v27's rates slice (stage 1).

## What it records

- **One dataset, `<instance>:ecb_fx`:** prices, pushed when each day's rates
  appear and pulled for any past day the lake wants; daily; history from
  1999; Frankfurt's day, ending at midnight; TARGET's calendar; no venue;
  kept, with the ECB cited.
- **Each rate as the ECB quotes it.** Every currency is quoted per euro, so
  USD 1.1225 is the price of the euro's cash instrument, in dollars. Nothing
  is inverted: a reader wanting the other way inverts it, and says so.
- **A close for its business date.** The rate's day is the business date, a
  plain date; the price's kind is `close`, the day's one reference rate.
  Its published time is when the portal says the rates changed, stated only
  for a rate read on its own day; a rate read later states none rather than
  a wrong one.
- **Exact.** Every rate is made a decimal from the text the portal wrote.
- **A second dataset, `<instance>:ecb_estr`:** rates (`meridian.v1.Rate`),
  pushed when the ECB publishes them at 08:00 CET the next TARGET business
  day, the history from 1 October 2019 backfilled once, any past day pulled
  when the lake wants it; Frankfurt's day; TARGET's calendar; kept, with the
  ECB cited. Seven a day, each about the platform's seeded record for it
  (`ecb:ESTR`, the five `ecb:ESTR … compounded average` records,
  `ecb:ESTR compounded index`), resolved by the seed's symbol at the ECB:
  €STR a fixing with its volume, transactions and 25th and 75th
  percentiles, each average an average, both in per cent on actual/360,
  simple; the index an index level, based 1 October 2019 = 100. A revision
  is the same row's next version, with its later published time.
- **Every currency resolved** to the deployment's cash instrument by its
  ISO 4217 code, as of the moment it is asked, a miss reported with why.
  The plugin mints no currency: core answers a code the deployment does not
  hold with the platform master's currency, pulled. A day with no rate is
  no rate, never a zero.
- **TARGET's calendar read** from the deployment: the next rates expected,
  and the days the ECB publishes nothing on, declined without a request.
- **Every answer kept** as received, from the first day, in the storage the
  deployment grants, and named by each row it was first read into.

Its pages, under Manage alone, are the data role's, the same on every data
plugin, and show how it reaches the ECB and what it serves, never a rate:
**Connection** (`read_connection`, "No key needed", "Does not stream", and
its Sources) and **Datasets** (`read_datasets`, saying whether a deployment
admin has licensed each dataset, with its Lag and Records), each the same
through the deployment's MCP. The data role's figures are on its Summary.

## Checking it

    make ci-local                                  # lint, tests, plugin check, image, e2e: the pre-push gate
    make preview SHOTS=<dir>                       # each page in a browser with the kit, at 375, 582 and 1280 px

`make e2e` runs it on core's plugin harness (core v27) beside a reading
plugin: the ECB's portal unreachable at first, then sample data reading the
committed answer's last ten days, the rates read back in the right
instruments, a past day wanted and recorded, a weekend day and a currency it
never prices declined, both tools answering what the pages show, and a new
container recording nothing twice and reading its licence on start.

**The data suite.** `tests/test_suite.py` runs the SDK's suite on the
plugin's own conversion, and it passes: stage 0's cases are presented,
`reads-a-calendar` and its datasets' licences among them, and the rates
slice's `a-rate-fixing`, `a-same-day-revision` and `an-index-level` on €STR;
every other case is about a kind of data the ECB never states -- a day's
open, high, low and volume, a crypto asset, a venue, a security another
source named, trades, quotes, settlement dates, outcomes, a stream, a curve
-- and is not presented, with why, as the suite lets it; the feed delay
waits for contract v28 (ruling 518).

## The terms, summarised

Not legal advice; read the ECB's own words before relying on them.

- **Free use, the ECB cited.** The ECB's website allows free use of its
  information, reproduced accurately with the ECB cited as the source, a
  change to it stated
  ([copyright and disclaimer](https://www.ecb.europa.eu/home/disclaimer/html/index.en.html)).
  So the dataset's default licence is kept, with derived use and display,
  no limit on retention, and not one person's terms (`personal_use` false);
  the attribution is shown on the Datasets page. A deployment's licence on
  its Data sources page confirms or replaces it.
- **For information purposes only.** The ECB publishes the reference rates
  for information and discourages using them for transactions.
- **No endorsement.** This project is not affiliated with or endorsed by the
  European Central Bank.

## Licence

Apache-2.0 (LICENSE, NOTICE). The ECB's answers under `src/ecb/responses/`
are its reference rates as received on 2026-10-19 and its €STR series as
received on 2026-10-23.
