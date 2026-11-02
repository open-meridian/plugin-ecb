"""The European Central Bank's euro foreign exchange reference rates and euro
short-term rate as an Open Meridian data plugin: stages 0 and 1 of the ECB's
data plugin (spec/a-public-rates-and-filings-data-plugin §8; one plugin per
publisher's feed, rulings 343 to 349). Each TARGET business day's reference
rates into the deployment's lake, each rate the price of the euro's cash
instrument in the other currency, as the ECB quotes it (`ecb_fx`); and each
day's €STR, its compounded averages and its compounded index as rates
(`ecb_estr`, contract v27's rates slice).

It runs its data role class, `Lake` (feed.py's `Feed`, with €STR's work
beside it and its lifecycle here), with `meridian.run` on the sidecar it is
launched beside, declaring its catalogue, its storage and its one setting
(declaration.py); `meridian.run` delivers the settings, serves its two pages
(page.py), hands it what the lake wants of it, and sets the data role's
figures on each heartbeat. It reads the ECB's current reference rates and
€STR at start and every hour, recording what it has not recorded in this
process (feed.py, estr_feed.py), and €STR's history once (estr_feed.py).
What the portal answered is kept in the storage the deployment grants
(raw.py), and moved past its window as the settings say. It reads which of
its datasets a deployment admin has licensed, on start and every minute.
It holds
nothing else: a restart reads the portal again, and the lake answers what it
recorded before unchanged; it does not stream, so it has no restart's gap to
backfill beyond the ten days its current read reaches.

Everything it says to the deployment goes through the sidecar; everything it
reads comes from the ECB's public Data Portal, or with sample data from the
answer committed with it.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

import meridian

from .declaration import DECLARATION, PORT
from .estr_feed import EstrFeed
from .feed import Feed
from .page import figures, hold, pages
from .portal import portal
from .raw import RawStore
from .settings import Config, config_from

log = logging.getLogger("ecb")

#: How often the current rates are checked, in seconds: hourly.
CHECK_SECONDS = 3600
#: How often storage is tended past its window, in seconds: daily.
TEND_SECONDS = 86_400
#: How often the datasets' licences are read again.
LICENCES_SECONDS = 60


class Lake(Feed):
    """The data role's class with its lifecycle (open-meridian 0.35, rulings
    1004, 1005, 1009 to 1023), €STR's work beside it on the same wants:
    `meridian.run` delivers each settings to `on_settings` -- the first
    before anything is heard -- and starts `run`, again after a backoff
    should it fail."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.estr = EstrFeed(self)
        self.config = Config()
        self.wake = asyncio.Event()

    async def on_settings(self, delivered: Any) -> None:
        """Apply each delivery of the settings: sample data on or off, and the
        answers' window, tended at once."""
        config = config_from(delivered.values)
        self.config = config
        self.use(portal(config.sample_data))
        self.wake.set()
        await self.raw.tend(self.plugin, config.window_days, config.past_window, self.now())

    async def run(self) -> None:
        """The current rates and €STR checked, storage tended, the licences
        read, and the feed delay reported (contract v28, ReportLatency)."""
        await asyncio.gather(self._check(), self._tend(), self._licences(), self.latency.run())

    async def _check(self) -> None:
        """Read the current rates and €STR at once, then hourly, or at once
        when the settings change."""
        while True:
            self.wake.clear()
            for status, work in ((self.status, self.check), (self.estr.status, self.estr.check)):
                try:
                    await work()
                except meridian.MeridianError as failed:
                    # The sidecar refused something a recording needed; say so
                    # and keep the schedule rather than spin.
                    status.error = f"the deployment refused a recording: {failed}"
                    log.warning("this check stopped: %s", failed)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.wake.wait(), timeout=CHECK_SECONDS)

    async def _tend(self) -> None:
        while True:
            await asyncio.sleep(TEND_SECONDS)
            config = self.config
            await self.raw.tend(self.plugin, config.window_days, config.past_window, self.now())

    async def _licences(self) -> None:
        """Its own declared datasets' licences (contract v20, W10.9), read on
        start and every minute, for the Datasets page."""
        while True:
            try:
                await self.wants.read_licences()
            except meridian.MeridianError as failed:
                log.warning("the datasets' licences were not read this time: %s", failed)
            await asyncio.sleep(LICENCES_SECONDS)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    lake = Lake(portal(False), RawStore())
    hold(lake, lake.estr)
    # The version's whole declaration (declaration.py): its settings, its
    # pages with the levels each serves and their tools, and its
    # documentation. A version registers exactly what it was uploaded with
    # (contract v25).
    meridian.run(
        declaration=DECLARATION,
        roles=[lake],
        pages=pages,
        port=PORT,
        on_settings=lake.on_settings,
        figures=lambda: figures(lake.status, lake, lake.estr.status),
    )


if __name__ == "__main__":
    main()
