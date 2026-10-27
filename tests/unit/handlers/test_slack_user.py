import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import pytest

from foundry_onboarding.contracts.slack_user import SlackInvitationStatus, SlackUserInput
from foundry_onboarding.errors import (
    ConfigurationError,
    InvalidInputError,
    OnboardingPolicyRejectedError,
    SlackUnavailableError,
)
from foundry_onboarding.handlers import slack_user
from foundry_onboarding.runtime_configuration.onboarding import (
    OnboardingPolicyConfiguration,
)
from foundry_onboarding.runtime_configuration.slack import SlackConfiguration

EVENTS_DIRECTORY = Path(__file__).parents[3] / "events" / "functions" / "slack_user"
USER_TOKEN = "xoxp-not-a-real-token"
TEAM_ID = "T12345678"
CHANNEL_IDS = ("C12345678", "G87654321")


def read_event(name: str) -> dict[str, object]:
    event = json.loads((EVENTS_DIRECTORY / name).read_text(encoding="utf-8"))
    assert isinstance(event, dict)
    return cast(dict[str, object], event)


def _configuration() -> SlackConfiguration:
    return SlackConfiguration.model_validate(
        {
            "team_id": TEAM_ID,
            "channel_ids": CHANNEL_IDS,
            "user_token": USER_TOKEN,
        }
    )


def _policy_configuration() -> OnboardingPolicyConfiguration:
    return OnboardingPolicyConfiguration.model_validate({"allowed_email_domains": "example.com"})


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


@dataclass
class HandlerHarness:
    gateway: FakeGateway = field(default_factory=FakeGateway)
    configuration: SlackConfiguration = field(default_factory=_configuration)
    policy_configuration: OnboardingPolicyConfiguration = field(
        default_factory=_policy_configuration
    )
    calls: list[tuple[str, object]] = field(default_factory=list)


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> HandlerHarness:
    harness = HandlerHarness()

    def load_policy_configuration() -> OnboardingPolicyConfiguration:
        harness.calls.append(("load_policy_configuration", None))
        return harness.policy_configuration

    def load_configuration() -> SlackConfiguration:
        harness.calls.append(("load_configuration", None))
        return harness.configuration

    def create_client(configuration: SlackConfiguration) -> FakeGateway:
        harness.calls.append(("create_client", configuration))
        return harness.gateway

    monkeypatch.setattr(
        slack_user,
        "load_onboarding_policy_configuration",
        load_policy_configuration,
    )
    monkeypatch.setattr(slack_user, "load_slack_configuration", load_configuration)
    monkeypatch.setattr(slack_user, "create_slack_client", create_client)
    return harness


def test_handler_returns_invited_output_and_composes_dependencies(
    harness: HandlerHarness,
) -> None:
    event = read_event("valid.json")

    result = slack_user.handler(event, object())

    assert result == read_event("expected-invited.json")
    assert harness.calls == [
        ("load_policy_configuration", None),
        ("load_configuration", None),
        ("create_client", harness.configuration),
    ]
    assert len(harness.gateway.calls) == 1
    request = harness.gateway.calls[0]
    assert isinstance(request, SlackUserInput)
    assert request.name == "Jane Smith"
    assert str(request.email) == "jane.smith@example.com"


@pytest.mark.parametrize(
    ("status", "expected_fixture"),
    [
        ("already_member", "expected-already-member.json"),
        ("already_invited", "expected-already-invited.json"),
    ],
)
def test_handler_returns_reconciliation_output(
    harness: HandlerHarness,
    status: SlackInvitationStatus,
    expected_fixture: str,
) -> None:
    harness.gateway.status = status

    result = slack_user.handler(read_event("valid.json"), object())

    assert result == read_event(expected_fixture)
    assert len(harness.gateway.calls) == 1


def test_invalid_input_is_rejected_before_loading_configuration(
    harness: HandlerHarness,
) -> None:
    with pytest.raises(InvalidInputError, match="Slack user input is invalid") as raised:
        slack_user.handler(read_event("malformed.json"), object())

    assert raised.value.__cause__ is None
    assert harness.calls == []
    assert harness.gateway.calls == []


def test_disallowed_domain_is_rejected_before_loading_provider_configuration(
    harness: HandlerHarness,
) -> None:
    event = read_event("valid.json")
    event["email"] = "jane.smith@other.example"

    with pytest.raises(
        OnboardingPolicyRejectedError,
        match="Email domain is not allowed",
    ):
        slack_user.handler(event, object())

    assert harness.calls == [("load_policy_configuration", None)]
    assert harness.gateway.calls == []


def test_success_log_contains_only_safe_request_metadata(
    harness: HandlerHarness,
    caplog: pytest.LogCaptureFixture,
) -> None:
    event = read_event("valid.json")

    with caplog.at_level(logging.INFO, logger="foundry_onboarding.handlers.slack_user"):
        slack_user.handler(event, object())

    records = [
        record
        for record in caplog.records
        if record.getMessage() == "Slack user provisioning completed"
    ]
    assert len(records) == 1
    record = records[0]
    assert record.__dict__["request_id"] == event["request_id"]
    assert record.__dict__["status"] == "invited"
    assert "Jane Smith" not in caplog.text
    assert "jane.smith@example.com" not in caplog.text
    assert USER_TOKEN not in caplog.text
    assert TEAM_ID not in caplog.text
    assert CHANNEL_IDS[0] not in caplog.text


def test_invalid_input_log_uses_unknown_request_id_and_excludes_payload(
    harness: HandlerHarness,
    caplog: pytest.LogCaptureFixture,
) -> None:
    event = read_event("malformed.json")

    with (
        caplog.at_level(logging.WARNING, logger="foundry_onboarding.handlers.slack_user"),
        pytest.raises(InvalidInputError),
    ):
        slack_user.handler(event, object())

    records = [
        record
        for record in caplog.records
        if record.getMessage() == "Slack user provisioning rejected invalid input"
    ]
    assert len(records) == 1
    record = records[0]
    assert record.__dict__["request_id"] == "unknown"
    assert record.__dict__["validation_error_count"] == 4
    assert "not-an-email" not in caplog.text
    assert "must-not-be-accepted" not in caplog.text


def test_provider_error_is_logged_safely_and_propagated(
    harness: HandlerHarness,
    caplog: pytest.LogCaptureFixture,
) -> None:
    error = SlackUnavailableError("sensitive provider details must not be logged")
    harness.gateway.error = error

    with (
        caplog.at_level(logging.WARNING, logger="foundry_onboarding.handlers.slack_user"),
        pytest.raises(SlackUnavailableError) as raised,
    ):
        slack_user.handler(read_event("valid.json"), object())

    assert raised.value is error
    records = [
        record
        for record in caplog.records
        if record.getMessage() == "Slack user provisioning failed"
    ]
    assert len(records) == 1
    assert records[0].__dict__["error_code"] == "SLACK_UNAVAILABLE"
    assert "sensitive provider details" not in caplog.text
    assert "jane.smith@example.com" not in caplog.text
    assert USER_TOKEN not in caplog.text


def test_configuration_error_is_logged_safely_and_propagated(
    harness: HandlerHarness,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    error = ConfigurationError("sensitive configuration details")

    def fail_configuration_load() -> SlackConfiguration:
        raise error

    monkeypatch.setattr(slack_user, "load_slack_configuration", fail_configuration_load)

    with (
        caplog.at_level(logging.WARNING, logger="foundry_onboarding.handlers.slack_user"),
        pytest.raises(ConfigurationError) as raised,
    ):
        slack_user.handler(read_event("valid.json"), object())

    assert raised.value is error
    records = [
        record
        for record in caplog.records
        if record.getMessage() == "Slack user provisioning failed"
    ]
    assert len(records) == 1
    assert records[0].__dict__["error_code"] == "CONFIGURATION_ERROR"
    assert "sensitive configuration details" not in caplog.text
    assert USER_TOKEN not in caplog.text
