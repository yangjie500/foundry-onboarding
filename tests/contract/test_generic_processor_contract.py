import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from foundry_onboarding.contracts.generic_processor import (
    EchoResult,
    GenericProcessorInput,
    GenericProcessorOutput,
)

EVENTS_DIRECTORY = Path(__file__).parents[2] / "events" / "functions" / "generic_processor"


def read_event(name: str) -> str:
    return (EVENTS_DIRECTORY / name).read_text(encoding="utf-8")


def test_valid_event_matches_processor_contract() -> None:
    processor_input = GenericProcessorInput.model_validate_json(read_event("valid.json"))

    assert processor_input.message == "Hello from Step Functions"


def test_malformed_processor_event_is_rejected() -> None:
    with pytest.raises(ValidationError):
        GenericProcessorInput.model_validate_json(read_event("malformed.json"))


def test_unknown_processor_field_is_rejected() -> None:
    event = json.loads(read_event("valid.json"))
    event["unexpected"] = "value"

    with pytest.raises(ValidationError):
        GenericProcessorInput.model_validate(event)


def test_expected_output_matches_processor_contract() -> None:
    output = GenericProcessorOutput.model_validate_json(read_event("expected-output.json"))

    assert output.status == "succeeded"
    assert output.result.message == "Hello from Step Functions"
    assert output.result.example_variable == "hello-from-dev-parameter-store"
    assert output.result.example_secret_loaded is True


def test_processor_output_preserves_request_identity() -> None:
    processor_input = GenericProcessorInput.model_validate_json(read_event("valid.json"))
    output = GenericProcessorOutput(
        schema_version=processor_input.schema_version,
        request_id=processor_input.request_id,
        status="succeeded",
        result=EchoResult(
            message=processor_input.message,
            example_variable="hello-from-dev-parameter-store",
            example_secret_loaded=True,
        ),
    )

    assert output.request_id == processor_input.request_id


def test_processor_output_round_trips_through_json() -> None:
    output = GenericProcessorOutput.model_validate_json(read_event("expected-output.json"))

    decoded = GenericProcessorOutput.model_validate_json(output.model_dump_json())

    assert decoded == output
