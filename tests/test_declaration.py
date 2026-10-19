"""The catalogue, from code, as the deployment approves it."""

from __future__ import annotations

from meridian.plugin.v1 import operations_pb2 as ops

from ecb.declaration import DECLARATION
from ecb.declared import ECB_FX_DATASET, TARGET_CALENDAR


def test_one_daily_dataset_of_prices() -> None:
    assert [d.key for d in DECLARATION.catalogue] == ["ecb_fx"]
    assert list(ECB_FX_DATASET.data_types) == ["meridian.v1.Price"]
    modes = [ops.ObservationMode.Name(m) for m in ECB_FX_DATASET.modes]
    assert modes == ["OBSERVATION_MODE_PUSH", "OBSERVATION_MODE_PULL"]
    assert ECB_FX_DATASET.day_time_zone == "Europe/Berlin"
    assert ECB_FX_DATASET.day_end_minute == 0
    assert ECB_FX_DATASET.cadence == 86_400 and ECB_FX_DATASET.history == 10_100
    assert ECB_FX_DATASET.calendar_id == TARGET_CALENDAR
    assert not ECB_FX_DATASET.venue_id and not ECB_FX_DATASET.aggregator


def test_the_ecbs_terms_are_not_one_persons() -> None:
    licence = ECB_FX_DATASET.licence_default
    assert licence is not None
    assert licence.kept and licence.derived_use and licence.display
    assert not licence.personal_use and licence.retention_days == 0


def test_the_answers_are_kept_in_storage() -> None:
    assert DECLARATION.storage is not None
    assert [k.name for k in DECLARATION.storage.kinds] == ["responses"]
