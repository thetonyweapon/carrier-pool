import json
from typing import Callable, Tuple, Type

import pytest
from hypothesis import given
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


PARSER_CASES: Tuple[Tuple[Callable[[bytes], object], Type[Exception]], ...] = (
    (freightflow._parse_payload, freightflow.InvalidFreightFlowPayloadError),
    (hauldesk._parse_payload, hauldesk.InvalidHaulDeskPayloadError),
    (brokeros._parse_payload, brokeros.InvalidBrokerOSPayloadError),
)


@pytest.mark.parametrize(("parse", "error"), PARSER_CASES)
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
