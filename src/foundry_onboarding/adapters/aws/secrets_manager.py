import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, cast

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from foundry_onboarding.errors import ConfigurationError


class SecretsManagerClient(Protocol):
    """Subset of the Secrets Manager client required by the adapter."""

    def get_secret_value(self, *, SecretId: str) -> Mapping[str, object]: ...


@dataclass(frozen=True, slots=True)
class SecretStore:
    """Retrieve and parse JSON secret documents from Secrets Manager."""

    client: SecretsManagerClient

    def get_json_secret(self, secret_name: str) -> dict[str, object]:
        if not secret_name.strip():
            raise ConfigurationError("Secret name must be non-empty")

        try:
            response = self.client.get_secret_value(SecretId=secret_name)
        except (BotoCoreError, ClientError) as error:
            raise ConfigurationError("Unable to load secret from Secrets Manager") from error

        secret_string = response.get("SecretString")
        if not isinstance(secret_string, str) or not secret_string:
            raise ConfigurationError("Secrets Manager returned an invalid secret")

        try:
            decoded = json.loads(secret_string)
        except json.JSONDecodeError as error:
            raise ConfigurationError("Secrets Manager returned invalid JSON") from error

        if not isinstance(decoded, dict):
            raise ConfigurationError("Secrets Manager secret must be a JSON object")

        return cast(dict[str, object], decoded)


def create_secret_store() -> SecretStore:
    """Create the production adapter backed by the Lambda execution role."""

    client = cast(SecretsManagerClient, boto3.client("secretsmanager"))
    return SecretStore(client)
