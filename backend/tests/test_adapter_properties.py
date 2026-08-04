import json
from typing import Callable, Tuple, Type

import pytest
from hypothesis import given
from hypothesis import settings as hypothesis_settings
from hypothesis import strategies as st

from app.ingestion import brokeros, freightflow, hauldesk
from tests.test_brokeros_ingestion import make_sync as make_brokeros_sync
from tests.test_freightflow_ingestion import make_sync as make_freightflow_sync
from tests.test_hauldesk_ingestion import make_sync as make_hauldesk_sync

json_scalars = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(max_size=32),
)
json_values = st.recursive(
    json_scalars,
    lambda children: st.one_of(
        st.lists(children, max_size=4),
        st.dictionaries(st.text(max_size=16), children, max_size=4),
    ),
    max_leaves=20,
)
PROPERTY_SETTINGS = hypothesis_settings(max_examples=50, deadline=None)


PARSER_CASES: Tuple[Tuple[Callable[[bytes], object], Type[Exception]], ...] = (
    (freightflow._parse_payload, freightflow.InvalidFreightFlowPayloadError),
    (hauldesk._parse_payload, hauldesk.InvalidHaulDeskPayloadError),
    (brokeros._parse_payload, brokeros.InvalidBrokerOSPayloadError),
)

REFERENCE_CASES = (
    (
        freightflow._parse_payload,
        make_freightflow_sync("2026-07-06T06:00:00-05:00"),
        freightflow.InvalidFreightFlowPayloadError,
    ),
    (hauldesk._parse_payload, make_hauldesk_sync(), hauldesk.InvalidHaulDeskPayloadError),
    (brokeros._parse_payload, make_brokeros_sync(), brokeros.InvalidBrokerOSPayloadError),
)


@pytest.mark.parametrize(("parse", "error"), PARSER_CASES)
@PROPERTY_SETTINGS
@given(value=json_values)
def test_adapters_reject_or_normalize_arbitrary_json(parse, error, value) -> None:
    raw_contents = json.dumps(value, allow_nan=False).encode()

    try:
        parse(raw_contents)
    except error:
        return

    # A parser may accept an input, but it must never leak an implementation error.
    assert isinstance(value, dict)


@pytest.mark.parametrize(
    "parse,payload",
    [
        (freightflow._parse_payload, make_freightflow_sync("2026-07-06T06:00:00-05:00")),
        (hauldesk._parse_payload, make_hauldesk_sync()),
        (brokeros._parse_payload, make_brokeros_sync()),
    ],
)
def test_reference_payloads_are_accepted(parse, payload) -> None:
    parsed_payload, sync = parse(json.dumps(payload).encode())

    assert parsed_payload == payload
    assert sync is not None


@pytest.mark.parametrize(("parse", "payload", "error"), REFERENCE_CASES)
@PROPERTY_SETTINGS
@given(extra_key=st.text(min_size=1, max_size=24))
def test_adapters_reject_arbitrary_unknown_top_level_fields(
    parse, payload, error, extra_key
) -> None:
    if extra_key in payload:
        return
    mutated = dict(payload)
    mutated[extra_key] = None

    try:
        parsed_payload, normalized = parse(json.dumps(mutated).encode())
    except error:
        return
    # Adapters with permissive source models may normalize away unknown fields.
    assert parsed_payload == mutated
    assert extra_key not in normalized.model_dump()


@pytest.mark.parametrize(
    ("parse", "payload", "collection", "error"),
    (
        (
            freightflow._parse_payload,
            make_freightflow_sync("2026-07-06T06:00:00-05:00"),
            "loads",
            freightflow.InvalidFreightFlowPayloadError,
        ),
        (
            hauldesk._parse_payload,
            make_hauldesk_sync(),
            "loads",
            hauldesk.InvalidHaulDeskPayloadError,
        ),
        (
            brokeros._parse_payload,
            make_brokeros_sync(),
            "records",
            brokeros.InvalidBrokerOSPayloadError,
        ),
    ),
)
@PROPERTY_SETTINGS
@given(extra_key=st.text(min_size=1, max_size=24))
def test_adapters_reject_arbitrary_unknown_record_fields(
    parse, payload, collection, error, extra_key
) -> None:
    record = payload[collection][0]
    if extra_key in record:
        return
    mutated = json.loads(json.dumps(payload))
    mutated[collection][0][extra_key] = None

    try:
        parsed_payload, normalized = parse(json.dumps(mutated).encode())
    except error:
        return
    normalized_records = getattr(normalized, collection)
    assert parsed_payload == mutated
    assert extra_key not in normalized_records[0].model_dump()
