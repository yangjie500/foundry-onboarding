import json
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from foundry_onboarding.contracts.generic_processor import GenericProcessorInput
from foundry_onboarding.contracts.generic_workflow import (
    EchoWorkflowPayload,
    GenericWorkflowInput,
    OnboardUserWorkflowPayload,
)
from foundry_onboarding.contracts.gitlab_user import GitLabUserInput, GitLabUserOutput

WORKFLOW_EVENTS_DIRECTORY = Path(__file__).parents[2] / "events" / "workflows"


def read_event(workflow: str, name: str) -> str:
    return (WORKFLOW_EVENTS_DIRECTORY / workflow / name).read_text(encoding="utf-8")


def test_valid_event_matches_workflow_contract() -> None:
    workflow_input = GenericWorkflowInput.model_validate_json(read_event("generic", "valid.json"))

    assert workflow_input.schema_version == "1.0"
    assert workflow_input.request_id == UUID("8e95a486-d4e4-4aee-afc7-327f029311ee")
    assert workflow_input.action == "echo"
    assert isinstance(workflow_input.payload, EchoWorkflowPayload)
    assert workflow_input.payload.message == "Hello from Step Functions"


def test_valid_onboarding_event_matches_workflow_contract() -> None:
    workflow_input = GenericWorkflowInput.model_validate_json(
        read_event("onboarding", "valid.json")
    )

    assert workflow_input.schema_version == "1.0"
    assert workflow_input.request_id == UUID("f084a40c-2d45-4bc9-96b2-d650bb746413")
    assert workflow_input.action == "onboard_user"
    assert isinstance(workflow_input.payload, OnboardUserWorkflowPayload)
    assert workflow_input.payload.username == "jane.smith"
    assert str(workflow_input.payload.email) == "jane.smith@example.com"
    assert workflow_input.payload.external is False


def test_malformed_workflow_event_is_rejected() -> None:
    with pytest.raises(ValidationError):
        GenericWorkflowInput.model_validate_json(read_event("generic", "malformed.json"))


def test_malformed_onboarding_event_is_rejected() -> None:
    with pytest.raises(ValidationError):
        GenericWorkflowInput.model_validate_json(read_event("onboarding", "malformed.json"))


def test_unsupported_workflow_action_is_rejected() -> None:
    with pytest.raises(ValidationError):
        GenericWorkflowInput.model_validate_json(read_event("generic", "unsupported-action.json"))


@pytest.mark.parametrize(
    ("action", "payload"),
    [
        (
            "echo",
            {
                "username": "jane.smith",
                "name": "Jane Smith",
                "email": "jane@example.com",
                "external": False,
            },
        ),
        ("onboard_user", {"message": "wrong payload"}),
    ],
)
def test_action_rejects_mismatched_payload(action: str, payload: dict[str, object]) -> None:
    event = json.loads(read_event("generic", "valid.json"))
    event["action"] = action
    event["payload"] = payload

    with pytest.raises(ValidationError):
        GenericWorkflowInput.model_validate(event)


def test_unknown_workflow_field_is_rejected() -> None:
    event = json.loads(read_event("generic", "valid.json"))
    event["unexpected"] = "value"

    with pytest.raises(ValidationError):
        GenericWorkflowInput.model_validate(event)


def test_workflow_input_transforms_to_processor_input() -> None:
    workflow_input = GenericWorkflowInput.model_validate_json(read_event("generic", "valid.json"))
    assert isinstance(workflow_input.payload, EchoWorkflowPayload)

    processor_input = GenericProcessorInput(
        schema_version=workflow_input.schema_version,
        request_id=workflow_input.request_id,
        message=workflow_input.payload.message,
    )

    assert processor_input.request_id == workflow_input.request_id
    assert processor_input.message == workflow_input.payload.message


def test_onboarding_input_transforms_to_gitlab_user_input() -> None:
    workflow_input = GenericWorkflowInput.model_validate_json(
        read_event("onboarding", "valid.json")
    )
    assert isinstance(workflow_input.payload, OnboardUserWorkflowPayload)

    gitlab_input = GitLabUserInput(
        schema_version=workflow_input.schema_version,
        request_id=workflow_input.request_id,
        username=workflow_input.payload.username,
        name=workflow_input.payload.name,
        email=workflow_input.payload.email,
        external=workflow_input.payload.external,
    )

    assert gitlab_input.request_id == workflow_input.request_id
    assert gitlab_input.username == "jane.smith"
    assert str(gitlab_input.email) == "jane.smith@example.com"


@pytest.mark.parametrize(
    ("fixture_name", "expected_status"),
    [("expected-created.json", "created"), ("expected-existing.json", "existing")],
)
def test_onboarding_output_fixture_matches_gitlab_contract(
    fixture_name: str,
    expected_status: str,
) -> None:
    output = GitLabUserOutput.model_validate_json(read_event("onboarding", fixture_name))

    assert output.status == expected_status
    assert output.request_id == UUID("f084a40c-2d45-4bc9-96b2-d650bb746413")
    assert output.result.id == 123
    assert output.result.username == "jane.smith"
