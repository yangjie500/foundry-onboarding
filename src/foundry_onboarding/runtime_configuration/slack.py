from typing import Annotated, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)

from foundry_onboarding.adapters.aws.parameter_store import (
    ParameterStore,
    create_parameter_store,
)
from foundry_onboarding.adapters.aws.secrets_manager import SecretStore, create_secret_store
from foundry_onboarding.errors import ConfigurationError
from foundry_onboarding.runtime_configuration.environment import required_environment_variable

TEAM_ID_PARAMETER_ENV = "SLACK_TEAM_ID_PARAMETER_NAME"
CHANNEL_IDS_PARAMETER_ENV = "SLACK_CHANNEL_IDS_PARAMETER_NAME"
CREDENTIALS_SECRET_ENV = "SLACK_CREDENTIALS_SECRET_NAME"

SlackTeamId = Annotated[
    str,
    Field(min_length=2, max_length=32, pattern=r"^T[A-Z0-9]+$"),
]
SlackChannelId = Annotated[
    str,
    Field(min_length=2, max_length=32, pattern=r"^[CG][A-Z0-9]+$"),
]


class SlackCredentials(BaseModel):
    """Validated secret document used to authenticate to Slack."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    user_token: Annotated[SecretStr, Field(min_length=1)]

    @model_validator(mode="after")
    def token_must_not_be_blank(self) -> Self:
        if not self.user_token.get_secret_value().strip():
            raise ValueError("Slack user token must not be blank")

        return self


class SlackConfiguration(BaseModel):
    """Validated runtime values used to invite users to Slack."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    team_id: SlackTeamId
    channel_ids: Annotated[tuple[SlackChannelId, ...], Field(min_length=1)]
    user_token: Annotated[SecretStr, Field(min_length=1)]

    @field_validator("channel_ids", mode="before")
    @classmethod
    def parse_channel_ids(cls, value: object) -> object:
        if not isinstance(value, str):
            return value

        channel_ids = tuple(channel_id.strip() for channel_id in value.split(","))
        if any(not channel_id for channel_id in channel_ids):
            raise ValueError("Slack channel IDs must not contain blank entries")

        return channel_ids

    @model_validator(mode="after")
    def validate_slack_configuration(self) -> Self:
        if len(set(self.channel_ids)) != len(self.channel_ids):
            raise ValueError("Slack channel IDs must be distinct")
        if not self.user_token.get_secret_value().strip():
            raise ValueError("Slack user token must not be blank")

        return self


def _create_parameter_store() -> ParameterStore:
    return create_parameter_store()


def _create_secret_store() -> SecretStore:
    return create_secret_store()


def load_slack_configuration() -> SlackConfiguration:
    """Load and validate Slack runtime configuration from AWS stores."""

    team_id_parameter_name = required_environment_variable(TEAM_ID_PARAMETER_ENV)
    channel_ids_parameter_name = required_environment_variable(CHANNEL_IDS_PARAMETER_ENV)
    credentials_secret_name = required_environment_variable(CREDENTIALS_SECRET_ENV)

    values = _create_parameter_store().get_parameters(
        [team_id_parameter_name, channel_ids_parameter_name],
        with_decryption=False,
    )
    secret_document = _create_secret_store().get_json_secret(credentials_secret_name)

    try:
        credentials = SlackCredentials.model_validate(secret_document)
        return SlackConfiguration.model_validate(
            {
                "team_id": values[team_id_parameter_name],
                "channel_ids": values[channel_ids_parameter_name],
                "user_token": credentials.user_token,
            }
        )
    except ValidationError:
        raise ConfigurationError("Slack runtime configuration is invalid") from None
