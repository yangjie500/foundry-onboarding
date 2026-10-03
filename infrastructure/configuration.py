import re
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

EnvironmentName = Literal["dev", "staging", "production"]
WorkflowLogLevel = Literal["ALL", "ERROR", "FATAL", "OFF"]
SqsIngestionMode = Literal["disabled", "development", "external"]

_SQS_QUEUE_ARN = re.compile(
    r"^arn:(?P<partition>aws(?:-[a-z]+)*):sqs:(?P<region>[^:]+):"
    r"(?P<account>\d{12}):(?P<name>[A-Za-z0-9_-]{1,80}(?:\.fifo)?)$"
)
_KMS_KEY_ARN = re.compile(
    r"^arn:(?P<partition>aws(?:-[a-z]+)*):kms:(?P<region>[^:]+):"
    r"(?P<account>\d{12}):key/(?P<key_id>[A-Za-z0-9-]+)$"
)


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


class ExternalSqsSettings(SettingsModel):
    queue_arn: str
    kms_key_arn: str | None = None
    event_source_mapping_enabled: bool = False

    @model_validator(mode="after")
    def validate_external_queue(self) -> Self:
        queue_match = _SQS_QUEUE_ARN.fullmatch(self.queue_arn)
        if queue_match is None:
            raise ValueError("external SQS queue ARN is invalid")
        if queue_match.group("name").endswith(".fifo"):
            raise ValueError("external SQS queue must be a Standard queue")

        if self.kms_key_arn is not None:
            key_match = _KMS_KEY_ARN.fullmatch(self.kms_key_arn)
            if key_match is None:
                raise ValueError("external SQS KMS key ARN must identify a customer managed key")
            if (
                key_match.group("partition") != queue_match.group("partition")
                or key_match.group("region") != queue_match.group("region")
                or key_match.group("account") != queue_match.group("account")
            ):
                raise ValueError(
                    "external SQS queue and KMS key must share partition, region, and account"
                )

        return self


class SqsIngestionSettings(SettingsModel):
    mode: SqsIngestionMode
    external: ExternalSqsSettings | None = None
    batch_size: int = Field(default=10, ge=1, le=10)
    visibility_timeout_seconds: int = Field(default=180, ge=1, le=43_200)
    message_retention_days: int = Field(default=4, ge=1, le=14)
    dead_letter_retention_days: int = Field(default=14, ge=1, le=14)
    max_receive_count: int = Field(default=5, ge=1, le=1_000)

    @model_validator(mode="after")
    def validate_mode_settings(self) -> Self:
        if self.mode == "external" and self.external is None:
            raise ValueError("external SQS mode requires external settings")
        if self.mode != "external" and self.external is not None:
            raise ValueError("external SQS settings require external mode")
        if (
            self.mode == "development"
            and self.dead_letter_retention_days < self.message_retention_days
        ):
            raise ValueError("SQS dead-letter retention must cover source retention")

        return self


class IngestionSettings(SettingsModel):
    sqs: SqsIngestionSettings


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
    ca_bundle_parameter_name: str | None = Field(
        default=None,
        min_length=2,
        max_length=1_011,
        pattern=r"^/[A-Za-z0-9_.\-/]+$",
    )
    tls_verify: bool = True

    @model_validator(mode="after")
    def validate_gitlab_settings(self) -> Self:
        parameter_names = {
            self.base_url_parameter_name,
            self.api_token_parameter_name,
        }
        if self.ca_bundle_parameter_name is not None:
            parameter_names.add(self.ca_bundle_parameter_name)

        expected_parameter_count = 3 if self.ca_bundle_parameter_name is not None else 2
        if len(parameter_names) != expected_parameter_count:
            raise ValueError("GitLab parameter names must be distinct")
        if self.ca_bundle_parameter_name is not None and not self.tls_verify:
            raise ValueError("GitLab custom CA requires TLS verification")

        return self


class IntegrationSettings(SettingsModel):
    gitlab: GitLabSettings


class EnvironmentConfig(SettingsModel):
    environment: EnvironmentName
    aws_region: str = Field(min_length=1)
    lambda_function: LambdaSettings
    workflow: WorkflowSettings
    observability: ObservabilitySettings
    ingestion: IngestionSettings
    parameters: ParameterSettings
    integrations: IntegrationSettings

    @model_validator(mode="after")
    def validate_environment_settings(self) -> Self:
        if self.environment != "dev" and not self.integrations.gitlab.tls_verify:
            raise ValueError("GitLab TLS verification can be disabled only in development")
        sqs_settings = self.ingestion.sqs
        if self.environment != "dev" and sqs_settings.mode == "development":
            raise ValueError("development SQS mode can be used only in development")
        if self.environment == "dev" and sqs_settings.mode == "external":
            raise ValueError("external SQS mode cannot be used in development")
        if sqs_settings.external is not None:
            queue_match = _SQS_QUEUE_ARN.fullmatch(sqs_settings.external.queue_arn)
            if queue_match is None or queue_match.group("region") != self.aws_region:
                raise ValueError("external SQS queue must be in the configured AWS Region")
        minimum_visibility_timeout = self.lambda_function.timeout_seconds * 6
        if (
            sqs_settings.mode == "development"
            and sqs_settings.visibility_timeout_seconds < minimum_visibility_timeout
        ):
            raise ValueError("SQS visibility timeout must be at least six times Lambda timeout")

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
