from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

EnvironmentName = Literal["dev", "staging", "production"]
WorkflowLogLevel = Literal["ALL", "ERROR", "FATAL", "OFF"]


class SettingsModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LambdaSettings(SettingsModel):
    memory_size_mb: int = Field(ge=128, le=10_240)
    timeout_seconds: int = Field(ge=1, le=900)


class RetrySettings(SettingsModel):
    interval_seconds: int = Field(ge=1, le=900)
    max_attempts: int = Field(ge=0, le=10)
    backoff_rate: float = Field(ge=1.0, le=10.0)


class WorkflowSettings(SettingsModel):
    timeout_seconds: int = Field(ge=1, le=86_400)
    retry: RetrySettings


class ObservabilitySettings(SettingsModel):
    log_retention_days: Literal[14, 30, 90]
    enable_tracing: bool
    workflow_log_level: WorkflowLogLevel


class ParameterSettings(SettingsModel):
    generic_variable_name: str = Field(
        min_length=2,
        max_length=1_011,
        pattern=r"^/[A-Za-z0-9_.\-/]+$",
    )
    generic_variable_value: str = Field(min_length=1, max_length=256)
    generic_secret_name: str = Field(
        min_length=2,
        max_length=1_011,
        pattern=r"^/[A-Za-z0-9_.\-/]+$",
    )

    @model_validator(mode="after")
    def parameter_names_must_be_distinct(self) -> Self:
        if self.generic_variable_name == self.generic_secret_name:
            raise ValueError("generic parameter names must be distinct")

        return self


class GitLabSettings(SettingsModel):
    base_url_parameter_name: str = Field(
        min_length=2,
        max_length=1_011,
        pattern=r"^/[A-Za-z0-9_.\-/]+$",
    )
    api_token_parameter_name: str = Field(
        min_length=2,
        max_length=1_011,
        pattern=r"^/[A-Za-z0-9_.\-/]+$",
    )
    tls_verify: bool = True

    @model_validator(mode="after")
    def parameter_names_must_be_distinct(self) -> Self:
        if self.base_url_parameter_name == self.api_token_parameter_name:
            raise ValueError("GitLab parameter names must be distinct")

        return self


class IntegrationSettings(SettingsModel):
    gitlab: GitLabSettings


class EnvironmentConfig(SettingsModel):
    environment: EnvironmentName
    aws_region: str = Field(min_length=1)
    lambda_function: LambdaSettings
    workflow: WorkflowSettings
    observability: ObservabilitySettings
    parameters: ParameterSettings
    integrations: IntegrationSettings

    @model_validator(mode="after")
    def insecure_gitlab_tls_is_development_only(self) -> Self:
        if self.environment != "dev" and not self.integrations.gitlab.tls_verify:
            raise ValueError("GitLab TLS verification can be disabled only in development")

        return self


def load_environment_config(environment: EnvironmentName) -> EnvironmentConfig:
    config_path = Path(__file__).parent.parent / "config" / f"{environment}.yaml"

    with config_path.open(encoding="utf-8") as config_file:
        raw_config = yaml.safe_load(config_file)

    config = EnvironmentConfig.model_validate(raw_config)

    if config.environment != environment:
        raise ValueError(
            f"Configuration environment {config.environment!r} does not match "
            f"requested environment {environment!r}"
        )

    return config
