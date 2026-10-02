from typing import Annotated, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    SecretStr,
    StrictBool,
    ValidationError,
    model_validator,
)

from foundry_onboarding.adapters.aws.parameter_store import (
    ParameterStore,
    create_parameter_store,
)
from foundry_onboarding.errors import ConfigurationError
from foundry_onboarding.runtime_configuration.environment import (
    boolean_environment_variable,
    optional_environment_variable,
    required_environment_variable,
)

BASE_URL_PARAMETER_ENV = "GITLAB_BASE_URL_PARAMETER_NAME"
API_TOKEN_PARAMETER_ENV = "GITLAB_API_TOKEN_PARAMETER_NAME"
CA_BUNDLE_PARAMETER_ENV = "GITLAB_CA_BUNDLE_PARAMETER_NAME"
TLS_VERIFY_ENV = "GITLAB_TLS_VERIFY"


class GitLabConfiguration(BaseModel):
    """Validated runtime values used to communicate with GitLab."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    base_url: HttpUrl
    api_token: Annotated[SecretStr, Field(min_length=1)]
    ca_bundle_pem: str | None = Field(default=None, min_length=1, repr=False)
    tls_verify: StrictBool = True

    @model_validator(mode="after")
    def validate_gitlab_configuration(self) -> Self:
        if self.base_url.scheme != "https":
            raise ValueError("GitLab base URL must use HTTPS")
        if self.base_url.username is not None or self.base_url.password is not None:
            raise ValueError("GitLab base URL must not contain credentials")
        if self.base_url.query is not None or self.base_url.fragment is not None:
            raise ValueError("GitLab base URL must not contain a query or fragment")

        normalized_path = (self.base_url.path or "").rstrip("/")
        if normalized_path.endswith("/api/v4") or normalized_path.endswith("/api/v4/users"):
            raise ValueError("GitLab base URL must not contain an API endpoint path")
        if not self.api_token.get_secret_value().strip():
            raise ValueError("GitLab API token must not be blank")
        if self.ca_bundle_pem is not None and not self.ca_bundle_pem.strip():
            raise ValueError("GitLab CA bundle must not be blank")
        if self.ca_bundle_pem is not None and not self.tls_verify:
            raise ValueError("GitLab custom CA requires TLS verification")

        return self


def _create_parameter_store() -> ParameterStore:
    return create_parameter_store()


def load_gitlab_configuration() -> GitLabConfiguration:
    """Load and validate GitLab runtime configuration from Parameter Store."""

    base_url_parameter_name = required_environment_variable(BASE_URL_PARAMETER_ENV)
    api_token_parameter_name = required_environment_variable(API_TOKEN_PARAMETER_ENV)
    ca_bundle_parameter_name = optional_environment_variable(CA_BUNDLE_PARAMETER_ENV)
    tls_verify = boolean_environment_variable(TLS_VERIFY_ENV, default=True)
    parameter_names = [base_url_parameter_name, api_token_parameter_name]
    if ca_bundle_parameter_name is not None:
        parameter_names.append(ca_bundle_parameter_name)

    values = _create_parameter_store().get_parameters(
        parameter_names,
        with_decryption=True,
    )

    try:
        return GitLabConfiguration.model_validate(
            {
                "base_url": values[base_url_parameter_name],
                "api_token": values[api_token_parameter_name],
                "ca_bundle_pem": (
                    values[ca_bundle_parameter_name]
                    if ca_bundle_parameter_name is not None
                    else None
                ),
                "tls_verify": tls_verify,
            }
        )
    except ValidationError:
        raise ConfigurationError("GitLab runtime configuration is invalid") from None
