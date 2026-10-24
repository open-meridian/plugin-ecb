"""The European Central Bank's euro foreign exchange reference rates and euro
short-term rate as an Open Meridian data plugin: stages 0 and 1 of the ECB's
data plugin (spec/a-public-rates-and-filings-data-plugin §8; one plugin per
publisher's feed, rulings 343 to 349). Each TARGET business day's reference
rates into the deployment's lake, each rate the price of the euro's cash
instrument in the other currency, as the ECB quotes it (`ecb_fx`); and each
day's €STR, its compounded averages and its compounded index as rates
(`ecb_estr`, contract v27's rates slice).

It connects to the sidecar it is launched beside with its catalogue, its
storage and its one setting (declaration.py), serves its two pages
(page.py), hears what the lake wants of it, and reads the ECB's current
reference rates and €STR at start and every hour, recording what it has not
recorded in this process (feed.py, estr_feed.py), and €STR's history once
(estr_feed.py). What the portal answered is kept in the storage the
deployment grants (raw.py), and moved past its window as the settings say.
It reads which of its datasets a deployment admin has licensed, on start and
every minute, and reports the data role's figures on its heartbeat. It holds
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
import signal

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
#: How long before a broken settings stream is asked again, in seconds.
RETRY_SECONDS = 5
#: How often storage is tended past its window, in seconds: daily.
TEND_SECONDS = 86_400
#: How often the datasets' licences are read again, and the figures set.
LICENCES_SECONDS = 60


async def watch_settings(
    plugin: meridian.Plugin, feed: Feed, held: list[Config], wake: asyncio.Event
) -> None:
    """Apply each delivery of the settings: sample data on or off, and the
    answers' window, tended at once. A stream that breaks -- the deployment
    not serving its configuration yet at a first start, or restarting -- is
    asked again after a pause, and delivers the settings whole."""
    while True:
        try:
            async for delivered in plugin.settings():
                config = config_from(delivered.values)
                held[0] = config
                feed.use(portal(config.sample_data))
                wake.set()
                await feed.raw.tend(plugin, config.window_days, config.past_window, feed.now())
        except Exception as broken:  # noqa: BLE001 - a broken stream, asked again
            log.warning("the settings were not delivered (%s); asking again", broken)
        await asyncio.sleep(RETRY_SECONDS)


async def check(feed: Feed, estr: EstrFeed, wake: asyncio.Event) -> None:
    """Read the current rates and €STR once the settings have come, then
    hourly, or at once when the settings change."""
    await wake.wait()
    while True:
        wake.clear()
        for status, work in ((feed.status, feed.check), (estr.status, estr.check)):
            try:
                await work()
            except meridian.MeridianError as failed:
                # The sidecar refused something a recording needed; say so
                # and keep the schedule rather than spin.
                status.error = f"the deployment refused a recording: {failed}"
                log.warning("this check stopped: %s", failed)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(wake.wait(), timeout=CHECK_SECONDS)


async def tend(plugin: meridian.Plugin, feed: Feed, held: list[Config]) -> None:
    while True:
        await asyncio.sleep(TEND_SECONDS)
        config = held[0]
        await feed.raw.tend(plugin, config.window_days, config.past_window, feed.now())


async def licences(plugin: meridian.Plugin, feed: Feed, estr: EstrFeed) -> None:
    """Its own declared datasets' licences (contract v20, W10.9), read on
    start and every minute, for the Datasets page; and the data role's
    figures, set for the next heartbeat."""
    while True:
        try:
            await feed.wants.read_licences()
        except meridian.MeridianError as failed:
            log.warning("the datasets' licences were not read this time: %s", failed)
        plugin.figures = figures(feed.status, feed, estr.status)
        await asyncio.sleep(LICENCES_SECONDS)


def _said(task: asyncio.Task[None]) -> None:
    """A task that ended on an error says so, rather than ending unseen."""
    if not task.cancelled() and task.exception() is not None:
        log.error("%s stopped", task.get_name(), exc_info=task.exception())


async def run() -> None:
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for stop in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(stop, stopped.set)

    # The version's whole declaration (declaration.py): its settings, its
    # pages with the levels each serves and their tools, and its documentation.
    # A version registers exactly what it was uploaded with (contract v25).
    async with await meridian.connect(declaration=DECLARATION) as plugin:
        log.info("registered as %s, roles %s", plugin.identity.instance_id, plugin.identity.roles)
        feed = Feed(plugin, portal(False), RawStore())
        estr = EstrFeed(feed)
        hold(feed, estr)
        held = [Config()]
        wake = asyncio.Event()
        server = pages.serve(plugin, PORT)
        log.info("serving its pages on 127.0.0.1:%d", PORT)
        tasks = [
            asyncio.create_task(
                plugin.receive(observations_wanted=feed.on_want, want_withdrawn=feed.on_withdrawn)
            ),
            asyncio.create_task(watch_settings(plugin, feed, held, wake)),
            asyncio.create_task(check(feed, estr, wake)),
            asyncio.create_task(tend(plugin, feed, held)),
            asyncio.create_task(licences(plugin, feed, estr)),
        ]
        for task in tasks:
            task.add_done_callback(_said)
        await stopped.wait()
        log.info("stopping")
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        server.shutdown()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    asyncio.run(run())


if __name__ == "__main__":
    main()
