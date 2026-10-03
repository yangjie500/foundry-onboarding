import json
from dataclasses import dataclass, field
from pathlib import Path

from foundry_onboarding.adapters.aws.step_functions import WorkflowStartStatus
from foundry_onboarding.contracts.sqs_onboarding import SqsOnboardingMessage
from foundry_onboarding.services.workflow_ingress import start_onboarding_workflow

EVENT_PATH = Path(__file__).parents[3] / "events" / "sqs" / "onboarding" / "valid.json"
STATE_MACHINE_ARN = "arn:aws:states:us-east-1:111122223333:stateMachine:foundry-dev-onboarding"
REQUEST_ID = "f084a40c-2d45-4bc9-96b2-d650bb746413"


@dataclass
class FakeWorkflowStarter:
    status: WorkflowStartStatus = "started"
    calls: list[dict[str, str]] = field(default_factory=list)

    def start_workflow(self, **kwargs: str) -> WorkflowStartStatus:
        self.calls.append(kwargs)
        return self.status


def _message() -> SqsOnboardingMessage:
    return SqsOnboardingMessage.model_validate_json(EVENT_PATH.read_text(encoding="utf-8"))


def test_starts_workflow_with_deterministic_name_and_internal_contract() -> None:
    starter = FakeWorkflowStarter()

    status = start_onboarding_workflow(_message(), STATE_MACHINE_ARN, starter)

    assert status == "started"
    assert len(starter.calls) == 1
    call = starter.calls[0]
    assert call["state_machine_arn"] == STATE_MACHINE_ARN
    assert call["execution_name"] == REQUEST_ID
    assert json.loads(call["workflow_input"]) == {
        "schema_version": "1.0",
        "request_id": REQUEST_ID,
        "action": "onboard_user",
        "payload": {
            "username": "jane.smith",
            "name": "Jane Smith",
            "email": "jane.smith@example.com",
            "external": False,
        },
    }


def test_preserves_duplicate_status() -> None:
    starter = FakeWorkflowStarter(status="duplicate")

    status = start_onboarding_workflow(_message(), STATE_MACHINE_ARN, starter)

    assert status == "duplicate"
