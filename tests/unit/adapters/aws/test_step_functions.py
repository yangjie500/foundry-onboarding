from dataclasses import dataclass, field
from typing import Any

import boto3
import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

from foundry_onboarding.adapters.aws import step_functions
from foundry_onboarding.adapters.aws.step_functions import StepFunctions
from foundry_onboarding.errors import WorkflowStartError

STATE_MACHINE_ARN = "arn:aws:states:us-east-1:111122223333:stateMachine:foundry-dev-onboarding"
EXECUTION_NAME = "f084a40c-2d45-4bc9-96b2-d650bb746413"
WORKFLOW_INPUT = '{"schema_version":"1.0"}'


@dataclass
class FakeStepFunctionsClient:
    error: Exception | None = None
    calls: list[dict[str, str]] = field(default_factory=list)

    def start_execution(self, **kwargs: str) -> object:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return {"executionArn": "not-used"}


def _client_error(code: str, message: str = "sensitive AWS detail") -> ClientError:
    return ClientError(
        {"Error": {"Code": code, "Message": message}},
        "StartExecution",
    )


def test_starts_execution_with_exact_arguments() -> None:
    client = FakeStepFunctionsClient()
    adapter = StepFunctions(client)

    status = adapter.start_workflow(
        state_machine_arn=STATE_MACHINE_ARN,
        execution_name=EXECUTION_NAME,
        workflow_input=WORKFLOW_INPUT,
    )

    assert status == "started"
    assert client.calls == [
        {
            "stateMachineArn": STATE_MACHINE_ARN,
            "name": EXECUTION_NAME,
            "input": WORKFLOW_INPUT,
        }
    ]


def test_existing_execution_is_reported_as_duplicate() -> None:
    adapter = StepFunctions(FakeStepFunctionsClient(error=_client_error("ExecutionAlreadyExists")))

    status = adapter.start_workflow(
        state_machine_arn=STATE_MACHINE_ARN,
        execution_name=EXECUTION_NAME,
        workflow_input=WORKFLOW_INPUT,
    )

    assert status == "duplicate"


@pytest.mark.parametrize(
    "error",
    [
        _client_error("ThrottlingException"),
        EndpointConnectionError(endpoint_url="https://states.example.com"),
    ],
)
def test_aws_failures_are_translated_without_sensitive_details(error: Exception) -> None:
    adapter = StepFunctions(FakeStepFunctionsClient(error=error))

    with pytest.raises(WorkflowStartError, match="Unable to start onboarding workflow") as raised:
        adapter.start_workflow(
            state_machine_arn=STATE_MACHINE_ARN,
            execution_name=EXECUTION_NAME,
            workflow_input=WORKFLOW_INPUT,
        )

    assert raised.value.__cause__ is error
    assert "sensitive AWS detail" not in str(raised.value)


def test_factory_creates_step_functions_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeStepFunctionsClient()

    def boto3_client(service_name: str) -> Any:
        assert service_name == "stepfunctions"
        return client

    monkeypatch.setattr(boto3, "client", boto3_client)

    adapter = step_functions.create_step_functions()

    assert adapter.client is client
