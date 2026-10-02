import json
import logging
import ssl
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol, cast
from urllib.parse import urlencode

import urllib3
from pydantic import BaseModel, ConfigDict, EmailStr, Field, StrictBool, ValidationError
from urllib3.exceptions import HTTPError

from foundry_onboarding.contracts.gitlab_user import GitLabUserInput
from foundry_onboarding.errors import (
    GitLabAuthenticationError,
    GitLabProtocolError,
    GitLabRequestError,
    GitLabUnavailableError,
)
from foundry_onboarding.runtime_configuration.gitlab import GitLabConfiguration

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = urllib3.Timeout(connect=3.0, read=10.0)


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


class _GitLabUserResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    id: int = Field(strict=True, gt=0)
    username: str = Field(min_length=1, max_length=255)
    email: EmailStr
    external: StrictBool
    state: str = Field(min_length=1, max_length=64)


@dataclass(frozen=True, slots=True)
class GitLabUserRecord:
    """Provider fields required to reconcile a GitLab identity."""

    id: int
    username: str
    email: str
    external: bool
    state: str


@dataclass(frozen=True, slots=True)
class GitLabClient:
    """Minimal GitLab Users API adapter."""

    base_url: str
    api_token: str = field(repr=False)
    http: HttpPool

    def find_user_by_username(self, username: str) -> GitLabUserRecord | None:
        users = self._get_users({"username": username})
        matches = [user for user in users if user.username.casefold() == username.casefold()]
        return self._single_match(matches)

    def find_user_by_email(self, email: str) -> GitLabUserRecord | None:
        users = self._get_users({"search": email})
        matches = [user for user in users if user.email.casefold() == email.casefold()]
        return self._single_match(matches)

    def create_user(self, request: GitLabUserInput) -> GitLabUserRecord:
        response = self._request(
            "POST",
            "/api/v4/users",
            body={
                "username": request.username,
                "name": request.name,
                "email": str(request.email),
                "external": request.external,
                "reset_password": True,
                "admin": False,
                "can_create_group": False,
                "private_profile": True,
            },
        )
        if response.status != 201:
            self._raise_for_status(response.status)

        return self._parse_user(response.data)

    def _get_users(self, query: Mapping[str, str]) -> list[GitLabUserRecord]:
        response = self._request("GET", f"/api/v4/users?{urlencode(query)}")
        if response.status != 200:
            self._raise_for_status(response.status)

        try:
            payload = json.loads(response.data)
        except UnicodeDecodeError, json.JSONDecodeError:
            raise GitLabProtocolError("GitLab returned an invalid response") from None

        if not isinstance(payload, list):
            raise GitLabProtocolError("GitLab returned an invalid response")

        return [self._parse_user_value(value) for value in payload]

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: Mapping[str, object] | None = None,
    ) -> HttpResponse:
        headers = {
            "Accept": "application/json",
            "PRIVATE-TOKEN": self.api_token,
        }
        encoded_body: bytes | None = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            encoded_body = json.dumps(body, separators=(",", ":")).encode()

        try:
            return self.http.request(
                method,
                f"{self.base_url}{path}",
                body=encoded_body,
                headers=headers,
                timeout=_REQUEST_TIMEOUT,
                retries=False,
                redirect=False,
            )
        except HTTPError:
            raise GitLabUnavailableError("GitLab is temporarily unavailable") from None

    @staticmethod
    def _parse_user(data: bytes) -> GitLabUserRecord:
        try:
            value = json.loads(data)
        except UnicodeDecodeError, json.JSONDecodeError:
            raise GitLabProtocolError("GitLab returned an invalid response") from None

        return GitLabClient._parse_user_value(value)

    @staticmethod
    def _parse_user_value(value: object) -> GitLabUserRecord:
        try:
            user = _GitLabUserResponse.model_validate(value)
        except ValidationError:
            raise GitLabProtocolError("GitLab returned an invalid response") from None

        return GitLabUserRecord(
            id=user.id,
            username=user.username,
            email=str(user.email),
            external=user.external,
            state=user.state,
        )

    @staticmethod
    def _single_match(matches: list[GitLabUserRecord]) -> GitLabUserRecord | None:
        if len(matches) > 1:
            raise GitLabProtocolError("GitLab returned an invalid response")

        return matches[0] if matches else None

    @staticmethod
    def _raise_for_status(status: int) -> None:
        if status in {401, 403}:
            raise GitLabAuthenticationError("GitLab authentication failed")
        if status == 429 or 500 <= status <= 599:
            raise GitLabUnavailableError("GitLab is temporarily unavailable")
        if status in {400, 409}:
            raise GitLabRequestError("GitLab rejected the user request")

        raise GitLabProtocolError("GitLab returned an unexpected status")


def create_gitlab_client(configuration: GitLabConfiguration) -> GitLabClient:
    """Create a GitLab adapter using validated runtime configuration."""

    if not configuration.tls_verify:
        logger.warning("GitLab TLS certificate verification is disabled for development")

    pool = urllib3.PoolManager(
        cert_reqs=ssl.CERT_REQUIRED if configuration.tls_verify else ssl.CERT_NONE
    )
    return GitLabClient(
        base_url=str(configuration.base_url).rstrip("/"),
        api_token=configuration.api_token.get_secret_value(),
        http=cast(HttpPool, pool),
    )
