from typing import Annotated, Literal

from pydantic import EmailStr, Field

from foundry_onboarding.contracts.common import WorkflowIdentity

SlackInvitationStatus = Literal["invited", "already_member", "already_invited"]


class SlackUserInput(WorkflowIdentity):
    """Input accepted by the Slack user invitation Lambda."""

    name: str = Field(min_length=1, max_length=255)
    email: Annotated[EmailStr, Field(max_length=254)]


class SlackUserOutput(WorkflowIdentity):
    """Provider-safe result of reconciling a Slack workspace invitation."""

    status: SlackInvitationStatus
