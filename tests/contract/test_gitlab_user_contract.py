import json
from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

from foundry_onboarding.contracts.gitlab_user import (
    GitLabUserInput,
    GitLabUserOutput,
)

EVENTS_DIRECTORY = Path(__file__).parents[2] / "events" / "functions" / "gitlab_user"


def read_event(name: str) -> dict[str, object]:
    event = json.loads((EVENTS_DIRECTORY / name).read_text(encoding="utf-8"))
    assert isinstance(event, dict)
    return cast(dict[str, object], event)


def test_valid_event_matches_gitlab_user_input_contract() -> None:
    request = GitLabUserInput.model_validate(read_event("valid.json"))

    assert request.username == "jane.smith"
    assert request.name == "Jane Smith"
    assert str(request.email) == "jane.smith@example.com"
    assert request.external is False


def test_malformed_event_is_rejected() -> None:
    with pytest.raises(ValidationError) as raised:
        GitLabUserInput.model_validate(read_event("malformed.json"))

    assert raised.value.error_count() == 5


@pytest.mark.parametrize(
    "username",
    [
        "a",
        ".jane",
        "jane.",
        "-jane",
        "jane-",
        "jane smith",
        "jane@example",
        "jane..smith",
        "jane_-smith",
        "jane.git",
        "jane.atom",
        f"a{'b' * 255}",
    ],
)
def test_invalid_gitlab_usernames_are_rejected(username: str) -> None:
    event = read_event("valid.json")
    event["username"] = username

    with pytest.raises(ValidationError):
        GitLabUserInput.model_validate(event)


@pytest.mark.parametrize("username", ["ab", "jane.smith", "Jane-Smith_2"])
def test_valid_gitlab_usernames_are_accepted(username: str) -> None:
    event = read_event("valid.json")
    event["username"] = username

    request = GitLabUserInput.model_validate(event)

    assert request.username == username


@pytest.mark.parametrize("email", ["", "not-an-email", "jane@", "@example.com"])
def test_invalid_email_addresses_are_rejected(email: str) -> None:
    event = read_event("valid.json")
    event["email"] = email

    with pytest.raises(ValidationError):
        GitLabUserInput.model_validate(event)


@pytest.mark.parametrize("external", [None, "false", 0, 1])
def test_external_must_be_an_explicit_boolean(external: object) -> None:
    event = read_event("valid.json")
    if external is None:
        del event["external"]
    else:
        event["external"] = external

    with pytest.raises(ValidationError):
        GitLabUserInput.model_validate(event)


@pytest.mark.parametrize(
    "field",
    [
        "admin",
        "api_token",
        "base_url",
        "can_create_group",
        "force_random_password",
        "group_id",
        "password",
        "private_profile",
        "reset_password",
        "skip_confirmation",
    ],
)
def test_security_and_provider_configuration_fields_are_rejected(field: str) -> None:
    event = read_event("valid.json")
    event[field] = "must-not-be-accepted"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        GitLabUserInput.model_validate(event)


@pytest.mark.parametrize(
    ("fixture_name", "expected_status"),
    [
        ("expected-created.json", "created"),
        ("expected-existing.json", "existing"),
    ],
)
def test_expected_output_matches_contract(
    fixture_name: str,
    expected_status: str,
) -> None:
    output = GitLabUserOutput.model_validate(read_event(fixture_name))

    assert output.status == expected_status
    assert output.result.id == 123
    assert output.result.username == "jane.smith"


@pytest.mark.parametrize("user_id", [0, -1, "123"])
def test_output_requires_a_positive_strict_user_id(user_id: object) -> None:
    event = read_event("expected-created.json")
    result = event["result"]
    assert isinstance(result, dict)
    result["id"] = user_id

    with pytest.raises(ValidationError):
        GitLabUserOutput.model_validate(event)


def test_output_preserves_request_identity_and_round_trips_through_json() -> None:
    request = GitLabUserInput.model_validate(read_event("valid.json"))
    output = GitLabUserOutput.model_validate(read_event("expected-created.json"))
    decoded = GitLabUserOutput.model_validate_json(output.model_dump_json())

    assert output.request_id == request.request_id
    assert decoded == output
