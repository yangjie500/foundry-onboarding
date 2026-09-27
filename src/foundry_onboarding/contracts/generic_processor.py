from typing import Literal

from pydantic import Field

from foundry_onboarding.contracts.common import ContractModel, WorkflowIdentity


class EchoResult(ContractModel):
    """Result produced by the generic processor's echo operation."""

    message: str = Field(min_length=1, max_length=1_000)


class GenericProcessorInput(WorkflowIdentity):
    """Input accepted by the generic processor Lambda."""

    message: str = Field(min_length=1, max_length=1_000)


class GenericProcessorOutput(WorkflowIdentity):
    """Successful output returned by the generic processor Lambda."""

    status: Literal["succeeded"]
    result: EchoResult
