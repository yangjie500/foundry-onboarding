import json
import ssl
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

import pytest
import urllib3
from urllib3.exceptions import ConnectTimeoutError

from foundry_onboarding.adapters.slack.client import (
    HttpResponse,
    SlackClient,
    create_slack_client,
)
from foundry_onboarding.contracts.slack_user import SlackUserInput
from foundry_onboarding.errors import (
    SlackAuthenticationError,
    SlackProtocolError,
    SlackRequestError,
    SlackUnavailableError,
)
from foundry_onboarding.runtime_configuration.slack import SlackConfiguration

TEAM_ID = "T12345678"
CHANNEL_IDS = ("C12345678", "G87654321")
USER_TOKEN = "xoxp-not-a-real-token"
EMAIL = "jane.smith@example.com"
REAL_NAME = "Jane Smith"


@dataclass(frozen=True, slots=True)
class FakeResponse:
    status: int
    data: bytes


class FakeHttpPool:
    def __init__(
        self,
        responses: list[FakeResponse] | None = None,
        error: ConnectTimeoutError | None = None,
    ) -> None:
        self.responses = list(responses or [])
        self.error = error
        self.calls: list[dict[str, object]] = []

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
    ) -> HttpResponse:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "body": body,
                "headers": dict(headers),
                "timeout": timeout,
                "retries": retries,
                "redirect": redirect,
            }
        )
        if self.error is not None:
            raise self.error

        return self.responses.pop(0)


def _response(status: int, payload: object) -> FakeResponse:
    return FakeResponse(status=status, data=json.dumps(payload).encode())


def _client(pool: FakeHttpPool) -> SlackClient:
    return SlackClient(
        team_id=TEAM_ID,
        channel_ids=CHANNEL_IDS,
        user_token=USER_TOKEN,
        http=pool,
    )


def _request() -> SlackUserInput:
    return SlackUserInput.model_validate(
        {
            "schema_version": "1.0",
            "request_id": "f084a40c-2d45-4bc9-96b2-d650bb746413",
            "name": REAL_NAME,
            "email": EMAIL,
        }
    )


def test_invite_user_sends_only_approved_fields_with_safe_request_options() -> None:
    pool = FakeHttpPool([_response(200, {"ok": True})])

    status = _client(pool).invite_user(_request())

    assert status == "invited"
    assert len(pool.calls) == 1
    call = pool.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "https://slack.com/api/admin.users.invite"
    assert call["headers"] == {
        "Accept": "application/json",
        "Authorization": f"Bearer {USER_TOKEN}",
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "foundry-onboarding/0.1",
    }
    assert json.loads(cast(bytes, call["body"])) == {
        "team_id": TEAM_ID,
        "email": EMAIL,
        "channel_ids": "C12345678,G87654321",
        "real_name": REAL_NAME,
    }
    timeout = cast(urllib3.Timeout, call["timeout"])
    assert timeout.connect_timeout == 3.0
    assert timeout.read_timeout == 10.0
    assert call["retries"] is False
    assert call["redirect"] is False


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        ("already_in_team", "already_member"),
        ("already_in_team_invited_user", "already_invited"),
    ],
)
def test_invite_user_reconciles_existing_membership(error: str, expected: str) -> None:
    pool = FakeHttpPool([_response(200, {"ok": False, "error": error})])

    assert _client(pool).invite_user(_request()) == expected


@pytest.mark.parametrize(
    "error",
    [
        "invalid_auth",
        "not_authed",
        "token_expired",
        "token_revoked",
        "missing_scope",
        "not_allowed_token_type",
        "not_an_admin",
        "failed_to_validate_caller",
        "team_access_not_granted",
    ],
)
def test_invite_user_translates_authentication_errors(error: str) -> None:
    pool = FakeHttpPool([_response(200, {"ok": False, "error": error})])

    with pytest.raises(SlackAuthenticationError, match="authentication failed"):
        _client(pool).invite_user(_request())


@pytest.mark.parametrize(
    "error",
    [
        "invalid_email",
        "failed_to_validate_team",
        "failed_to_validate_channels",
        "invalid_arguments",
        "team_not_found",
    ],
)
def test_invite_user_translates_permanent_request_errors(error: str) -> None:
    pool = FakeHttpPool([_response(200, {"ok": False, "error": error})])

    with pytest.raises(SlackRequestError, match="rejected the invitation request"):
        _client(pool).invite_user(_request())


@pytest.mark.parametrize(
    "error",
    [
        "ratelimited",
        "service_unavailable",
        "internal_error",
        "fatal_error",
        "request_timeout",
        "failed_to_send_invite",
    ],
)
def test_invite_user_translates_transient_errors(error: str) -> None:
    pool = FakeHttpPool([_response(200, {"ok": False, "error": error})])

    with pytest.raises(SlackUnavailableError, match="temporarily unavailable"):
        _client(pool).invite_user(_request())


@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (400, SlackRequestError),
        (401, SlackAuthenticationError),
        (403, SlackAuthenticationError),
        (429, SlackUnavailableError),
        (500, SlackUnavailableError),
        (503, SlackUnavailableError),
        (302, SlackProtocolError),
        (404, SlackProtocolError),
    ],
)
def test_adapter_translates_http_statuses_without_response_body(
    status: int,
    error_type: type[Exception],
) -> None:
    sensitive_body = f"provider error containing {USER_TOKEN} {EMAIL} {REAL_NAME}"
    pool = FakeHttpPool([FakeResponse(status, sensitive_body.encode())])

    with pytest.raises(error_type) as raised:
        _client(pool).invite_user(_request())

    assert USER_TOKEN not in str(raised.value)
    assert EMAIL not in str(raised.value)
    assert REAL_NAME not in str(raised.value)
    assert sensitive_body not in str(raised.value)


@pytest.mark.parametrize(
    "payload",
    [
        b"not-json",
        json.dumps([]).encode(),
        json.dumps({}).encode(),
        json.dumps({"ok": "true"}).encode(),
        json.dumps({"ok": False}).encode(),
        json.dumps({"ok": False, "error": ""}).encode(),
        json.dumps({"ok": True, "error": "contradictory"}).encode(),
        b"{" + (b"x" * 16_384) + b"}",
    ],
)
def test_invite_user_rejects_malformed_or_oversized_responses(payload: bytes) -> None:
    pool = FakeHttpPool([FakeResponse(200, payload)])

    with pytest.raises(SlackProtocolError, match="invalid response"):
        _client(pool).invite_user(_request())


def test_invite_user_rejects_unknown_application_error_without_exposing_it() -> None:
    sensitive_error = f"unknown-{USER_TOKEN}-{EMAIL}"
    pool = FakeHttpPool([_response(200, {"ok": False, "error": sensitive_error})])

    with pytest.raises(SlackProtocolError, match="unexpected error") as raised:
        _client(pool).invite_user(_request())

    assert sensitive_error not in str(raised.value)
    assert USER_TOKEN not in str(raised.value)
    assert EMAIL not in str(raised.value)


def test_adapter_translates_network_errors() -> None:
    pool = FakeHttpPool(error=ConnectTimeoutError(None, "timed out"))

    with pytest.raises(SlackUnavailableError, match="temporarily unavailable") as raised:
        _client(pool).invite_user(_request())

    assert raised.value.__cause__ is None


def test_client_representation_hides_configuration_and_token() -> None:
    client = _client(FakeHttpPool())

    assert USER_TOKEN not in repr(client)
    assert TEAM_ID not in repr(client)
    assert CHANNEL_IDS[0] not in repr(client)


def test_create_client_applies_tls_verification(monkeypatch: pytest.MonkeyPatch) -> None:
    pools: list[dict[str, object]] = []
    pool = FakeHttpPool()

    def create_pool(**kwargs: object) -> FakeHttpPool:
        pools.append(kwargs)
        return pool

    monkeypatch.setattr(urllib3, "PoolManager", create_pool)
    configuration = SlackConfiguration.model_validate(
        {
            "team_id": TEAM_ID,
            "channel_ids": CHANNEL_IDS,
            "user_token": USER_TOKEN,
        }
    )

    client = create_slack_client(configuration)

    assert pools == [{"cert_reqs": ssl.CERT_REQUIRED}]
    assert client.http is pool
    assert USER_TOKEN not in repr(client)
