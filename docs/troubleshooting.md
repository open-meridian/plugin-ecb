# Troubleshooting

## Connection

| What you see | What it means | What to do |
|---|---|---|
| **Not answering** | No check has reached the ECB's portal: no network, a proxy, or the portal down | Check the deployment's outbound access to data-api.ecb.europa.eu; the plugin tries again every hour |
| **Answering**, with a warning | An earlier check worked; the last did not | Nothing, usually: the next check runs within the hour. The detail says what failed |
| Sources: **calendar not read** | The deployment could not pull TARGET's calendar from the platform | The plugin assumes Monday to Friday; check the deployment reaches the platform |

## Rates and instruments

| What you see | What it means | What to do |
|---|---|---|
| **N currencies not resolved** | A currency's ISO 4217 code found no cash instrument, or two | Complete or merge the instrument at the Instruments page; the next check records its rates |
| No rate at all, **EUR** not resolved | The euro's own cash instrument is missing: every rate is its price | Complete the euro's instrument at the Instruments page |
| A rate the plugin could not read | The portal stated a value that is not a number | It is not recorded; the Datasets page lists it |

## Wants and licences

| What you see | What it means | What to do |
|---|---|---|
| A day declined, *source silent* | A weekend, a TARGET closing day, or a day not published yet | Wait for the next TARGET business day's rates, around 16:00 CET |
| A subject declined, *not covered* | The ECB prices only the euro: a rate in francs is the price of the euro | Read the euro's price in that currency, and invert it in the reader |
| Datasets: **Not licensed yet** | No deployment admin has licensed the dataset | Ask a deployment admin to license it on Data sources; the page says so within a minute |
