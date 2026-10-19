"""The two pages under Manage, and their read tools: what each shows, to
whom, and that a tool answers what its page shows."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from meridian.testing import PageClient

from ecb import page as page_module
from ecb.page import CONNECTION, DATASETS, figures, hold, pages

from conftest import CODES, feed, want


@pytest.fixture
def client(tmp_path: Path) -> PageClient:
    work = feed(tmp_path)

    async def run() -> None:
        await work.check()
        await work.on_want(want("w-0925", ["LCL-EUR"], day="2026-09-25"))
        await work.on_want(want("w-standing", ["LCL-EUR"], standing=True))

    asyncio.run(run())
    hold(work)
    return PageClient(pages)


def test_each_page_is_managed_alone(client: PageClient) -> None:
    served = {(r.page.path, r.level): r.response.status for r in client.every_page()}
    assert served == {
        (CONNECTION, "admin"): 200,
        (CONNECTION, "write"): 403,
        (CONNECTION, "read"): 403,
        (DATASETS, "admin"): 200,
        (DATASETS, "write"): 403,
        (DATASETS, "read"): 403,
    }
    # No rate on any page: the ECB's figures are the reading roles' to show.
    client.assert_no_account_data("1.1225", "177.63", "0.84")


def test_connection_says_how_the_ecb_is_reached(client: PageClient) -> None:
    text = client.get(CONNECTION, "admin").text
    # The data role's sections, in its order, then the ECB's Sources.
    assert text.index("<h2>Key</h2>") < text.index("<h2>Limits and use</h2>")
    assert text.index("<h2>Stream</h2>") < text.index("<h2>Sources</h2>")
    assert 'state="ok"' in text and "Sample data" in text
    assert "No key needed" in text and "Does not stream" in text
    assert "Mon 19 Oct" in text  # the latest day published
    assert "Tue 20 Oct" in text  # the next one expected, by TARGET's calendar
    assert "TARGET closing days, version 1" in text
    assert 'href="/.meridian/ui/0.12.0/meridian.css"' in text


def test_datasets_lists_the_dataset_and_every_currency(client: PageClient) -> None:
    text = client.get(DATASETS, "admin").text
    assert text.index("<h2>Served</h2>") < text.index("<h2>Wants</h2>")
    assert text.index('<th class="wide-only">Lag</th>') < text.index("<h2>Records</h2>")
    assert "ecb:ecb_fx" in text and "cite the ECB" in text
    assert "Not licensed yet" in text
    assert text.count("<tr data-code=") == len(CODES) + 1
    assert "<om-pager>" in text and "Kept current" in text
    assert "15 h 56 m median" in text
    assert "Source: European Central Bank" in text and "cite the ECB" in text


def test_the_tools_answer_what_the_pages_show(client: PageClient) -> None:
    names = {t.name for t in pages.tools}
    assert names == {"read_connection", "read_datasets"}
    connection = client.call_tool("read_connection")
    assert connection.outcome == "unchanged", connection.json
    data = connection.data
    assert data["latest_day"] == "2026-10-19" and data["first_day"] == "2026-10-09"
    assert data["mode"] == "Sample data" and data["credentials"] == []
    assert data["sessions"] is None and data["next_release"] == "2026-10-20"
    assert data["published_at"] == "2026-10-19T13:56:57+00:00"
    [source] = data["sources"]
    assert source["dataset"] == "ecb:ecb_fx" and source["next_expected"] == "2026-10-20"
    datasets = client.call_tool("read_datasets")
    assert datasets.outcome == "unchanged"
    read = datasets.data
    (served,) = read["served"]
    assert served["dataset"] == "ecb:ecb_fx" and served["arrives"] == "push, pull"
    assert served["recorded"] >= 203 and served["licensed"] is False
    codes = [r["code"] for r in read["records"]]
    assert codes[0] == "EUR" and sorted(codes[1:]) == sorted(CODES)
    usd = next(r for r in read["records"] if r["code"] == "USD")
    assert usd["price_of"] == "EUR in USD" and usd["name"] == "US dollar"
    page = client.get(DATASETS, "admin").text
    assert all(r["instrument_id"] in page for r in read["records"])
    assert read["wants"][0]["want_id"] == "w-standing"
    assert read["wants"][0]["state"] == "Kept current"
    [lag] = read["lag"]
    assert lag["rates"] == len(CODES) and lag["median_seconds"] == 15 * 3600 + 56 * 60 + 57


def test_before_the_first_check() -> None:
    page_module._held.clear()
    text = PageClient(pages).get(CONNECTION, "admin").text
    assert "Checking the ECB" in text
    empty = PageClient(pages).get(DATASETS, "admin").text
    assert "No rates read yet" in empty


def test_the_ecb_not_reached(tmp_path: Path) -> None:
    work = feed(tmp_path)
    work.status.error = "https://data-api.ecb.europa.eu/service/data/EXR: ConnectionRefusedError"
    hold(work)
    text = PageClient(pages).get(CONNECTION, "admin").text
    assert 'state="error"' in text and "Not answering" in text
    assert "ConnectionRefusedError" in text


def test_the_currencies_are_searched(client: PageClient) -> None:
    text = client.get(DATASETS, "admin", q="krona").text
    assert 'type="search"' in text and 'value="krona"' in text
    found = {c for c in CODES if f'data-code="{c}"' in text}
    assert found == {"ISK", "SEK"}
    assert f"2 of {len(CODES) + 1}" in text
    nothing = client.get(DATASETS, "admin", q="drachma").text
    assert "No currency matches" in nothing
    # The tool answers every currency, whatever a browser searched.
    assert len(client.call_tool("read_datasets").data["records"]) == len(CODES) + 1


def test_a_licensed_dataset_is_said_so(client: PageClient) -> None:
    page_module._held["feed"].wants.licensed = frozenset({"ecb:ecb_fx"})
    (served,) = client.call_tool("read_datasets").data["served"]
    assert served["licensed"] is True


def test_the_figures_are_the_data_roles_in_its_order(client: PageClient) -> None:
    work = page_module._held["feed"]
    said = figures(work.status, work)
    assert [f.label for f in said] == [
        "Connection",
        "Entitled at the vendor",
        "Stream",
        "Last recorded",
    ]
    assert said[0].value == "Sample data" and said[2].value == "Does not stream"
