"""The ECB's answers kept as received, where each rate was first read, and
months moved past their window."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from ecb.portal import Fetched, path_for
from ecb.rates import Rate
from ecb.raw import RawStore, range_name

from conftest import AT, PUBLISHED_NS


def fetched(at: datetime) -> Fetched:
    path = path_for(date(2026, 10, 9), date(2026, 10, 19))
    return Fetched(path, 200, b"KEY,FREQ\n", at, last_modified="Mon, 19 Oct 2026 13:56:57 GMT")


def test_an_answer_kept_and_read_back(tmp_path: Path) -> None:
    store = RawStore(tmp_path)
    key = store.keep(fetched(AT))
    assert key == "responses/2026-10/20261019T163000000000Z-20261009-20261019.json.gz"
    kept = store.read(key)
    assert kept is not None and kept["body"] == "KEY,FREQ\n" and kept["status"] == 200
    assert kept["url"].startswith("https://data-api.ecb.europa.eu/service/data/EXR/D..EUR.SP00.A?")
    assert store.read("../outside.json.gz") is None
    assert range_name("/elsewhere") == "answer"


def test_a_rate_names_the_answer_it_was_first_read_from(tmp_path: Path) -> None:
    store = RawStore(tmp_path)
    one, two = store.keep(fetched(AT)), store.keep(fetched(AT + timedelta(hours=1)))
    rate = Rate("USD", date(2026, 10, 19), Decimal("1.1225"), "1.1225")
    first, noted = store.first(rate, one, PUBLISHED_NS)
    assert noted and first.key == one and first.published_ns == PUBLISHED_NS
    again, noted = store.first(rate, two, PUBLISHED_NS)
    assert not noted and again == first
    store.save_firsts()
    # A new process, the same storage: the same answer named.
    assert RawStore(tmp_path).first(rate, two, PUBLISHED_NS)[0] == first
    # A correction is a new value, noted afresh, read days later: no published time.
    corrected = Rate("USD", date(2026, 10, 16), Decimal("1.1301"), "1.1301")
    assert store.first(corrected, two, PUBLISHED_NS)[0].published_ns == 0


class Mover:
    def __init__(self) -> None:
        self.moved: list[tuple[str, str, int]] = []
        self.stored: list[Any] = []

    async def archive_unit(self, kind: str, unit: str, **span: int) -> None:
        self.moved.append(("archived", unit, span["record_count"]))

    async def delete_unit(self, kind: str, unit: str, **span: int) -> None:
        self.moved.append(("deleted", unit, span["record_count"]))


async def test_months_past_the_window_moved_as_the_setting_says(tmp_path: Path) -> None:
    store = RawStore(tmp_path)
    store.keep(fetched(AT - timedelta(days=400)))
    store.keep(fetched(AT - timedelta(days=399)))
    store.keep(fetched(AT))
    mover = Mover()
    done = await store.tend(mover, 365, "archived", AT)  # type: ignore[arg-type]
    assert done["archived"] == 1
    assert mover.moved == [("archived", "responses/2025-09", 2)]
    kept = await store.tend(mover, 365, "kept", AT)  # type: ignore[arg-type]
    assert kept["kept"] == 1
    assert mover.stored[0].record_count == 3


async def test_nothing_moved_without_granted_storage() -> None:
    store = RawStore(None)
    store.granted = False
    store.keep(fetched(datetime(2020, 1, 1, tzinfo=UTC)))
    mover = Mover()
    assert (await store.tend(mover, 1, "deleted", AT))["deleted"] == 0  # type: ignore[arg-type]
    assert mover.moved == []
