import pytest

from foundry_onboarding.handlers.common import safe_request_id

REQUEST_ID = "f084a40c-2d45-4bc9-96b2-d650bb746413"


@pytest.mark.parametrize(
    "event",
    [
        None,
        "not-an-event",
        [],
        {},
        {"request_id": None},
        {"request_id": 123},
        {"request_id": "not-a-uuid"},
        {"request_id": "malicious\nlog-entry"},
    ],
)
def test_safe_request_id_rejects_untrusted_values(event: object) -> None:
    assert safe_request_id(event) == "unknown"


def test_safe_request_id_returns_canonical_uuid() -> None:
    event = {"request_id": "F084A40C-2D45-4BC9-96B2-D650BB746413"}

    assert safe_request_id(event) == REQUEST_ID
