from collections.abc import Mapping

import pytest
from pydantic import ValidationError

from foundry_onboarding.errors import ConfigurationError
from foundry_onboarding.runtime_configuration import gitlab

BASE_URL_PARAMETER_NAME = "/foundry/dev/gitlab/base-url"
API_TOKEN_PARAMETER_NAME = "/foundry/dev/gitlab/api-token"
API_TOKEN = "glpat-not-a-real-token"


class FakeParameterStore:
    def __init__(self, values: Mapping[str, str] | None = None) -> None:
        self.values = dict(
            values
            or {
                BASE_URL_PARAMETER_NAME: "https://gitlab.example.com",
                API_TOKEN_PARAMETER_NAME: API_TOKEN,
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


def _configure_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(gitlab.BASE_URL_PARAMETER_ENV, BASE_URL_PARAMETER_NAME)
    monkeypatch.setenv(gitlab.API_TOKEN_PARAMETER_ENV, API_TOKEN_PARAMETER_NAME)
    monkeypatch.setenv(gitlab.TLS_VERIFY_ENV, "false")


@pytest.mark.parametrize(
    "missing_environment",
    [gitlab.BASE_URL_PARAMETER_ENV, gitlab.API_TOKEN_PARAMETER_ENV],
)
def test_load_configuration_requires_parameter_name_environment_variables(
    monkeypatch: pytest.MonkeyPatch,
    missing_environment: str,
) -> None:
    _configure_environment(monkeypatch)
    monkeypatch.delenv(missing_environment)

    with pytest.raises(ConfigurationError, match=missing_environment):
        gitlab.load_gitlab_configuration()


def test_load_configuration_retrieves_both_parameters_with_decryption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FakeParameterStore()
    _configure_environment(monkeypatch)
    monkeypatch.setattr(gitlab, "_create_parameter_store", lambda: store)

    configuration = gitlab.load_gitlab_configuration()

    assert str(configuration.base_url) == "https://gitlab.example.com/"
    assert configuration.api_token.get_secret_value() == API_TOKEN
    assert configuration.tls_verify is False
    assert store.calls == [([BASE_URL_PARAMETER_NAME, API_TOKEN_PARAMETER_NAME], True)]


def test_configuration_masks_token_and_is_immutable() -> None:
    configuration = gitlab.GitLabConfiguration.model_validate(
        {
            "base_url": "https://gitlab.example.com",
            "api_token": API_TOKEN,
        }
    )

    assert API_TOKEN not in repr(configuration)
    assert "**********" in repr(configuration)
    with pytest.raises(ValidationError, match="Instance is frozen"):
        configuration.api_token = configuration.api_token


def test_tls_verification_defaults_to_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FakeParameterStore()
    _configure_environment(monkeypatch)
    monkeypatch.delenv(gitlab.TLS_VERIFY_ENV)
    monkeypatch.setattr(gitlab, "_create_parameter_store", lambda: store)

    configuration = gitlab.load_gitlab_configuration()

    assert configuration.tls_verify is True


@pytest.mark.parametrize(
    ("value", "expected"),
    [("true", True), (" TRUE ", True), ("false", False), (" FALSE ", False)],
)
def test_loader_parses_explicit_tls_verification_values(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
    expected: bool,
) -> None:
    store = FakeParameterStore()
    _configure_environment(monkeypatch)
    monkeypatch.setenv(gitlab.TLS_VERIFY_ENV, value)
    monkeypatch.setattr(gitlab, "_create_parameter_store", lambda: store)

    configuration = gitlab.load_gitlab_configuration()

    assert configuration.tls_verify is expected


@pytest.mark.parametrize("value", ["invalid", "1", "yes", ""])
def test_loader_rejects_invalid_tls_verification_values(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    _configure_environment(monkeypatch)
    monkeypatch.setenv(gitlab.TLS_VERIFY_ENV, value)

    with pytest.raises(ConfigurationError, match="must be true or false"):
        gitlab.load_gitlab_configuration()


@pytest.mark.parametrize(
    "base_url",
    [
        "http://gitlab.example.com",
        "gitlab.example.com",
        "https://user:password@gitlab.example.com",
        "https://gitlab.example.com?source=configuration",
        "https://gitlab.example.com#configuration",
        "https://gitlab.example.com/api/v4",
        "https://gitlab.example.com/api/v4/users",
    ],
)
def test_configuration_rejects_unsafe_or_invalid_base_urls(base_url: str) -> None:
    with pytest.raises(ValidationError):
        gitlab.GitLabConfiguration.model_validate({"base_url": base_url, "api_token": API_TOKEN})


@pytest.mark.parametrize("api_token", ["", "   "])
def test_configuration_rejects_empty_or_blank_tokens(api_token: str) -> None:
    with pytest.raises(ValidationError):
        gitlab.GitLabConfiguration.model_validate(
            {
                "base_url": "https://gitlab.example.com",
                "api_token": api_token,
            }
        )


def test_loader_translates_validation_errors_without_exposing_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FakeParameterStore(
        {
            BASE_URL_PARAMETER_NAME: "not-a-url",
            API_TOKEN_PARAMETER_NAME: API_TOKEN,
        }
    )
    _configure_environment(monkeypatch)
    monkeypatch.setattr(gitlab, "_create_parameter_store", lambda: store)

    with pytest.raises(
        ConfigurationError,
        match="GitLab runtime configuration is invalid",
    ) as raised:
        gitlab.load_gitlab_configuration()

    assert raised.value.__cause__ is None
    assert API_TOKEN not in str(raised.value)


def test_loader_fetches_current_values_on_each_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FakeParameterStore()
    _configure_environment(monkeypatch)
    monkeypatch.setattr(gitlab, "_create_parameter_store", lambda: store)

    first = gitlab.load_gitlab_configuration()
    store.values[API_TOKEN_PARAMETER_NAME] = "glpat-rotated-not-a-real-token"
    second = gitlab.load_gitlab_configuration()

    assert first.api_token.get_secret_value() == API_TOKEN
    assert second.api_token.get_secret_value() == "glpat-rotated-not-a-real-token"
    assert len(store.calls) == 2
