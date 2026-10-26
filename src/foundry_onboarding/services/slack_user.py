from typing import Protocol

from foundry_onboarding.contracts.slack_user import (
    SlackInvitationStatus,
    SlackUserInput,
    SlackUserOutput,
)


class SlackUserGateway(Protocol):
    """Provider operation required to reconcile a Slack invitation."""

    def invite_user(self, request: SlackUserInput) -> SlackInvitationStatus: ...


def reconcile_slack_user(
    request: SlackUserInput,
    gateway: SlackUserGateway,
) -> SlackUserOutput:
    """Invite a Slack user and return the provider-safe reconciliation status."""

    status = gateway.invite_user(request)
    return SlackUserOutput(
        schema_version=request.schema_version,
        request_id=request.request_id,
        status=status,
    )
