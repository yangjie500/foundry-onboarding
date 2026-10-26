import json
from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

from foundry_onboarding.contracts.slack_user import SlackUserInput, SlackUserOutput

EVENTS_DIRECTORY = Path(__file__).parents[2] / "events" / "functions" / "slack_user"


def read_event(name: str) -> dict[str, object]:
    event = json.loads((EVENTS_DIRECTORY / name).read_text(encoding="utf-8"))
    assert isinstance(event, dict)
    return cast(dict[str, object], event)


def test_valid_event_matches_slack_user_input_contract() -> None:
    request = SlackUserInput.model_validate(read_event("valid.json"))

    assert request.name == "Jane Smith"
    assert str(request.email) == "jane.smith@example.com"


def test_malformed_event_is_rejected() -> None:
    with pytest.raises(ValidationError) as raised:
        SlackUserInput.model_validate(read_event("malformed.json"))

    assert raised.value.error_count() == 4


@pytest.mark.parametrize("name", ["", " ", f"a{'b' * 255}"])
def test_invalid_names_are_rejected(name: str) -> None:
    event = read_event("valid.json")
    event["name"] = name

    with pytest.raises(ValidationError):
        SlackUserInput.model_validate(event)


@pytest.mark.parametrize("email", ["", "not-an-email", "jane@", "@example.com"])
def test_invalid_email_addresses_are_rejected(email: str) -> None:
    event = read_event("valid.json")
    event["email"] = email

    with pytest.raises(ValidationError):
        SlackUserInput.model_validate(event)


@pytest.mark.parametrize(
    "field",
    [
        "channel_ids",
        "custom_message",
        "guest_expiration_ts",
        "is_restricted",
        "is_ultra_restricted",
        "resend",
        "signing_secret",
        "team_id",
        "user_token",
    ],
)
def test_provider_configuration_and_credentials_are_rejected(field: str) -> None:
    event = read_event("valid.json")
    event[field] = "must-not-be-accepted"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SlackUserInput.model_validate(event)


@pytest.mark.parametrize(
    ("fixture_name", "expected_status"),
    [
        ("expected-invited.json", "invited"),
        ("expected-already-member.json", "already_member"),
        ("expected-already-invited.json", "already_invited"),
    ],
)
def test_expected_output_matches_contract(
    fixture_name: str,
    expected_status: str,
) -> None:
    output = SlackUserOutput.model_validate(read_event(fixture_name))

    assert output.status == expected_status


@pytest.mark.parametrize("status", ["created", "existing", "failed", "pending", ""])
def test_unknown_output_status_is_rejected(status: str) -> None:
    event = read_event("expected-invited.json")
    event["status"] = status

    with pytest.raises(ValidationError):
        SlackUserOutput.model_validate(event)


def test_output_preserves_request_identity_and_round_trips_through_json() -> None:
    request = SlackUserInput.model_validate(read_event("valid.json"))
    output = SlackUserOutput.model_validate(read_event("expected-invited.json"))
    decoded = SlackUserOutput.model_validate_json(output.model_dump_json())

    assert output.request_id == request.request_id
    assert decoded == output
