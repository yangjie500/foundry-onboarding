import json
import logging
from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

from foundry_onboarding.errors import InvalidInputError
from foundry_onboarding.handlers.generic_processor import handler
from foundry_onboarding.services.generic_processor import GenericProcessorParameters

EVENTS_DIRECTORY = Path(__file__).parents[3] / "events" / "functions" / "generic_processor"


@pytest.fixture(autouse=True)
def stub_parameter_store(monkeypatch: pytest.MonkeyPatch) -> None:
    parameters = GenericProcessorParameters(
        example_variable="hello-from-dev-parameter-store",
        example_secret="not-a-real-secret",
    )
    monkeypatch.setattr(
        "foundry_onboarding.handlers.generic_processor.load_generic_processor_parameters",
        lambda: parameters,
    )


def read_event(name: str) -> dict[str, object]:
    event = json.loads((EVENTS_DIRECTORY / name).read_text(encoding="utf-8"))

    assert isinstance(event, dict)

    return cast(dict[str, object], event)


def test_handler_returns_expected_output() -> None:
    event = read_event("valid.json")
    expected = read_event("expected-output.json")

    result = handler(event, object())

    assert result == expected


def test_handler_translates_validation_failure() -> None:
    event = read_event("malformed.json")

    with pytest.raises(InvalidInputError) as raised:
        handler(event, object())

    assert str(raised.value) == "Generic processor input is invalid"
    assert isinstance(raised.value.__cause__, ValidationError)


def test_invalid_input_error_has_stable_code() -> None:
    assert InvalidInputError.error_code == "INVALID_INPUT"


def test_handler_logs_request_metadata_without_payload(
    caplog: pytest.LogCaptureFixture,
) -> None:
    event = read_event("valid.json")

    with caplog.at_level(
        logging.INFO,
        logger="foundry_onboarding.handlers.generic_processor",
    ):
        handler(event, object())

    completion_records = [
        record
        for record in caplog.records
        if record.getMessage() == "Generic processor completed request"
    ]

    assert len(completion_records) == 1
    assert completion_records[0].__dict__["request_id"] == event["request_id"]
    assert "Hello from Step Functions" not in caplog.text
    assert "not-a-real-secret" not in caplog.text


def test_handler_logs_invalid_input_without_full_event(
    caplog: pytest.LogCaptureFixture,
) -> None:
    event = read_event("malformed.json")

    with (
        caplog.at_level(
            logging.WARNING,
            logger="foundry_onboarding.handlers.generic_processor",
        ),
        pytest.raises(InvalidInputError),
    ):
        handler(event, object())

    rejection_records = [
        record
        for record in caplog.records
        if record.getMessage() == "Generic processor rejected invalid input"
    ]

    assert len(rejection_records) == 1
    assert rejection_records[0].__dict__["validation_error_count"] == 2
    assert 'request_id": "not-a-uuid"' not in caplog.text
