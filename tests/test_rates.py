"""The ECB's reference rates, read from the real answer committed."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from ecb.rates import NotRates, last_modified_ns, parse

from conftest import CODES, PUBLISHED_NS, recorded


def test_the_recorded_answer() -> None:
    rates = parse(recorded())
    assert len(rates.rates) == 1624 and not rates.unread
    assert list(rates.currencies) == CODES
    assert rates.days[0] == date(2026, 8, 3) and rates.days[-1] == date(2026, 10, 19)
    assert len(rates.days) == 56
    assert rates.names["USD"] == "US dollar" and rates.names["AUD"] == "Australian dollar"


def test_every_rate_is_the_text_the_portal_wrote() -> None:
    rates = {(r.currency, r.day): r for r in parse(recorded()).rates}
    usd = rates[("USD", date(2026, 10, 19))]
    assert usd.value == Decimal("1.1225") and usd.text == "1.1225" and usd.status == "A"
    jpy = rates[("JPY", date(2026, 8, 3))]
    assert jpy.value == Decimal(jpy.text) and "." in jpy.text


def test_an_empty_answer_is_no_rate() -> None:
    assert parse("").rates == () and parse("\n").days == ()


def test_a_value_that_does_not_read_is_kept_as_not_read() -> None:
    header, first, *_ = recorded().splitlines()
    fields = first.split(",")
    fields[7] = "NaN"
    rates = parse("\n".join([header, ",".join(fields)]))
    assert rates.rates == () and rates.unread == ("AUD 2026-08-03: NaN",)


def test_an_answer_not_in_euro_or_units_is_refused() -> None:
    header, first, *_ = recorded().splitlines()
    with pytest.raises(NotRates, match="per euro"):
        parse("\n".join([header, first.replace(",AUD,EUR,", ",AUD,USD,")]))
    with pytest.raises(NotRates, match="columns"):
        parse("KEY,FREQ\nEXR,D\n")


def test_last_modified() -> None:
    assert last_modified_ns("Mon, 19 Oct 2026 13:56:57 GMT") == PUBLISHED_NS
    assert last_modified_ns("") == 0
