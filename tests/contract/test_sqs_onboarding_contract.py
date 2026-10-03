import json
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from foundry_onboarding.contracts.generic_workflow import OnboardUserWorkflowPayload
from foundry_onboarding.contracts.sqs_onboarding import SqsOnboardingMessage

SQS_ONBOARDING_EVENTS_DIRECTORY = Path(__file__).parents[2] / "events" / "sqs" / "onboarding"


def read_event(name: str) -> str:
    return (SQS_ONBOARDING_EVENTS_DIRECTORY / name).read_text(encoding="utf-8")


def test_valid_message_matches_sqs_onboarding_contract() -> None:
    message = SqsOnboardingMessage.model_validate_json(read_event("valid.json"))

    assert message.schema_version == "1.0"
    assert message.request_id == UUID("f084a40c-2d45-4bc9-96b2-d650bb746413")
    assert message.action == "onboard_user"
    assert message.payload.username == "jane.smith"
    assert message.payload.name == "Jane Smith"
    assert str(message.payload.email) == "jane.smith@example.com"
    assert message.payload.external is False


def test_malformed_message_is_rejected() -> None:
    with pytest.raises(ValidationError):
        SqsOnboardingMessage.model_validate_json(read_event("malformed.json"))


def test_unknown_fields_are_rejected() -> None:
    event = json.loads(read_event("valid.json"))
    event["unexpected"] = "value"

    with pytest.raises(ValidationError):
        SqsOnboardingMessage.model_validate(event)


def test_unknown_payload_fields_are_rejected() -> None:
    event = json.loads(read_event("valid.json"))
    event["payload"]["access_token"] = "must-not-be-accepted"

    with pytest.raises(ValidationError):
        SqsOnboardingMessage.model_validate(event)


def test_non_onboarding_action_is_rejected() -> None:
    event = json.loads(read_event("valid.json"))
    event["action"] = "echo"

    with pytest.raises(ValidationError):
        SqsOnboardingMessage.model_validate(event)


def test_message_converts_to_internal_workflow_input() -> None:
    message = SqsOnboardingMessage.model_validate_json(read_event("valid.json"))

    workflow_input = message.to_workflow_input()

    assert workflow_input.schema_version == message.schema_version
    assert workflow_input.request_id == message.request_id
    assert workflow_input.action == "onboard_user"
    assert isinstance(workflow_input.payload, OnboardUserWorkflowPayload)
    assert workflow_input.payload.username == message.payload.username
    assert workflow_input.payload.name == message.payload.name
    assert workflow_input.payload.email == message.payload.email
    assert workflow_input.payload.external is message.payload.external
