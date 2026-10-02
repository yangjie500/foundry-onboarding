import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import pytest

from foundry_onboarding.adapters.gitlab.client import GitLabUserRecord
from foundry_onboarding.contracts.gitlab_user import GitLabUserInput
from foundry_onboarding.errors import (
    ConfigurationError,
    GitLabUnavailableError,
    InvalidInputError,
)
from foundry_onboarding.handlers import gitlab_user
from foundry_onboarding.runtime_configuration.gitlab import GitLabConfiguration

EVENTS_DIRECTORY = Path(__file__).parents[3] / "events" / "functions" / "gitlab_user"
API_TOKEN = "glpat-not-a-real-token"


def read_event(name: str) -> dict[str, object]:
    event = json.loads((EVENTS_DIRECTORY / name).read_text(encoding="utf-8"))
    assert isinstance(event, dict)
    return cast(dict[str, object], event)


def _configuration() -> GitLabConfiguration:
    return GitLabConfiguration.model_validate(
        {
            "base_url": "https://gitlab.example.com",
            "api_token": API_TOKEN,
            "tls_verify": False,
        }
    )


def _user() -> GitLabUserRecord:
    return GitLabUserRecord(
        id=123,
        username="jane.smith",
        email="jane.smith@example.com",
        external=False,
        state="active",
    )


@dataclass
class FakeGateway:
    existing_user: GitLabUserRecord | None = None
    created_user: GitLabUserRecord = field(default_factory=_user)
    error: Exception | None = None
    calls: list[tuple[str, object]] = field(default_factory=list)

    def find_user_by_username(self, username: str) -> GitLabUserRecord | None:
        self.calls.append(("find_user_by_username", username))
        if self.error is not None:
            raise self.error
        return self.existing_user

    def find_user_by_email(self, email: str) -> GitLabUserRecord | None:
        self.calls.append(("find_user_by_email", email))
        return None

    def create_user(self, request: GitLabUserInput) -> GitLabUserRecord:
        self.calls.append(("create_user", request))
        return self.created_user


@dataclass
class HandlerHarness:
    gateway: FakeGateway = field(default_factory=FakeGateway)
    configuration: GitLabConfiguration = field(default_factory=_configuration)
    calls: list[tuple[str, object]] = field(default_factory=list)


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> HandlerHarness:
    harness = HandlerHarness()

    def load_configuration() -> GitLabConfiguration:
        harness.calls.append(("load_configuration", None))
        return harness.configuration

    def create_client(configuration: GitLabConfiguration) -> FakeGateway:
        harness.calls.append(("create_client", configuration))
        return harness.gateway

    monkeypatch.setattr(gitlab_user, "load_gitlab_configuration", load_configuration)
    monkeypatch.setattr(gitlab_user, "create_gitlab_client", create_client)
    return harness


def test_handler_returns_created_output_and_composes_dependencies(
    harness: HandlerHarness,
) -> None:
    event = read_event("valid.json")

    result = gitlab_user.handler(event, object())

    assert result == read_event("expected-created.json")
    assert harness.calls == [
        ("load_configuration", None),
        ("create_client", harness.configuration),
    ]
    assert harness.gateway.calls[0] == ("find_user_by_username", "jane.smith")
    assert harness.gateway.calls[1] == (
        "find_user_by_email",
        "jane.smith@example.com",
    )
    operation, request = harness.gateway.calls[2]
    assert operation == "create_user"
    assert isinstance(request, GitLabUserInput)


def test_handler_returns_existing_output(harness: HandlerHarness) -> None:
    harness.gateway.existing_user = _user()

    result = gitlab_user.handler(read_event("valid.json"), object())

    assert result == read_event("expected-existing.json")
    assert [call[0] for call in harness.gateway.calls] == ["find_user_by_username"]


def test_invalid_input_is_rejected_before_loading_configuration(
    harness: HandlerHarness,
) -> None:
    with pytest.raises(InvalidInputError, match="GitLab user input is invalid") as raised:
        gitlab_user.handler(read_event("malformed.json"), object())

    assert raised.value.__cause__ is None
    assert harness.calls == []
    assert harness.gateway.calls == []


def test_success_log_contains_only_safe_request_metadata(
    harness: HandlerHarness,
    caplog: pytest.LogCaptureFixture,
) -> None:
    event = read_event("valid.json")

    with caplog.at_level(logging.INFO, logger="foundry_onboarding.handlers.gitlab_user"):
        gitlab_user.handler(event, object())

    records = [
        record
        for record in caplog.records
        if record.getMessage() == "GitLab user provisioning completed"
    ]
    assert len(records) == 1
    record = records[0]
    assert record.__dict__["request_id"] == event["request_id"]
    assert record.__dict__["status"] == "created"
    assert record.__dict__["gitlab_user_id"] == 123
    assert "Jane Smith" not in caplog.text
    assert "jane.smith@example.com" not in caplog.text
    assert "jane.smith" not in caplog.text
    assert API_TOKEN not in caplog.text


def test_invalid_input_log_uses_unknown_request_id_and_excludes_payload(
    harness: HandlerHarness,
    caplog: pytest.LogCaptureFixture,
) -> None:
    event = read_event("malformed.json")

    with (
        caplog.at_level(logging.WARNING, logger="foundry_onboarding.handlers.gitlab_user"),
        pytest.raises(InvalidInputError),
    ):
        gitlab_user.handler(event, object())

    records = [
        record
        for record in caplog.records
        if record.getMessage() == "GitLab user provisioning rejected invalid input"
    ]
    assert len(records) == 1
    record = records[0]
    assert record.__dict__["request_id"] == "unknown"
    assert record.__dict__["validation_error_count"] == 5
    assert "not-an-email" not in caplog.text
    assert ".jane" not in caplog.text


def test_provider_error_is_logged_safely_and_propagated(
    harness: HandlerHarness,
    caplog: pytest.LogCaptureFixture,
) -> None:
    error = GitLabUnavailableError("sensitive provider details must not be logged")
    harness.gateway.error = error

    with (
        caplog.at_level(logging.WARNING, logger="foundry_onboarding.handlers.gitlab_user"),
        pytest.raises(GitLabUnavailableError) as raised,
    ):
        gitlab_user.handler(read_event("valid.json"), object())

    assert raised.value is error
    records = [
        record
        for record in caplog.records
        if record.getMessage() == "GitLab user provisioning failed"
    ]
    assert len(records) == 1
    assert records[0].__dict__["error_code"] == "GITLAB_UNAVAILABLE"
    assert "sensitive provider details" not in caplog.text
    assert "jane.smith@example.com" not in caplog.text
    assert API_TOKEN not in caplog.text


def test_configuration_error_is_logged_safely_and_propagated(
    harness: HandlerHarness,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    error = ConfigurationError("sensitive configuration details")

    def fail_configuration_load() -> GitLabConfiguration:
        raise error

    monkeypatch.setattr(gitlab_user, "load_gitlab_configuration", fail_configuration_load)

    with (
        caplog.at_level(logging.WARNING, logger="foundry_onboarding.handlers.gitlab_user"),
        pytest.raises(ConfigurationError) as raised,
    ):
        gitlab_user.handler(read_event("valid.json"), object())

    assert raised.value is error
    records = [
        record
        for record in caplog.records
        if record.getMessage() == "GitLab user provisioning failed"
    ]
    assert len(records) == 1
    assert records[0].__dict__["error_code"] == "CONFIGURATION_ERROR"
    assert "sensitive configuration details" not in caplog.text
    assert API_TOKEN not in caplog.text
