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
from foundry_onboarding.contracts.gitlab_user import (
    GitLabUserInput,
    GitLabUsername,
    GitLabUserOutput,
    GitLabUserResult,
)

__all__ = [
    "ContractModel",
    "EchoResult",
    "EchoWorkflowPayload",
    "GenericProcessorInput",
    "GenericProcessorOutput",
    "GenericWorkflowInput",
    "GitLabUserInput",
    "GitLabUserOutput",
    "GitLabUserResult",
    "GitLabUsername",
    "WorkflowIdentity",
]
