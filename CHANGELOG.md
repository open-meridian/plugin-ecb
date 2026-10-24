# Changelog

## 0.2.0

Stage 1 of the ECB's data plugin, on open-meridian 0.32.3 (contract v27).

- **The euro short-term rate as rates**, a second dataset (`ecb_estr`), read
  from the ECB's Data Portal (the `EST` dataflow) and recorded through the
  SDK's rates helpers: €STR as a fixing with its volume, transactions and
  25th and 75th percentiles, its 1-week, 1-month, 3-month, 6-month and
  12-month compounded averages as averages (per cent, actual/360, simple),
  and its compounded index as an index level (1 October 2019 = 100, its
  convention €STR's: actual/360, simple). Each is
  about the platform's seeded `ecb:` record, resolved by its symbol at the
  ECB, never minted.
- **Pushed when published**, at 08:00 CET the next TARGET business day,
  with its published time; **a revision** by 09:00 recorded as the same
  row's next version; **the history** from 1 October 2019 backfilled once;
  **any past day** pulled on a want; every answer kept as received.
- **The pages and tools** list €STR beside the reference rates: a second
  source on Connection, a second dataset with its lag on Datasets, and the
  seven records with their instruments under Records.
- **The data suite's rates cases** presented on €STR (`a-rate-fixing`,
  `a-same-day-revision`, `an-index-level`); the curve cases, the stream's
  liveness and the lake query (about trades from v27) not presented, with
  why; the feed delay not presented until contract v28 (ruling 518).
- **The pins:** open-meridian 0.32.3 and its base image, core a5da59a's
  runtime and harness for the e2e, meridian 0.1.51 for the check. `ecb_fx`
  is unchanged.

## 0.1.0

The first version: stage 0 of the ECB's data plugin, on open-meridian 0.31.0
(contract v26).

- **The ECB's euro foreign exchange reference rates as prices**, one dataset
  (`ecb_fx`): each TARGET business day's rates pushed when the ECB publishes
  them, any past day pulled on a want, each rate the price of the euro's
  cash instrument in the other currency, never inverted.
- **TARGET's calendar read** for the next rates expected and the days the
  ECB publishes nothing on.
- **Raw answers kept from the first day**, in the storage the deployment
  grants.
- **The data role's pages**, Connection (with Sources) and Datasets (with Lag
  and Records), each a read tool on the deployment's MCP.
- **The data suite passes**, stage 0's cases presented.
