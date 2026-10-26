# Changelog

## 0.3.0

On open-meridian 0.33.1, contract v28 (plugin-common-v28), on core v28's
harness.

- **The feed delay, reported** (ruling 518, required again from contract
  v28): each rate and price recorded unasked or for a standing want has its
  age at the edge recorded from its published time (`roles.Latency` on the
  SDK's `Wants`), reported every 10 seconds (`ReportLatency`);
  `reports-its-feed-delay` is presented on the current rates read.
- **The suite's v28 cases** (ruling 602): option chains, filings, holdings,
  corporate actions and ratings not presented, kinds the ECB never
  publishes; the quality cases, about quotes, too.
- **`meridian plugin migrate`** (to_0_33_0, to_0_33_1): e2e/reader.py's
  SubjectRefs are `meridian.SubjectRef` (ruling 599), and convert.py's.
- **The pins:** open-meridian 0.33.1 and plugin-python:0.33.1 by tag and
  digest; core v28's runtime and harness at `8def82a` (chart 0.1.313) by
  digest; `meridian` 0.1.52 in check.yaml (was 0.1.51).
- The README's "not released yet" is gone.

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
