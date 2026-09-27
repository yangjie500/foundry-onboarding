import json
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from foundry_onboarding.contracts.generic_processor import GenericProcessorInput
from foundry_onboarding.contracts.generic_workflow import GenericWorkflowInput

EVENTS_DIRECTORY = Path(__file__).parents[2] / "events" / "workflows" / "generic"


def read_event(name: str) -> str:
    return (EVENTS_DIRECTORY / name).read_text(encoding="utf-8")


def test_valid_event_matches_workflow_contract() -> None:
    workflow_input = GenericWorkflowInput.model_validate_json(read_event("valid.json"))

    assert workflow_input.schema_version == "1.0"
    assert workflow_input.request_id == UUID("8e95a486-d4e4-4aee-afc7-327f029311ee")
    assert workflow_input.action == "echo"
    assert workflow_input.payload.message == "Hello from Step Functions"


def test_malformed_workflow_event_is_rejected() -> None:
    with pytest.raises(ValidationError):
        GenericWorkflowInput.model_validate_json(read_event("malformed.json"))


def test_unsupported_workflow_action_is_rejected() -> None:
    with pytest.raises(ValidationError):
        GenericWorkflowInput.model_validate_json(read_event("unsupported-action.json"))


def test_unknown_workflow_field_is_rejected() -> None:
    event = json.loads(read_event("valid.json"))
    event["unexpected"] = "value"

    with pytest.raises(ValidationError):
        GenericWorkflowInput.model_validate(event)


def test_workflow_input_transforms_to_processor_input() -> None:
    workflow_input = GenericWorkflowInput.model_validate_json(read_event("valid.json"))

    processor_input = GenericProcessorInput(
        schema_version=workflow_input.schema_version,
        request_id=workflow_input.request_id,
        message=workflow_input.payload.message,
    )

    assert processor_input.request_id == workflow_input.request_id
    assert processor_input.message == workflow_input.payload.message
