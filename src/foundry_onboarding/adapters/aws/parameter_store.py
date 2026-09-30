from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, cast

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from foundry_onboarding.errors import ConfigurationError


class ParameterStoreClient(Protocol):
    """Subset of the SSM client required by the adapter."""

    def get_parameters(
        self,
        *,
        Names: list[str],
        WithDecryption: bool,
    ) -> Mapping[str, object]: ...


@dataclass(frozen=True, slots=True)
class ParameterStore:
    """Retrieve validated configuration values from Parameter Store."""

    client: ParameterStoreClient

    def get_parameters(
        self,
        names: Sequence[str],
        *,
        with_decryption: bool = False,
    ) -> dict[str, str]:
        requested_names = list(dict.fromkeys(names))
        if not requested_names or any(not name.strip() for name in requested_names):
            raise ConfigurationError("Parameter Store names must be non-empty")

        try:
            response = self.client.get_parameters(
                Names=requested_names,
                WithDecryption=with_decryption,
            )
        except (BotoCoreError, ClientError) as error:
            raise ConfigurationError("Unable to load parameters from Parameter Store") from error

        raw_parameters = response.get("Parameters")
        if not isinstance(raw_parameters, list):
            raise ConfigurationError("Parameter Store returned an invalid response")

        values: dict[str, str] = {}
        for raw_parameter in raw_parameters:
            if not isinstance(raw_parameter, Mapping):
                continue

            name = raw_parameter.get("Name")
            value = raw_parameter.get("Value")
            if isinstance(name, str) and isinstance(value, str) and value:
                values[name] = value

        if any(name not in values for name in requested_names):
            raise ConfigurationError("Required Parameter Store values are unavailable")

        return values


def create_parameter_store() -> ParameterStore:
    """Create the production adapter backed by the Lambda execution role."""

    client = cast(ParameterStoreClient, boto3.client("ssm"))
    return ParameterStore(client)
