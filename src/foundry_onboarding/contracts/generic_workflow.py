from typing import Annotated, Literal, Self

from pydantic import EmailStr, Field, StrictBool, model_validator

from foundry_onboarding.contracts.common import ContractModel, WorkflowIdentity
from foundry_onboarding.contracts.gitlab_user import GitLabUsername, GitLabUserResult
from foundry_onboarding.contracts.slack_user import SlackInvitationStatus


class EchoWorkflowPayload(ContractModel):
    """Payload accepted by the generic workflow's echo action."""

    message: str = Field(min_length=1, max_length=1_000)


class OnboardUserWorkflowPayload(ContractModel):
    """Identity data accepted by the onboarding workflow."""

    username: GitLabUsername
    name: str = Field(min_length=1, max_length=255)
    email: Annotated[EmailStr, Field(max_length=254)]
    external: StrictBool


class GenericWorkflowInput(WorkflowIdentity):
    """Public input used to start the generic workflow."""

    action: Literal["echo", "onboard_user"]
    payload: EchoWorkflowPayload | OnboardUserWorkflowPayload

    @model_validator(mode="after")
    def action_must_match_payload(self) -> Self:
        if self.action == "echo" and not isinstance(self.payload, EchoWorkflowPayload):
            raise ValueError("echo action requires an echo payload")
        if self.action == "onboard_user" and not isinstance(
            self.payload, OnboardUserWorkflowPayload
        ):
            raise ValueError("onboard_user action requires an onboarding payload")

        return self


class OnboardUserGitLabOutput(ContractModel):
    """Provider-safe GitLab result embedded in an onboarding workflow result."""

    status: Literal["created", "existing"]
    result: GitLabUserResult


class OnboardUserSlackOutput(ContractModel):
    """Provider-safe Slack result embedded in an onboarding workflow result."""

    status: SlackInvitationStatus


class OnboardUserWorkflowOutput(WorkflowIdentity):
    """Sanitized result returned by a successful onboarding workflow."""

    action: Literal["onboard_user"]
    gitlab: OnboardUserGitLabOutput
    slack: OnboardUserSlackOutput
