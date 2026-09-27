from typing import Literal

from pydantic import Field

from foundry_onboarding.contracts.common import ContractModel, WorkflowIdentity


class EchoWorkflowPayload(ContractModel):
    """Payload accepted by the generic workflow's echo action."""

    message: str = Field(min_length=1, max_length=1_000)


class GenericWorkflowInput(WorkflowIdentity):
    """Public input used to start the generic workflow."""

    action: Literal["echo"]
    payload: EchoWorkflowPayload
