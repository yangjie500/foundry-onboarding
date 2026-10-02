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
    required_environment_variable,
)

BASE_URL_PARAMETER_ENV = "GITLAB_BASE_URL_PARAMETER_NAME"
API_TOKEN_PARAMETER_ENV = "GITLAB_API_TOKEN_PARAMETER_NAME"
TLS_VERIFY_ENV = "GITLAB_TLS_VERIFY"


class GitLabConfiguration(BaseModel):
    """Validated runtime values used to communicate with GitLab."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    base_url: HttpUrl
    api_token: Annotated[SecretStr, Field(min_length=1)]
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

        return self


def _create_parameter_store() -> ParameterStore:
    return create_parameter_store()


def load_gitlab_configuration() -> GitLabConfiguration:
    """Load and validate GitLab runtime configuration from Parameter Store."""

    base_url_parameter_name = required_environment_variable(BASE_URL_PARAMETER_ENV)
    api_token_parameter_name = required_environment_variable(API_TOKEN_PARAMETER_ENV)
    tls_verify = boolean_environment_variable(TLS_VERIFY_ENV, default=True)
    values = _create_parameter_store().get_parameters(
        [base_url_parameter_name, api_token_parameter_name],
        with_decryption=True,
    )

    try:
        return GitLabConfiguration.model_validate(
            {
                "base_url": values[base_url_parameter_name],
                "api_token": values[api_token_parameter_name],
                "tls_verify": tls_verify,
            }
        )
    except ValidationError:
        raise ConfigurationError("GitLab runtime configuration is invalid") from None
