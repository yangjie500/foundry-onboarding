from dataclasses import dataclass
from typing import Literal, Protocol, cast

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from foundry_onboarding.errors import WorkflowStartError

WorkflowStartStatus = Literal["started", "duplicate"]


class StepFunctionsClient(Protocol):
    """Subset of the Step Functions client used by the ingress adapter."""

    def start_execution(
        self,
        *,
        stateMachineArn: str,
        name: str,
        input: str,
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class StepFunctions:
    """Start workflow executions while translating AWS failures safely."""

    client: StepFunctionsClient

    def start_workflow(
        self,
        *,
        state_machine_arn: str,
        execution_name: str,
        workflow_input: str,
    ) -> WorkflowStartStatus:
        try:
            self.client.start_execution(
                stateMachineArn=state_machine_arn,
                name=execution_name,
                input=workflow_input,
            )
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") == "ExecutionAlreadyExists":
                return "duplicate"
            raise WorkflowStartError("Unable to start onboarding workflow") from error
        except BotoCoreError as error:
            raise WorkflowStartError("Unable to start onboarding workflow") from error

        return "started"


def create_step_functions() -> StepFunctions:
    """Create the production adapter backed by the Lambda execution role."""

    client = cast(StepFunctionsClient, boto3.client("stepfunctions"))
    return StepFunctions(client)
