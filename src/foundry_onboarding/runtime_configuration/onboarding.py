from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from foundry_onboarding.adapters.aws.parameter_store import (
    ParameterStore,
    create_parameter_store,
)
from foundry_onboarding.errors import ConfigurationError
from foundry_onboarding.runtime_configuration.environment import (
    required_environment_variable,
)
from foundry_onboarding.services.onboarding_policy import normalize_email_domain

ALLOWED_EMAIL_DOMAINS_PARAMETER_ENV = "ALLOWED_EMAIL_DOMAINS_PARAMETER_NAME"


class OnboardingPolicyConfiguration(BaseModel):
    """Validated business policy applied before provider provisioning."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed_email_domains: tuple[str, ...] = Field(min_length=1)

    @field_validator("allowed_email_domains", mode="before")
    @classmethod
    def parse_allowed_domains(cls, value: object) -> object:
        if not isinstance(value, str):
            return value

        return tuple(domain.strip() for domain in value.split(","))

    @field_validator("allowed_email_domains")
    @classmethod
    def normalize_allowed_domains(cls, domains: tuple[str, ...]) -> tuple[str, ...]:
        try:
            normalized = tuple(normalize_email_domain(domain) for domain in domains)
        except ValueError:
            raise ValueError("allowed email domains are invalid") from None

        if len(set(normalized)) != len(normalized):
            raise ValueError("allowed email domains must be distinct")

        return normalized


def _create_parameter_store() -> ParameterStore:
    return create_parameter_store()


def load_onboarding_policy_configuration() -> OnboardingPolicyConfiguration:
    """Load the current email-domain allowlist from Parameter Store."""

    parameter_name = required_environment_variable(ALLOWED_EMAIL_DOMAINS_PARAMETER_ENV)
    values = _create_parameter_store().get_parameters(
        [parameter_name],
        with_decryption=False,
    )

    try:
        return OnboardingPolicyConfiguration.model_validate(
            {"allowed_email_domains": values[parameter_name]}
        )
    except ValidationError:
        raise ConfigurationError("Onboarding policy configuration is invalid") from None
