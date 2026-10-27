from collections.abc import Mapping

import pytest
from pydantic import ValidationError

from foundry_onboarding.errors import ConfigurationError
from foundry_onboarding.runtime_configuration import onboarding

PARAMETER_NAME = "/foundry/dev/onboarding/allowed-email-domains"


class FakeParameterStore:
    def __init__(self, values: Mapping[str, str] | None = None) -> None:
        self.values = dict(values or {PARAMETER_NAME: "example.com, subsidiary.example.com"})
        self.calls: list[tuple[list[str], bool]] = []

    def get_parameters(
        self,
        names: list[str],
        *,
        with_decryption: bool = False,
    ) -> dict[str, str]:
        self.calls.append((names, with_decryption))
        return self.values


def test_loader_retrieves_and_normalizes_allowed_domains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FakeParameterStore()
    monkeypatch.setenv(onboarding.ALLOWED_EMAIL_DOMAINS_PARAMETER_ENV, PARAMETER_NAME)
    monkeypatch.setattr(onboarding, "_create_parameter_store", lambda: store)

    configuration = onboarding.load_onboarding_policy_configuration()

    assert configuration.allowed_email_domains == (
        "example.com",
        "subsidiary.example.com",
    )
    assert store.calls == [([PARAMETER_NAME], False)]


def test_loader_requires_parameter_name_environment_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(onboarding.ALLOWED_EMAIL_DOMAINS_PARAMETER_ENV, raising=False)

    with pytest.raises(
        ConfigurationError,
        match=onboarding.ALLOWED_EMAIL_DOMAINS_PARAMETER_ENV,
    ):
        onboarding.load_onboarding_policy_configuration()


@pytest.mark.parametrize(
    "value",
    ["", "   ", "example.com,", "*.example.com", "example.com,EXAMPLE.COM"],
)
def test_loader_rejects_invalid_or_duplicate_allowed_domains(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    store = FakeParameterStore({PARAMETER_NAME: value})
    monkeypatch.setenv(onboarding.ALLOWED_EMAIL_DOMAINS_PARAMETER_ENV, PARAMETER_NAME)
    monkeypatch.setattr(onboarding, "_create_parameter_store", lambda: store)

    with pytest.raises(
        ConfigurationError,
        match="Onboarding policy configuration is invalid",
    ) as raised:
        onboarding.load_onboarding_policy_configuration()

    assert raised.value.__cause__ is None
    if value:
        assert value not in str(raised.value)


def test_configuration_is_immutable() -> None:
    configuration = onboarding.OnboardingPolicyConfiguration.model_validate(
        {"allowed_email_domains": "example.com"}
    )

    with pytest.raises(ValidationError, match="Instance is frozen"):
        configuration.allowed_email_domains = ("other.example",)
