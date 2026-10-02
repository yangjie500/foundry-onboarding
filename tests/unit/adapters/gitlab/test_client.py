import json
import logging
import ssl
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

import pytest
import urllib3
from urllib3.exceptions import ConnectTimeoutError

from foundry_onboarding.adapters.gitlab.client import (
    GitLabClient,
    HttpResponse,
    create_gitlab_client,
)
from foundry_onboarding.contracts.gitlab_user import GitLabUserInput
from foundry_onboarding.errors import (
    ConfigurationError,
    GitLabAuthenticationError,
    GitLabProtocolError,
    GitLabRequestError,
    GitLabUnavailableError,
)
from foundry_onboarding.runtime_configuration.gitlab import GitLabConfiguration

API_TOKEN = "glpat-not-a-real-token"
CA_BUNDLE_PEM = "-----BEGIN CERTIFICATE-----\nnot-a-real-certificate\n-----END CERTIFICATE-----"


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


def _user_payload(
    *,
    user_id: int = 123,
    username: str = "jane.smith",
    email: str = "jane.smith@example.com",
    external: bool = False,
    state: str = "active",
) -> dict[str, object]:
    return {
        "id": user_id,
        "username": username,
        "email": email,
        "external": external,
        "state": state,
        "unneeded_provider_field": "ignored",
    }


def _response(status: int, payload: object) -> FakeResponse:
    return FakeResponse(status=status, data=json.dumps(payload).encode())


def _client(pool: FakeHttpPool) -> GitLabClient:
    return GitLabClient(
        base_url="https://gitlab.example.com",
        api_token=API_TOKEN,
        http=pool,
    )


def _request() -> GitLabUserInput:
    return GitLabUserInput.model_validate(
        {
            "schema_version": "1.0",
            "request_id": "f084a40c-2d45-4bc9-96b2-d650bb746413",
            "username": "jane.smith",
            "name": "Jane Smith",
            "email": "jane.smith@example.com",
            "external": False,
        }
    )


def test_find_user_by_username_encodes_query_and_uses_safe_request_options() -> None:
    pool = FakeHttpPool([_response(200, [_user_payload(username="Jane.Smith")])])

    user = _client(pool).find_user_by_username("Jane.Smith")

    assert user is not None
    assert user.id == 123
    assert user.username == "Jane.Smith"
    assert len(pool.calls) == 1
    call = pool.calls[0]
    assert call["method"] == "GET"
    assert call["url"] == "https://gitlab.example.com/api/v4/users?username=Jane.Smith"
    assert call["body"] is None
    assert call["headers"] == {"Accept": "application/json", "PRIVATE-TOKEN": API_TOKEN}
    timeout = cast(urllib3.Timeout, call["timeout"])
    assert timeout.connect_timeout == 3.0
    assert timeout.read_timeout == 10.0
    assert call["retries"] is False
    assert call["redirect"] is False


def test_username_query_is_url_encoded() -> None:
    pool = FakeHttpPool([_response(200, [])])

    _client(pool).find_user_by_username("jane+smith")

    assert pool.calls[0]["url"] == ("https://gitlab.example.com/api/v4/users?username=jane%2Bsmith")


def test_find_user_by_email_filters_fuzzy_results_to_exact_email() -> None:
    pool = FakeHttpPool(
        [
            _response(
                200,
                [
                    _user_payload(user_id=1, email="other@example.com"),
                    _user_payload(user_id=2, email="Jane.Smith@Example.com"),
                ],
            )
        ]
    )

    user = _client(pool).find_user_by_email("jane.smith@example.com")

    assert user is not None
    assert user.id == 2
    assert pool.calls[0]["url"] == (
        "https://gitlab.example.com/api/v4/users?search=jane.smith%40example.com"
    )


def test_lookup_returns_none_when_no_exact_match_exists() -> None:
    pool = FakeHttpPool([_response(200, [_user_payload(email="other@example.com")])])

    assert _client(pool).find_user_by_email("missing@example.com") is None


def test_lookup_rejects_multiple_exact_matches() -> None:
    pool = FakeHttpPool([_response(200, [_user_payload(), _user_payload(user_id=456)])])

    with pytest.raises(GitLabProtocolError, match="invalid response"):
        _client(pool).find_user_by_username("jane.smith")


def test_create_user_sends_fixed_security_policy_without_password() -> None:
    pool = FakeHttpPool([_response(201, _user_payload())])

    user = _client(pool).create_user(_request())

    assert user.id == 123
    call = pool.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "https://gitlab.example.com/api/v4/users"
    assert call["headers"] == {
        "Accept": "application/json",
        "PRIVATE-TOKEN": API_TOKEN,
        "Content-Type": "application/json",
    }
    assert call["retries"] is False
    assert call["redirect"] is False
    body = json.loads(cast(bytes, call["body"]))
    assert body == {
        "username": "jane.smith",
        "name": "Jane Smith",
        "email": "jane.smith@example.com",
        "external": False,
        "reset_password": True,
        "admin": False,
        "can_create_group": False,
        "private_profile": True,
    }
    assert "password" not in body


def test_create_user_translates_provider_rejection() -> None:
    pool = FakeHttpPool([_response(400, {"message": {"email": ["has already been taken"]}})])

    with pytest.raises(GitLabRequestError, match="rejected the user request"):
        _client(pool).create_user(_request())


@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (400, GitLabRequestError),
        (401, GitLabAuthenticationError),
        (403, GitLabAuthenticationError),
        (409, GitLabRequestError),
        (429, GitLabUnavailableError),
        (500, GitLabUnavailableError),
        (503, GitLabUnavailableError),
        (302, GitLabProtocolError),
        (404, GitLabProtocolError),
    ],
)
def test_adapter_translates_http_statuses_without_response_body(
    status: int,
    error_type: type[Exception],
) -> None:
    sensitive_body = f"provider error containing {API_TOKEN}"
    pool = FakeHttpPool([FakeResponse(status, sensitive_body.encode())])

    with pytest.raises(error_type) as raised:
        _client(pool).find_user_by_username("jane.smith")

    assert API_TOKEN not in str(raised.value)
    assert sensitive_body not in str(raised.value)


@pytest.mark.parametrize(
    "payload",
    [
        b"not-json",
        json.dumps({"not": "a-list"}).encode(),
        json.dumps([{"id": "not-an-integer"}]).encode(),
    ],
)
def test_lookup_rejects_malformed_responses(payload: bytes) -> None:
    pool = FakeHttpPool([FakeResponse(200, payload)])

    with pytest.raises(GitLabProtocolError, match="invalid response"):
        _client(pool).find_user_by_username("jane.smith")


@pytest.mark.parametrize(
    "payload",
    [b"not-json", json.dumps({"id": "not-an-integer"}).encode()],
)
def test_create_rejects_malformed_responses(payload: bytes) -> None:
    pool = FakeHttpPool([FakeResponse(201, payload)])

    with pytest.raises(GitLabProtocolError, match="invalid response"):
        _client(pool).create_user(_request())


def test_adapter_translates_network_errors() -> None:
    pool = FakeHttpPool(error=ConnectTimeoutError(None, "timed out"))

    with pytest.raises(GitLabUnavailableError, match="temporarily unavailable") as raised:
        _client(pool).find_user_by_username("jane.smith")

    assert raised.value.__cause__ is None


def test_client_representation_masks_token() -> None:
    client = _client(FakeHttpPool())

    assert API_TOKEN not in repr(client)


@pytest.mark.parametrize(
    ("tls_verify", "expected_certificate_requirement"),
    [(True, ssl.CERT_REQUIRED), (False, ssl.CERT_NONE)],
)
def test_create_client_applies_tls_configuration(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    tls_verify: bool,
    expected_certificate_requirement: ssl.VerifyMode,
) -> None:
    pools: list[dict[str, object]] = []
    pool = FakeHttpPool()

    def create_pool(**kwargs: object) -> FakeHttpPool:
        pools.append(kwargs)
        return pool

    monkeypatch.setattr(urllib3, "PoolManager", create_pool)
    configuration = GitLabConfiguration.model_validate(
        {
            "base_url": "https://gitlab.example.com",
            "api_token": API_TOKEN,
            "tls_verify": tls_verify,
        }
    )

    with caplog.at_level(
        logging.WARNING,
        logger="foundry_onboarding.adapters.gitlab.client",
    ):
        client = create_gitlab_client(configuration)

    assert pools == [{"cert_reqs": expected_certificate_requirement}]
    assert client.http is pool
    assert API_TOKEN not in caplog.text
    assert ("TLS certificate verification is disabled" in caplog.text) is (not tls_verify)


def test_create_client_augments_default_trust_with_custom_ca(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pools: list[dict[str, object]] = []
    pool = FakeHttpPool()

    class FakeSslContext:
        def __init__(self) -> None:
            self.ca_data: str | None = None

        def load_verify_locations(self, *, cadata: str) -> None:
            self.ca_data = cadata

    ssl_context = FakeSslContext()

    def create_default_context() -> ssl.SSLContext:
        return cast(ssl.SSLContext, ssl_context)

    def create_pool(**kwargs: object) -> FakeHttpPool:
        pools.append(kwargs)
        return pool

    monkeypatch.setattr(ssl, "create_default_context", create_default_context)
    monkeypatch.setattr(urllib3, "PoolManager", create_pool)
    configuration = GitLabConfiguration.model_validate(
        {
            "base_url": "https://gitlab.example.com",
            "api_token": API_TOKEN,
            "ca_bundle_pem": CA_BUNDLE_PEM,
            "tls_verify": True,
        }
    )

    client = create_gitlab_client(configuration)

    assert ssl_context.ca_data == CA_BUNDLE_PEM
    assert pools == [{"ssl_context": ssl_context}]
    assert client.http is pool


def test_create_client_translates_invalid_custom_ca_without_exposing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class InvalidSslContext:
        def load_verify_locations(self, *, cadata: str) -> None:
            raise ssl.SSLError(f"invalid certificate: {cadata}")

    def create_default_context() -> ssl.SSLContext:
        return cast(ssl.SSLContext, InvalidSslContext())

    monkeypatch.setattr(ssl, "create_default_context", create_default_context)
    configuration = GitLabConfiguration.model_validate(
        {
            "base_url": "https://gitlab.example.com",
            "api_token": API_TOKEN,
            "ca_bundle_pem": CA_BUNDLE_PEM,
            "tls_verify": True,
        }
    )

    with pytest.raises(ConfigurationError, match="GitLab CA bundle is invalid") as raised:
        create_gitlab_client(configuration)

    assert raised.value.__cause__ is None
    assert CA_BUNDLE_PEM not in str(raised.value)
