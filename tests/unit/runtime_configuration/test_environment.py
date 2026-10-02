import pytest

from foundry_onboarding.errors import ConfigurationError
from foundry_onboarding.runtime_configuration.environment import (
    optional_environment_variable,
)


def test_optional_environment_variable_returns_none_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPTIONAL_SETTING", raising=False)

    assert optional_environment_variable("OPTIONAL_SETTING") is None


def test_optional_environment_variable_returns_configured_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPTIONAL_SETTING", "configured-value")

    assert optional_environment_variable("OPTIONAL_SETTING") == "configured-value"


def test_optional_environment_variable_rejects_blank_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPTIONAL_SETTING", "   ")

    with pytest.raises(ConfigurationError, match="OPTIONAL_SETTING must not be blank"):
        optional_environment_variable("OPTIONAL_SETTING")
