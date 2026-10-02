from dataclasses import dataclass, field
from uuid import UUID

import pytest

from foundry_onboarding.adapters.gitlab.client import GitLabUserRecord
from foundry_onboarding.contracts.gitlab_user import GitLabUserInput
from foundry_onboarding.errors import (
    GitLabIdentityConflictError,
    GitLabProtocolError,
    GitLabRequestError,
    GitLabUnavailableError,
)
from foundry_onboarding.services.gitlab_user import reconcile_gitlab_user

REQUEST_ID = UUID("f084a40c-2d45-4bc9-96b2-d650bb746413")


def _request(
    *,
    username: str = "jane.smith",
    email: str = "jane.smith@example.com",
    external: bool = False,
) -> GitLabUserInput:
    return GitLabUserInput.model_validate(
        {
            "schema_version": "1.0",
            "request_id": str(REQUEST_ID),
            "username": username,
            "name": "Jane Smith",
            "email": email,
            "external": external,
        }
    )


def _user(
    *,
    user_id: int = 123,
    username: str = "jane.smith",
    email: str = "jane.smith@example.com",
    external: bool = False,
    state: str = "active",
) -> GitLabUserRecord:
    return GitLabUserRecord(
        id=user_id,
        username=username,
        email=email,
        external=external,
        state=state,
    )


@dataclass
class FakeGateway:
    username_results: list[GitLabUserRecord | None] = field(default_factory=list)
    email_results: list[GitLabUserRecord | None] = field(default_factory=list)
    created_user: GitLabUserRecord = field(default_factory=_user)
    create_error: Exception | None = None
    calls: list[tuple[str, object]] = field(default_factory=list)

    def find_user_by_username(self, username: str) -> GitLabUserRecord | None:
        self.calls.append(("find_user_by_username", username))
        return self.username_results.pop(0) if self.username_results else None

    def find_user_by_email(self, email: str) -> GitLabUserRecord | None:
        self.calls.append(("find_user_by_email", email))
        return self.email_results.pop(0) if self.email_results else None

    def create_user(self, request: GitLabUserInput) -> GitLabUserRecord:
        self.calls.append(("create_user", request))
        if self.create_error is not None:
            raise self.create_error
        return self.created_user


def test_reconcile_creates_user_when_identity_does_not_exist() -> None:
    request = _request()
    gateway = FakeGateway()

    output = reconcile_gitlab_user(request, gateway)

    assert output.status == "created"
    assert output.request_id == REQUEST_ID
    assert output.result.id == 123
    assert output.result.username == "jane.smith"
    assert gateway.calls == [
        ("find_user_by_username", "jane.smith"),
        ("find_user_by_email", "jane.smith@example.com"),
        ("create_user", request),
    ]


def test_reconcile_returns_matching_existing_username_without_creating() -> None:
    gateway = FakeGateway(username_results=[_user()])

    output = reconcile_gitlab_user(_request(), gateway)

    assert output.status == "existing"
    assert gateway.calls == [("find_user_by_username", "jane.smith")]


def test_reconcile_matches_identity_case_insensitively() -> None:
    gateway = FakeGateway(
        username_results=[_user(username="Jane.Smith", email="Jane.Smith@Example.com")]
    )

    output = reconcile_gitlab_user(_request(), gateway)

    assert output.status == "existing"
    assert output.result.username == "Jane.Smith"


def test_reconcile_returns_matching_existing_email_without_creating() -> None:
    gateway = FakeGateway(email_results=[_user()])

    output = reconcile_gitlab_user(_request(), gateway)

    assert output.status == "existing"
    assert gateway.calls == [
        ("find_user_by_username", "jane.smith"),
        ("find_user_by_email", "jane.smith@example.com"),
    ]


@pytest.mark.parametrize(
    "existing",
    [
        _user(email="different@example.com"),
        _user(username="different.user"),
        _user(external=True),
        _user(state="blocked"),
        _user(state="banned"),
    ],
)
def test_reconcile_rejects_conflicting_or_inactive_existing_users(
    existing: GitLabUserRecord,
) -> None:
    gateway = FakeGateway(username_results=[existing])

    with pytest.raises(GitLabIdentityConflictError, match="identity conflicts"):
        reconcile_gitlab_user(_request(), gateway)


def test_reconcile_rejects_email_owned_by_another_username() -> None:
    gateway = FakeGateway(email_results=[_user(username="another.user")])

    with pytest.raises(GitLabIdentityConflictError):
        reconcile_gitlab_user(_request(), gateway)


def test_reconcile_handles_concurrent_creation_as_existing() -> None:
    request = _request()
    gateway = FakeGateway(
        username_results=[None, _user()],
        create_error=GitLabRequestError("GitLab rejected the user request"),
    )

    output = reconcile_gitlab_user(request, gateway)

    assert output.status == "existing"
    assert gateway.calls == [
        ("find_user_by_username", "jane.smith"),
        ("find_user_by_email", "jane.smith@example.com"),
        ("create_user", request),
        ("find_user_by_username", "jane.smith"),
    ]


def test_reconcile_reraises_request_error_when_no_concurrent_user_exists() -> None:
    error = GitLabRequestError("GitLab rejected the user request")
    gateway = FakeGateway(create_error=error)

    with pytest.raises(GitLabRequestError) as raised:
        reconcile_gitlab_user(_request(), gateway)

    assert raised.value is error


def test_reconcile_propagates_transient_error_without_retrying_locally() -> None:
    error = GitLabUnavailableError("GitLab is temporarily unavailable")
    gateway = FakeGateway(create_error=error)

    with pytest.raises(GitLabUnavailableError) as raised:
        reconcile_gitlab_user(_request(), gateway)

    assert raised.value is error
    assert len([call for call in gateway.calls if call[0] == "create_user"]) == 1


@pytest.mark.parametrize(
    "created_user",
    [
        _user(username="different.user"),
        _user(email="different@example.com"),
        _user(external=True),
        _user(state="blocked"),
    ],
)
def test_reconcile_rejects_incompatible_create_response(
    created_user: GitLabUserRecord,
) -> None:
    gateway = FakeGateway(created_user=created_user)

    with pytest.raises(GitLabProtocolError, match="incompatible created user"):
        reconcile_gitlab_user(_request(), gateway)
