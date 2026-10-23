# Setup

## Launching it

The ECB's reference rates and €STR need no key and no account: the Data
Portal is public. Launch the plugin and approve its one role, `data` (a data
plugin). It reads the portal at once, and every hour after; on its first
start it also records €STR's history from October 2019, a few requests,
once.

Its settings, in the dashboard's Settings form:

- **Raw responses window** and **past the window** (the SDK's): how long the
  ECB's answers are kept in the plugin's storage, ten years by default, and
  whether they are then archived, kept or deleted.
- **Sample data**, on a deployment installed for development only: the
  ECB's reference rates recorded on 19 October 2026 and €STR recorded on 23
  October 2026, committed with the plugin, in place of the portal. For
  trying it offline.

## Its datasets

On the deployment's **Data sources** page (deployment admins), for each of
`<instance>:ecb_fx` (the reference rates, as prices) and
`<instance>:ecb_estr` (€STR, as rates):

1. **License it.** The catalogue's default is kept, with derived use and
   display, no limit on retention, and not one person's terms. The ECB asks
   to be cited as the source, and changes to its figures to be said; record
   that in your licence's attribution or note. Confirm the default, or set
   your own, with a note saying why.
2. **Entitle** each plugin that reads it, such as your reporting plugin, or
   a signal or pricing plugin reading €STR.
3. **Priority**, where another dataset also states the same values: put the
   one your valuation should read first.

## Your currencies' instruments

Each rate is about the euro's cash instrument, priced in another currency's,
each found by its ISO 4217 code. The Datasets tab shows each currency's
instrument, or why there is none (not found, or two records match). A
currency without one waits: its rates are recorded once it resolves, at the
next check. Until the euro itself resolves, no rate is recorded.

## €STR's records

Each €STR rate is about one of the platform's reference rate records:
`ecb:ESTR`, the five `ecb:ESTR … compounded average` records and
`ecb:ESTR compounded index`. Your deployment pulls each from the platform the
first time the plugin asks. The Datasets tab shows each record's instrument,
or that it is not held; one not held waits, reported missing, and €STR's
history is recorded once all seven are held.

## The calendar

Both datasets name the platform's "Euro (TARGET)" calendar. Your deployment
pulls it from the platform the first time the plugin reads it. If it cannot,
Connection says so and the plugin assumes Monday to Friday.
