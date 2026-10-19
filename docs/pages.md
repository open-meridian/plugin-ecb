# Pages

Both pages are the data role's, the same on every data plugin, under
**Manage**, for the plugin's admins. Neither shows a rate. Each is also a
read tool on the deployment's MCP, answering what the page shows, under the
same names on every data plugin.

## Connection (`read_connection`)

How the plugin reaches the ECB, and how the last check went:

- the head's status: answering, checking, not answering, or currencies not
  resolved;
- **Key:** the mode (Live or Sample data), "No key needed", what the ECB
  serves, and where it reads from;
- **Limits and use:** the limits it keeps (the ECB states none; one request
  at a time, at most one every two seconds, a check every hour), the
  requests made, the last check and error, and how many answers are kept;
- **Stream:** it does not stream;
- **Sources:** one line per source: its state, the last day it published,
  the next day expected by TARGET's calendar, and the calls made. A row's
  `…` opens how the calendar was read and the last error.

## Datasets (`read_datasets`)

What the plugin serves:

- **Served:** its one dataset as the deployment's catalogue lists it, with
  the terms it declares and whether a deployment admin has licensed it, and
  what it recorded and declined;
- **Wants:** the standing wants it keeps current, and the last wants it
  answered; **Subjects**;
- **Lag:** how long after the start of a rate's day the ECB published it,
  the median and the longest, and the attribution the ECB's terms ask for;
- **Records:** each currency the ECB rates, one line each: its code, the
  ECB's name for it, what its rate is the price of, and the deployment's
  instrument for it, or why there is none. A row's `…` opens its details.
