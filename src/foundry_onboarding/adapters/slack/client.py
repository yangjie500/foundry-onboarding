import json
import ssl
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol, cast

import urllib3
from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError, model_validator
from urllib3.exceptions import HTTPError

from foundry_onboarding.contracts.slack_user import SlackInvitationStatus, SlackUserInput
from foundry_onboarding.errors import (
    SlackAuthenticationError,
    SlackProtocolError,
    SlackRequestError,
    SlackUnavailableError,
)
from foundry_onboarding.runtime_configuration.slack import SlackConfiguration

_SLACK_INVITE_URL = "https://slack.com/api/admin.users.invite"
_USER_AGENT = "foundry-onboarding/0.1"
_REQUEST_TIMEOUT = urllib3.Timeout(connect=3.0, read=10.0)
_MAX_RESPONSE_BYTES = 16_384

_AUTHENTICATION_ERRORS = frozenset(
    {
        "access_denied",
        "account_inactive",
        "failed_to_validate_caller",
        "invalid_auth",
        "missing_scope",
        "no_permission",
        "not_allowed_token_type",
        "not_an_admin",
        "not_authed",
        "team_access_not_granted",
        "token_expired",
        "token_revoked",
        "two_factor_setup_required",
        "user_disabled",
    }
)
_REQUEST_ERRORS = frozenset(
    {
        "accesslimited",
        "deprecated_endpoint",
        "ekm_access_denied",
        "enterprise_is_restricted",
        "failed_looking_up_user",
        "failed_to_validate_channels",
        "failed_to_validate_custom_message",
        "failed_to_validate_expiration",
        "failed_to_validate_team",
        "feature_not_enabled",
        "invalid_arg_name",
        "invalid_arguments",
        "invalid_array_arg",
        "invalid_charset",
        "invalid_email",
        "invalid_form_data",
        "invalid_post_type",
        "method_deprecated",
        "missing_post_type",
        "team_not_found",
    }
)
_UNAVAILABLE_ERRORS = frozenset(
    {
        "failed_to_send_invite",
        "fatal_error",
        "internal_error",
        "org_login_required",
        "ratelimited",
        "request_timeout",
        "service_unavailable",
        "team_added_to_org",
    }
)


class HttpResponse(Protocol):
    @property
    def status(self) -> int: ...

    @property
    def data(self) -> bytes: ...


class HttpPool(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        body: bytes | None,
        headers: Mapping[str, str],
        timeout: urllib3.Timeout,
        retries: bool,
        redirect: bool,
    ) -> HttpResponse: ...


class _SlackResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    ok: StrictBool
    error: str | None = Field(default=None, min_length=1, max_length=256)

    @model_validator(mode="after")
    def validate_response(self) -> _SlackResponse:
        if self.ok and self.error is not None:
            raise ValueError("successful Slack response must not contain an error")
        if not self.ok and (self.error is None or not self.error.strip()):
            raise ValueError("failed Slack response must contain an error")

        return self


@dataclass(frozen=True, slots=True)
class SlackClient:
    """Minimal adapter for Slack's workspace invitation API."""

    team_id: str = field(repr=False)
    channel_ids: tuple[str, ...] = field(repr=False)
    user_token: str = field(repr=False)
    http: HttpPool

    def invite_user(self, request: SlackUserInput) -> SlackInvitationStatus:
        body = json.dumps(
            {
                "team_id": self.team_id,
                "email": str(request.email),
                "channel_ids": ",".join(self.channel_ids),
                "real_name": request.name,
            },
            separators=(",", ":"),
        ).encode()
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.user_token}",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": _USER_AGENT,
        }

        try:
            response = self.http.request(
                "POST",
                _SLACK_INVITE_URL,
                body=body,
                headers=headers,
                timeout=_REQUEST_TIMEOUT,
                retries=False,
                redirect=False,
            )
        except HTTPError:
            raise SlackUnavailableError("Slack is temporarily unavailable") from None

        if response.status != 200:
            self._raise_for_status(response.status)

        slack_response = self._parse_response(response.data)
        if slack_response.ok:
            return "invited"

        return self._handle_application_error(cast(str, slack_response.error))

    @staticmethod
    def _parse_response(data: bytes) -> _SlackResponse:
        if len(data) > _MAX_RESPONSE_BYTES:
            raise SlackProtocolError("Slack returned an invalid response")

        try:
            value = json.loads(data)
            return _SlackResponse.model_validate(value)
        except UnicodeDecodeError, json.JSONDecodeError, ValidationError:
            raise SlackProtocolError("Slack returned an invalid response") from None

    @staticmethod
    def _handle_application_error(error: str) -> SlackInvitationStatus:
        if error == "already_in_team":
            return "already_member"
        if error == "already_in_team_invited_user":
            return "already_invited"
        if error in _AUTHENTICATION_ERRORS:
            raise SlackAuthenticationError("Slack authentication failed")
        if error in _REQUEST_ERRORS:
            raise SlackRequestError("Slack rejected the invitation request")
        if error in _UNAVAILABLE_ERRORS:
            raise SlackUnavailableError("Slack is temporarily unavailable")

        raise SlackProtocolError("Slack returned an unexpected error")

    @staticmethod
    def _raise_for_status(status: int) -> None:
        if status in {401, 403}:
            raise SlackAuthenticationError("Slack authentication failed")
        if status == 429 or 500 <= status <= 599:
            raise SlackUnavailableError("Slack is temporarily unavailable")
        if status == 400:
            raise SlackRequestError("Slack rejected the invitation request")

        raise SlackProtocolError("Slack returned an unexpected status")


def create_slack_client(configuration: SlackConfiguration) -> SlackClient:
    """Create a Slack adapter using validated runtime configuration."""

    pool = urllib3.PoolManager(cert_reqs=ssl.CERT_REQUIRED)
    return SlackClient(
        team_id=configuration.team_id,
        channel_ids=configuration.channel_ids,
        user_token=configuration.user_token.get_secret_value(),
        http=cast(HttpPool, pool),
    )
