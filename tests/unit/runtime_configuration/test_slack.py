from collections.abc import Mapping

import pytest
from pydantic import ValidationError

from foundry_onboarding.errors import ConfigurationError
from foundry_onboarding.runtime_configuration import slack

TEAM_ID_PARAMETER_NAME = "/foundry/dev/slack/team-id"
CHANNEL_IDS_PARAMETER_NAME = "/foundry/dev/slack/channel-ids"
CREDENTIALS_SECRET_NAME = "foundry/dev/slack/credentials"
TEAM_ID = "T12345678"
CHANNEL_IDS = "C12345678,G87654321"
USER_TOKEN = "xoxp-not-a-real-token"


class FakeParameterStore:
    def __init__(self, values: Mapping[str, str] | None = None) -> None:
        self.values = dict(
            values
            or {
                TEAM_ID_PARAMETER_NAME: TEAM_ID,
                CHANNEL_IDS_PARAMETER_NAME: CHANNEL_IDS,
            }
        )
        self.calls: list[tuple[list[str], bool]] = []

    def get_parameters(
        self,
        names: list[str],
        *,
        with_decryption: bool = False,
    ) -> dict[str, str]:
        self.calls.append((names, with_decryption))
        return self.values


class FakeSecretStore:
    def __init__(self, document: Mapping[str, object] | None = None) -> None:
        self.document = dict({"user_token": USER_TOKEN} if document is None else document)
        self.calls: list[str] = []

    def get_json_secret(self, secret_name: str) -> dict[str, object]:
        self.calls.append(secret_name)
        return self.document


def _configure_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(slack.TEAM_ID_PARAMETER_ENV, TEAM_ID_PARAMETER_NAME)
    monkeypatch.setenv(slack.CHANNEL_IDS_PARAMETER_ENV, CHANNEL_IDS_PARAMETER_NAME)
    monkeypatch.setenv(slack.CREDENTIALS_SECRET_ENV, CREDENTIALS_SECRET_NAME)


def _configure_stores(
    monkeypatch: pytest.MonkeyPatch,
    parameter_store: FakeParameterStore,
    secret_store: FakeSecretStore,
) -> None:
    monkeypatch.setattr(slack, "_create_parameter_store", lambda: parameter_store)
    monkeypatch.setattr(slack, "_create_secret_store", lambda: secret_store)


@pytest.mark.parametrize(
    "missing_environment",
    [
        slack.TEAM_ID_PARAMETER_ENV,
        slack.CHANNEL_IDS_PARAMETER_ENV,
        slack.CREDENTIALS_SECRET_ENV,
    ],
)
def test_load_configuration_requires_reference_environment_variables(
    monkeypatch: pytest.MonkeyPatch,
    missing_environment: str,
) -> None:
    _configure_environment(monkeypatch)
    monkeypatch.delenv(missing_environment)

    with pytest.raises(ConfigurationError, match=missing_environment):
        slack.load_slack_configuration()


def test_load_configuration_retrieves_parameters_and_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parameter_store = FakeParameterStore()
    secret_store = FakeSecretStore()
    _configure_environment(monkeypatch)
    _configure_stores(monkeypatch, parameter_store, secret_store)

    configuration = slack.load_slack_configuration()

    assert configuration.team_id == TEAM_ID
    assert configuration.channel_ids == ("C12345678", "G87654321")
    assert configuration.user_token.get_secret_value() == USER_TOKEN
    assert parameter_store.calls == [([TEAM_ID_PARAMETER_NAME, CHANNEL_IDS_PARAMETER_NAME], False)]
    assert secret_store.calls == [CREDENTIALS_SECRET_NAME]


def test_configuration_masks_token_and_is_immutable() -> None:
    configuration = slack.SlackConfiguration.model_validate(
        {
            "team_id": TEAM_ID,
            "channel_ids": CHANNEL_IDS,
            "user_token": USER_TOKEN,
        }
    )

    assert USER_TOKEN not in repr(configuration)
    assert "**********" in repr(configuration)
    with pytest.raises(ValidationError, match="Instance is frozen"):
        configuration.team_id = configuration.team_id


@pytest.mark.parametrize("team_id", ["", "E12345678", "t12345678", "T123-456"])
def test_configuration_rejects_invalid_team_ids(team_id: str) -> None:
    with pytest.raises(ValidationError):
        slack.SlackConfiguration.model_validate(
            {"team_id": team_id, "channel_ids": CHANNEL_IDS, "user_token": USER_TOKEN}
        )


@pytest.mark.parametrize(
    "channel_ids",
    ["", "C12345678,", "C12345678,,G87654321", "D12345678", "C12345678,C12345678"],
)
def test_configuration_rejects_invalid_channel_lists(channel_ids: str) -> None:
    with pytest.raises(ValidationError):
        slack.SlackConfiguration.model_validate(
            {"team_id": TEAM_ID, "channel_ids": channel_ids, "user_token": USER_TOKEN}
        )


@pytest.mark.parametrize(
    "secret_document",
    [
        {},
        {"user_token": ""},
        {"user_token": "   "},
        {"user_token": USER_TOKEN, "signing_secret": "not-required"},
    ],
)
def test_loader_rejects_invalid_secret_documents(
    monkeypatch: pytest.MonkeyPatch,
    secret_document: Mapping[str, object],
) -> None:
    parameter_store = FakeParameterStore()
    secret_store = FakeSecretStore(secret_document)
    _configure_environment(monkeypatch)
    _configure_stores(monkeypatch, parameter_store, secret_store)

    with pytest.raises(ConfigurationError, match="Slack runtime configuration is invalid"):
        slack.load_slack_configuration()


def test_loader_translates_validation_errors_without_exposing_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_token = "xoxp-sensitive-invalid-configuration-value"
    parameter_store = FakeParameterStore(
        {
            TEAM_ID_PARAMETER_NAME: "not-a-team-id",
            CHANNEL_IDS_PARAMETER_NAME: CHANNEL_IDS,
        }
    )
    secret_store = FakeSecretStore({"user_token": secret_token})
    _configure_environment(monkeypatch)
    _configure_stores(monkeypatch, parameter_store, secret_store)

    with pytest.raises(
        ConfigurationError,
        match="Slack runtime configuration is invalid",
    ) as raised:
        slack.load_slack_configuration()

    assert raised.value.__cause__ is None
    assert secret_token not in str(raised.value)


def test_loader_fetches_current_secret_on_each_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parameter_store = FakeParameterStore()
    secret_store = FakeSecretStore()
    _configure_environment(monkeypatch)
    _configure_stores(monkeypatch, parameter_store, secret_store)

    first = slack.load_slack_configuration()
    secret_store.document["user_token"] = "xoxp-rotated-not-a-real-token"
    second = slack.load_slack_configuration()

    assert first.user_token.get_secret_value() == USER_TOKEN
    assert second.user_token.get_secret_value() == "xoxp-rotated-not-a-real-token"
    assert len(parameter_store.calls) == 2
    assert len(secret_store.calls) == 2
