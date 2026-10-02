import re
from typing import Annotated, Literal

from pydantic import AfterValidator, EmailStr, Field, StrictBool

from foundry_onboarding.contracts.common import ContractModel, WorkflowIdentity

_CONSECUTIVE_SPECIAL_CHARACTERS = re.compile(r"[_.-]{2}")
_RESERVED_FILE_EXTENSIONS = (".atom", ".git")


def _validate_gitlab_username(username: str) -> str:
    if _CONSECUTIVE_SPECIAL_CHARACTERS.search(username):
        raise ValueError("GitLab username must not contain consecutive special characters")
    if username.lower().endswith(_RESERVED_FILE_EXTENSIONS):
        raise ValueError("GitLab username must not end with a reserved file extension")

    return username


GitLabUsername = Annotated[
    str,
    Field(
        min_length=2,
        max_length=255,
        pattern=r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9])$",
    ),
    AfterValidator(_validate_gitlab_username),
]


class GitLabUserInput(WorkflowIdentity):
    """Input accepted by the GitLab user provisioning Lambda."""

    username: GitLabUsername
    name: str = Field(min_length=1, max_length=255)
    email: Annotated[EmailStr, Field(max_length=254)]
    external: StrictBool


class GitLabUserResult(ContractModel):
    """Minimal provider-safe details about a reconciled GitLab user."""

    id: int = Field(strict=True, gt=0)
    username: GitLabUsername


class GitLabUserOutput(WorkflowIdentity):
    """Successful output returned by the GitLab user provisioning Lambda."""

    status: Literal["created", "existing"]
    result: GitLabUserResult
