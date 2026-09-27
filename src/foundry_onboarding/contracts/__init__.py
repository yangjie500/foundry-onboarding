"""Public workflow contract models."""

from foundry_onboarding.contracts.common import ContractModel, WorkflowIdentity
from foundry_onboarding.contracts.generic_processor import (
    EchoResult,
    GenericProcessorInput,
    GenericProcessorOutput,
)
from foundry_onboarding.contracts.generic_workflow import (
    EchoWorkflowPayload,
    GenericWorkflowInput,
)

__all__ = [
    "ContractModel",
    "EchoResult",
    "EchoWorkflowPayload",
    "GenericProcessorInput",
    "GenericProcessorOutput",
    "GenericWorkflowInput",
    "WorkflowIdentity",
]
