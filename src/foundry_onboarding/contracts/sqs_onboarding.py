from typing import Annotated, Literal

from pydantic import EmailStr, Field, StrictBool

from foundry_onboarding.contracts.common import ContractModel, WorkflowIdentity
from foundry_onboarding.contracts.generic_workflow import (
    GenericWorkflowInput,
    OnboardUserWorkflowPayload,
)
from foundry_onboarding.contracts.gitlab_user import GitLabUsername


class SqsOnboardingPayload(ContractModel):
    """Business data accepted from the external onboarding queue."""

    username: GitLabUsername
    name: str = Field(min_length=1, max_length=255)
    email: Annotated[EmailStr, Field(max_length=254)]
    external: StrictBool


class SqsOnboardingMessage(WorkflowIdentity):
    """Versioned message body accepted from the onboarding queue."""

    action: Literal["onboard_user"]
    payload: SqsOnboardingPayload

    def to_workflow_input(self) -> GenericWorkflowInput:
        """Convert the external message into the internal workflow contract."""
        return GenericWorkflowInput(
            schema_version=self.schema_version,
            request_id=self.request_id,
            action=self.action,
            payload=OnboardUserWorkflowPayload(
                username=self.payload.username,
                name=self.payload.name,
                email=self.payload.email,
                external=self.payload.external,
            ),
        )
