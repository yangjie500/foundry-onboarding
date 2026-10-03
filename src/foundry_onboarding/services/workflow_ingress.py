from typing import Protocol

from foundry_onboarding.adapters.aws.step_functions import WorkflowStartStatus
from foundry_onboarding.contracts.sqs_onboarding import SqsOnboardingMessage


class WorkflowStarter(Protocol):
    """Workflow operation required by the SQS ingestion service."""

    def start_workflow(
        self,
        *,
        state_machine_arn: str,
        execution_name: str,
        workflow_input: str,
    ) -> WorkflowStartStatus: ...


def start_onboarding_workflow(
    message: SqsOnboardingMessage,
    state_machine_arn: str,
    starter: WorkflowStarter,
) -> WorkflowStartStatus:
    """Start one idempotently named workflow from a validated queue message."""

    workflow_input = message.to_workflow_input()
    return starter.start_workflow(
        state_machine_arn=state_machine_arn,
        execution_name=str(message.request_id),
        workflow_input=workflow_input.model_dump_json(),
    )
