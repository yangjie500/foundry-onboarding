from dataclasses import dataclass, field
from uuid import UUID

import pytest

from foundry_onboarding.contracts.slack_user import SlackInvitationStatus, SlackUserInput
from foundry_onboarding.errors import (
    SlackAuthenticationError,
    SlackProtocolError,
    SlackRequestError,
    SlackUnavailableError,
)
from foundry_onboarding.services.slack_user import reconcile_slack_user

REQUEST_ID = UUID("f084a40c-2d45-4bc9-96b2-d650bb746413")


def _request() -> SlackUserInput:
    return SlackUserInput.model_validate(
        {
            "schema_version": "1.0",
            "request_id": str(REQUEST_ID),
            "name": "Jane Smith",
            "email": "jane.smith@example.com",
        }
    )


@dataclass
class FakeGateway:
    status: SlackInvitationStatus = "invited"
    error: Exception | None = None
    calls: list[SlackUserInput] = field(default_factory=list)

    def invite_user(self, request: SlackUserInput) -> SlackInvitationStatus:
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        return self.status


@pytest.mark.parametrize("status", ["invited", "already_member", "already_invited"])
def test_reconcile_returns_provider_safe_status(status: SlackInvitationStatus) -> None:
    request = _request()
    gateway = FakeGateway(status=status)

    output = reconcile_slack_user(request, gateway)

    assert output.schema_version == "1.0"
    assert output.request_id == REQUEST_ID
    assert output.status == status
    assert gateway.calls == [request]


@pytest.mark.parametrize(
    "error",
    [
        SlackAuthenticationError("authentication failed"),
        SlackRequestError("request rejected"),
        SlackUnavailableError("temporarily unavailable"),
        SlackProtocolError("invalid response"),
    ],
)
def test_reconcile_propagates_provider_errors_without_retrying(error: Exception) -> None:
    gateway = FakeGateway(error=error)

    with pytest.raises(type(error)) as raised:
        reconcile_slack_user(_request(), gateway)

    assert raised.value is error
    assert len(gateway.calls) == 1
