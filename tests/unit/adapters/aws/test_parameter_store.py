from collections.abc import Mapping

import pytest
from botocore.exceptions import ClientError

from foundry_onboarding.adapters.aws.parameter_store import (
    ParameterStore,
    create_parameter_store,
)
from foundry_onboarding.errors import ConfigurationError

VARIABLE_NAME = "/foundry/dev/generic/example-variable"
SECRET_NAME = "/foundry/dev/generic/example-secret"


class FakeParameterStoreClient:
    def __init__(
        self,
        response: Mapping[str, object] | None = None,
        error: ClientError | None = None,
    ) -> None:
        self.response = response or {"Parameters": []}
        self.error = error
        self.calls: list[tuple[list[str], bool]] = []

    def get_parameters(
        self,
        *,
        Names: list[str],
        WithDecryption: bool,
    ) -> Mapping[str, object]:
        self.calls.append((Names, WithDecryption))
        if self.error is not None:
            raise self.error

        return self.response


def _successful_response() -> Mapping[str, object]:
    return {
        "Parameters": [
            {"Name": SECRET_NAME, "Value": "not-a-real-secret"},
            {"Name": VARIABLE_NAME, "Value": "hello-from-dev-parameter-store"},
        ]
    }


def test_get_parameters_maps_values_by_name_and_supports_decryption() -> None:
    client = FakeParameterStoreClient(_successful_response())

    values = ParameterStore(client).get_parameters(
        [VARIABLE_NAME, SECRET_NAME],
        with_decryption=True,
    )

    assert client.calls == [([VARIABLE_NAME, SECRET_NAME], True)]
    assert values == {
        VARIABLE_NAME: "hello-from-dev-parameter-store",
        SECRET_NAME: "not-a-real-secret",
    }


def test_get_parameters_removes_duplicate_names() -> None:
    client = FakeParameterStoreClient(_successful_response())

    ParameterStore(client).get_parameters([VARIABLE_NAME, VARIABLE_NAME, SECRET_NAME])

    assert client.calls == [([VARIABLE_NAME, SECRET_NAME], False)]


@pytest.mark.parametrize("names", [[], [""], ["   "]])
def test_get_parameters_rejects_empty_names(names: list[str]) -> None:
    with pytest.raises(ConfigurationError, match="names must be non-empty"):
        ParameterStore(FakeParameterStoreClient()).get_parameters(names)


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"Parameters": "invalid"},
        {"Parameters": [{"Name": VARIABLE_NAME, "Value": "configured"}]},
        {"Parameters": [{"Name": SECRET_NAME, "Value": ""}]},
        {"Parameters": ["invalid-entry"]},
    ],
)
def test_get_parameters_rejects_missing_or_invalid_values(
    response: Mapping[str, object],
) -> None:
    store = ParameterStore(FakeParameterStoreClient(response))

    with pytest.raises(ConfigurationError):
        store.get_parameters([VARIABLE_NAME, SECRET_NAME])


def test_get_parameters_translates_aws_errors_without_values() -> None:
    error = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "denied"}},
        "GetParameters",
    )
    store = ParameterStore(FakeParameterStoreClient(error=error))

    with pytest.raises(
        ConfigurationError,
        match="Unable to load parameters from Parameter Store",
    ) as raised:
        store.get_parameters([VARIABLE_NAME, SECRET_NAME])

    assert "not-a-real-secret" not in str(raised.value)
    assert raised.value.__cause__ is error


def test_create_parameter_store_uses_ssm_client(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeParameterStoreClient(_successful_response())
    services: list[str] = []

    def create_client(service: str) -> FakeParameterStoreClient:
        services.append(service)
        return client

    monkeypatch.setattr(
        "foundry_onboarding.adapters.aws.parameter_store.boto3.client",
        create_client,
    )

    store = create_parameter_store()

    assert store.client is client
    assert services == ["ssm"]
