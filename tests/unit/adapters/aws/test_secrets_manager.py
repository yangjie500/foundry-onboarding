from collections.abc import Mapping

import pytest
from botocore.exceptions import ClientError

from foundry_onboarding.adapters.aws.secrets_manager import (
    SecretStore,
    create_secret_store,
)
from foundry_onboarding.errors import ConfigurationError

SECRET_NAME = "foundry/dev/example/credentials"


class FakeSecretsManagerClient:
    def __init__(
        self,
        response: Mapping[str, object] | None = None,
        error: ClientError | None = None,
    ) -> None:
        self.response = response or {}
        self.error = error
        self.calls: list[str] = []

    def get_secret_value(self, *, SecretId: str) -> Mapping[str, object]:
        self.calls.append(SecretId)
        if self.error is not None:
            raise self.error

        return self.response


def test_get_json_secret_returns_object() -> None:
    client = FakeSecretsManagerClient({"SecretString": '{"api_token":"not-a-real-token"}'})

    secret = SecretStore(client).get_json_secret(SECRET_NAME)

    assert client.calls == [SECRET_NAME]
    assert secret == {"api_token": "not-a-real-token"}


def test_get_json_secret_rejects_empty_name() -> None:
    with pytest.raises(ConfigurationError, match="Secret name must be non-empty"):
        SecretStore(FakeSecretsManagerClient()).get_json_secret(" ")


@pytest.mark.parametrize(
    ("response", "message"),
    [
        ({}, "invalid secret"),
        ({"SecretBinary": b"binary"}, "invalid secret"),
        ({"SecretString": ""}, "invalid secret"),
        ({"SecretString": "not-json"}, "invalid JSON"),
        ({"SecretString": "[]"}, "must be a JSON object"),
    ],
)
def test_get_json_secret_rejects_invalid_documents(
    response: Mapping[str, object],
    message: str,
) -> None:
    with pytest.raises(ConfigurationError, match=message):
        SecretStore(FakeSecretsManagerClient(response)).get_json_secret(SECRET_NAME)


def test_get_json_secret_translates_aws_errors() -> None:
    error = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "denied"}},
        "GetSecretValue",
    )
    store = SecretStore(FakeSecretsManagerClient(error=error))

    with pytest.raises(
        ConfigurationError,
        match="Unable to load secret from Secrets Manager",
    ) as raised:
        store.get_json_secret(SECRET_NAME)

    assert raised.value.__cause__ is error


def test_create_secret_store_uses_secrets_manager_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeSecretsManagerClient()
    services: list[str] = []

    def create_client(service: str) -> FakeSecretsManagerClient:
        services.append(service)
        return client

    monkeypatch.setattr(
        "foundry_onboarding.adapters.aws.secrets_manager.boto3.client",
        create_client,
    )

    store = create_secret_store()

    assert store.client is client
    assert services == ["secretsmanager"]
