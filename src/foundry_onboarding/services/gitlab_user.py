from typing import Literal, Protocol

from foundry_onboarding.adapters.gitlab.client import GitLabUserRecord
from foundry_onboarding.contracts.gitlab_user import (
    GitLabUserInput,
    GitLabUserOutput,
    GitLabUserResult,
)
from foundry_onboarding.errors import (
    GitLabIdentityConflictError,
    GitLabProtocolError,
    GitLabRequestError,
)


class GitLabUserGateway(Protocol):
    """Provider operations required to reconcile a GitLab user."""

    def find_user_by_username(self, username: str) -> GitLabUserRecord | None: ...

    def find_user_by_email(self, email: str) -> GitLabUserRecord | None: ...

    def create_user(self, request: GitLabUserInput) -> GitLabUserRecord: ...


def reconcile_gitlab_user(
    request: GitLabUserInput,
    gateway: GitLabUserGateway,
) -> GitLabUserOutput:
    """Return an existing compatible user or create one safely."""

    existing = _find_existing_user(request, gateway)
    if existing is not None:
        return _output(request, "existing", existing)

    try:
        created = gateway.create_user(request)
    except GitLabRequestError:
        concurrent = _find_existing_user(request, gateway)
        if concurrent is not None:
            return _output(request, "existing", concurrent)
        raise

    if not _identity_matches(request, created) or created.state.casefold() != "active":
        raise GitLabProtocolError("GitLab returned an incompatible created user")

    return _output(request, "created", created)


def _find_existing_user(
    request: GitLabUserInput,
    gateway: GitLabUserGateway,
) -> GitLabUserRecord | None:
    by_username = gateway.find_user_by_username(request.username)
    if by_username is not None:
        _require_compatible_identity(request, by_username)
        return by_username

    by_email = gateway.find_user_by_email(str(request.email))
    if by_email is not None:
        _require_compatible_identity(request, by_email)
        return by_email

    return None


def _require_compatible_identity(
    request: GitLabUserInput,
    user: GitLabUserRecord,
) -> None:
    if not _identity_matches(request, user) or user.state.casefold() != "active":
        raise GitLabIdentityConflictError("GitLab user identity conflicts with the request")


def _identity_matches(request: GitLabUserInput, user: GitLabUserRecord) -> bool:
    return (
        user.username.casefold() == request.username.casefold()
        and user.email.casefold() == str(request.email).casefold()
        and user.external is request.external
    )


def _output(
    request: GitLabUserInput,
    status: Literal["created", "existing"],
    user: GitLabUserRecord,
) -> GitLabUserOutput:
    return GitLabUserOutput(
        schema_version=request.schema_version,
        request_id=request.request_id,
        status=status,
        result=GitLabUserResult(id=user.id, username=user.username),
    )
