"""The catalogue, from code, as the deployment approves it."""

from __future__ import annotations

from meridian.plugin.v1 import operations_pb2 as ops

from ecb.declaration import DECLARATION
from ecb.declared import (
    ECB_ESTR_DATASET,
    ECB_FX_DATASET,
    ESTR_TERMS,
    FX_TERMS,
    TARGET_CALENDAR,
)


def test_two_daily_datasets_prices_and_rates() -> None:
    assert [d.key for d in DECLARATION.catalogue] == ["ecb_fx", "ecb_estr"]
    assert list(ECB_FX_DATASET.data_types) == ["meridian.v1.Price"]
    modes = [ops.ObservationMode.Name(m) for m in ECB_FX_DATASET.modes]
    assert modes == ["OBSERVATION_MODE_PUSH", "OBSERVATION_MODE_PULL"]
    assert ECB_FX_DATASET.day_time_zone == "Europe/Berlin"
    assert ECB_FX_DATASET.day_end_minute == 0
    assert ECB_FX_DATASET.cadence == 86_400 and ECB_FX_DATASET.history == 10_100
    assert ECB_FX_DATASET.calendar_id == TARGET_CALENDAR
    assert not ECB_FX_DATASET.venue_id and not ECB_FX_DATASET.aggregator
    assert list(ECB_ESTR_DATASET.data_types) == [
        "meridian.v1.Rate",
        "meridian.v1.Rate.volume",
        "meridian.v1.Rate.transaction_count",
        "meridian.v1.Rate.percentiles",
    ]
    assert list(ECB_ESTR_DATASET.modes) == list(ECB_FX_DATASET.modes)
    assert ECB_ESTR_DATASET.calendar_id == TARGET_CALENDAR
    assert ECB_ESTR_DATASET.history == 2_600


def test_the_ecbs_terms_in_words_and_a_gap_asked_again() -> None:
    # Contract 30 (ruling 1032): the ECB's terms described, no licence; the
    # portal serves every past day, so a gap is asked again (W10.14).
    assert ECB_FX_DATASET.terms_and_pricing == FX_TERMS
    assert ECB_ESTR_DATASET.terms_and_pricing == ESTR_TERMS
    for dataset in (ECB_FX_DATASET, ECB_ESTR_DATASET):
        said = dataset.terms_and_pricing
        assert "cited as the source" in said and len(said) <= 2000
        assert dataset.gap_recovery == "backfill" and not dataset.sessions_calendar_id
    assert "information only" in FX_TERMS and "does not charge" in ESTR_TERMS


def test_the_answers_are_kept_in_storage() -> None:
    assert DECLARATION.storage is not None
    assert [k.name for k in DECLARATION.storage.kinds] == ["responses"]
