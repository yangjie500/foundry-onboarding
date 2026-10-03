from collections.abc import Mapping

import pytest
import yaml
from pydantic import ValidationError

from infrastructure.configuration import (
    EnvironmentConfig,
    EnvironmentName,
    load_environment_config,
)


def _valid_config() -> dict[str, object]:
    return {
        "environment": "dev",
        "aws_region": "us-east-1",
        "lambda_function": {
            "memory_size_mb": 256,
            "timeout_seconds": 30,
        },
        "workflow": {
            "timeout_seconds": 300,
            "retry": {
                "interval_seconds": 2,
                "max_attempts": 3,
                "backoff_rate": 2.0,
            },
        },
        "observability": {
            "log_retention_days": 14,
            "enable_tracing": True,
            "workflow_log_level": "ALL",
        },
        "ingestion": {
            "sqs": {
                "mode": "development",
                "batch_size": 10,
                "visibility_timeout_seconds": 180,
                "message_retention_days": 4,
                "dead_letter_retention_days": 14,
                "max_receive_count": 5,
            }
        },
        "parameters": {
            "generic_variable_name": "/foundry/dev/generic/example-variable",
            "generic_variable_value": "hello-from-dev-parameter-store",
            "generic_secret_name": "/foundry/dev/generic/example-secret",
        },
        "integrations": {
            "gitlab": {
                "base_url_parameter_name": "/foundry/dev/gitlab/base-url",
                "api_token_parameter_name": "/foundry/dev/gitlab/api-token",
                "tls_verify": False,
            }
        },
    }


@pytest.mark.parametrize(
    ("environment", "retention_days", "workflow_log_level"),
    [
        ("dev", 14, "ALL"),
        ("staging", 30, "ALL"),
        ("production", 90, "ERROR"),
    ],
)
def test_load_environment_config(
    environment: EnvironmentName,
    retention_days: int,
    workflow_log_level: str,
) -> None:
    config = load_environment_config(environment)

    assert config.environment == environment
    assert config.lambda_function.memory_size_mb == 256
    assert config.lambda_function.timeout_seconds == 30
    assert config.workflow.timeout_seconds == 300
    assert config.workflow.retry.max_attempts == 3
    assert config.observability.log_retention_days == retention_days
    assert config.observability.workflow_log_level == workflow_log_level
    expected_mode = "development" if environment == "dev" else "disabled"
    assert config.ingestion.sqs.mode == expected_mode
    assert config.ingestion.sqs.batch_size == 10
    assert config.ingestion.sqs.visibility_timeout_seconds == 180
    assert config.ingestion.sqs.message_retention_days == 4
    assert config.ingestion.sqs.dead_letter_retention_days == 14
    assert config.ingestion.sqs.max_receive_count == 5
    assert config.parameters.generic_variable_name == (
        f"/foundry/{environment}/generic/example-variable"
    )
    assert config.parameters.generic_secret_name == (
        f"/foundry/{environment}/generic/example-secret"
    )
    assert config.integrations.gitlab.base_url_parameter_name == (
        f"/foundry/{environment}/gitlab/base-url"
    )
    assert config.integrations.gitlab.api_token_parameter_name == (
        f"/foundry/{environment}/gitlab/api-token"
    )
    assert config.integrations.gitlab.ca_bundle_parameter_name is None
    assert config.integrations.gitlab.tls_verify is (environment != "dev")


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("lambda_function", "memory_size_mb", 127),
        ("lambda_function", "timeout_seconds", 901),
        ("workflow", "timeout_seconds", 0),
        ("observability", "log_retention_days", 7),
        ("observability", "workflow_log_level", "DEBUG"),
        ("ingestion.sqs", "visibility_timeout_seconds", 43_201),
        ("ingestion.sqs", "batch_size", 0),
        ("ingestion.sqs", "message_retention_days", 15),
        ("ingestion.sqs", "dead_letter_retention_days", 0),
        ("ingestion.sqs", "max_receive_count", 0),
        ("parameters", "generic_variable_name", "missing-leading-slash"),
        ("parameters", "generic_variable_value", ""),
        ("parameters", "generic_secret_name", "missing-leading-slash"),
        ("integrations.gitlab", "base_url_parameter_name", "missing-leading-slash"),
        ("integrations.gitlab", "api_token_parameter_name", "missing-leading-slash"),
        ("integrations.gitlab", "ca_bundle_parameter_name", "missing-leading-slash"),
    ],
)
def test_environment_config_rejects_invalid_settings(
    section: str,
    field: str,
    value: object,
) -> None:
    raw_config = _valid_config()
    section_config: object = raw_config
    for section_name in section.split("."):
        assert isinstance(section_config, dict)
        section_config = section_config[section_name]
    assert isinstance(section_config, dict)
    section_config[field] = value

    with pytest.raises(ValidationError):
        EnvironmentConfig.model_validate(raw_config)


def test_environment_config_rejects_invalid_retry_settings() -> None:
    raw_config = _valid_config()
    workflow = raw_config["workflow"]
    assert isinstance(workflow, dict)
    retry = workflow["retry"]
    assert isinstance(retry, dict)
    retry["max_attempts"] = -1

    with pytest.raises(ValidationError):
        EnvironmentConfig.model_validate(raw_config)


def test_environment_config_rejects_duplicate_parameter_names() -> None:
    raw_config = _valid_config()
    parameters = raw_config["parameters"]
    assert isinstance(parameters, dict)
    parameters["generic_secret_name"] = parameters["generic_variable_name"]

    with pytest.raises(ValidationError, match="generic parameter names must be distinct"):
        EnvironmentConfig.model_validate(raw_config)


def test_environment_config_rejects_duplicate_gitlab_parameter_names() -> None:
    raw_config = _valid_config()
    integrations = raw_config["integrations"]
    assert isinstance(integrations, dict)
    gitlab = integrations["gitlab"]
    assert isinstance(gitlab, dict)
    gitlab["api_token_parameter_name"] = gitlab["base_url_parameter_name"]

    with pytest.raises(ValidationError, match="GitLab parameter names must be distinct"):
        EnvironmentConfig.model_validate(raw_config)


@pytest.mark.parametrize("duplicate_field", ["base_url_parameter_name", "api_token_parameter_name"])
def test_environment_config_rejects_duplicate_gitlab_ca_parameter_name(
    duplicate_field: str,
) -> None:
    raw_config = _valid_config()
    integrations = raw_config["integrations"]
    assert isinstance(integrations, dict)
    gitlab = integrations["gitlab"]
    assert isinstance(gitlab, dict)
    gitlab["tls_verify"] = True
    gitlab["ca_bundle_parameter_name"] = gitlab[duplicate_field]

    with pytest.raises(ValidationError, match="GitLab parameter names must be distinct"):
        EnvironmentConfig.model_validate(raw_config)


def test_environment_config_rejects_custom_ca_when_tls_verification_is_disabled() -> None:
    raw_config = _valid_config()
    integrations = raw_config["integrations"]
    assert isinstance(integrations, dict)
    gitlab = integrations["gitlab"]
    assert isinstance(gitlab, dict)
    gitlab["ca_bundle_parameter_name"] = "/foundry/dev/gitlab/ca-bundle"

    with pytest.raises(ValidationError, match="GitLab custom CA requires TLS verification"):
        EnvironmentConfig.model_validate(raw_config)


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_environment_config_rejects_disabled_gitlab_tls_outside_development(
    environment: str,
) -> None:
    raw_config = _valid_config()
    raw_config["environment"] = environment

    with pytest.raises(
        ValidationError,
        match="GitLab TLS verification can be disabled only in development",
    ):
        EnvironmentConfig.model_validate(raw_config)


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_environment_config_rejects_development_mode_outside_development(
    environment: str,
) -> None:
    raw_config = _valid_config()
    raw_config["environment"] = environment
    integrations = raw_config["integrations"]
    assert isinstance(integrations, dict)
    gitlab = integrations["gitlab"]
    assert isinstance(gitlab, dict)
    gitlab["tls_verify"] = True

    with pytest.raises(
        ValidationError,
        match="development SQS mode can be used only in development",
    ):
        EnvironmentConfig.model_validate(raw_config)


def test_environment_config_rejects_short_sqs_visibility_timeout() -> None:
    raw_config = _valid_config()
    ingestion = raw_config["ingestion"]
    assert isinstance(ingestion, dict)
    sqs = ingestion["sqs"]
    assert isinstance(sqs, dict)
    sqs["visibility_timeout_seconds"] = 179

    with pytest.raises(
        ValidationError,
        match="SQS visibility timeout must be at least six times Lambda timeout",
    ):
        EnvironmentConfig.model_validate(raw_config)


def test_environment_config_ignores_queue_timeout_when_queue_is_not_provisioned() -> None:
    raw_config = _valid_config()
    ingestion = raw_config["ingestion"]
    assert isinstance(ingestion, dict)
    sqs = ingestion["sqs"]
    assert isinstance(sqs, dict)
    sqs["mode"] = "disabled"
    sqs["visibility_timeout_seconds"] = 1

    config = EnvironmentConfig.model_validate(raw_config)

    assert config.ingestion.sqs.visibility_timeout_seconds == 1


def test_environment_config_rejects_short_dead_letter_retention() -> None:
    raw_config = _valid_config()
    ingestion = raw_config["ingestion"]
    assert isinstance(ingestion, dict)
    sqs = ingestion["sqs"]
    assert isinstance(sqs, dict)
    sqs["message_retention_days"] = 10
    sqs["dead_letter_retention_days"] = 9

    with pytest.raises(
        ValidationError,
        match="SQS dead-letter retention must cover source retention",
    ):
        EnvironmentConfig.model_validate(raw_config)


def test_environment_config_requires_settings_for_external_sqs_mode() -> None:
    raw_config = _valid_config()
    sqs = raw_config["ingestion"]["sqs"]  # type: ignore[index]
    assert isinstance(sqs, dict)
    sqs["mode"] = "external"

    with pytest.raises(ValidationError, match="external SQS mode requires external settings"):
        EnvironmentConfig.model_validate(raw_config)


def test_environment_config_rejects_external_settings_in_disabled_mode() -> None:
    raw_config = _valid_config()
    sqs = raw_config["ingestion"]["sqs"]  # type: ignore[index]
    assert isinstance(sqs, dict)
    sqs["mode"] = "disabled"
    sqs["external"] = {
        "queue_arn": "arn:aws:sqs:us-east-1:222222222222:onboarding",
    }

    with pytest.raises(ValidationError, match="external SQS settings require external mode"):
        EnvironmentConfig.model_validate(raw_config)


def test_environment_config_accepts_external_sqs_outside_development() -> None:
    raw_config = _valid_config()
    raw_config["environment"] = "staging"
    gitlab = raw_config["integrations"]["gitlab"]  # type: ignore[index]
    assert isinstance(gitlab, dict)
    gitlab["tls_verify"] = True
    sqs = raw_config["ingestion"]["sqs"]  # type: ignore[index]
    assert isinstance(sqs, dict)
    sqs["mode"] = "external"
    sqs["external"] = {
        "queue_arn": "arn:aws:sqs:us-east-1:222222222222:onboarding",
        "kms_key_arn": (
            "arn:aws:kms:us-east-1:222222222222:key/11111111-2222-3333-4444-555555555555"
        ),
        "event_source_mapping_enabled": False,
    }

    config = EnvironmentConfig.model_validate(raw_config)

    assert config.ingestion.sqs.external is not None
    assert config.ingestion.sqs.external.event_source_mapping_enabled is False


@pytest.mark.parametrize(
    ("key_arn", "expected_error"),
    [
        (
            "arn:aws:kms:us-east-1:222222222222:alias/aws/sqs",
            "external SQS KMS key ARN must identify a customer managed key",
        ),
        (
            "arn:aws:kms:us-east-1:333333333333:key/11111111-2222-3333-4444-555555555555",
            "external SQS queue and KMS key must share partition, region, and account",
        ),
    ],
)
def test_environment_config_rejects_invalid_external_kms_key(
    key_arn: str,
    expected_error: str,
) -> None:
    raw_config = _valid_config()
    raw_config["environment"] = "staging"
    gitlab = raw_config["integrations"]["gitlab"]  # type: ignore[index]
    assert isinstance(gitlab, dict)
    gitlab["tls_verify"] = True
    sqs = raw_config["ingestion"]["sqs"]  # type: ignore[index]
    assert isinstance(sqs, dict)
    sqs["mode"] = "external"
    sqs["external"] = {
        "queue_arn": "arn:aws:sqs:us-east-1:222222222222:onboarding",
        "kms_key_arn": key_arn,
    }

    with pytest.raises(ValidationError, match=expected_error):
        EnvironmentConfig.model_validate(raw_config)


@pytest.mark.parametrize(
    ("queue_arn", "expected_error"),
    [
        ("not-an-arn", "external SQS queue ARN is invalid"),
        (
            "arn:aws:sqs:us-east-1:222222222222:onboarding.fifo",
            "external SQS queue must be a Standard queue",
        ),
        (
            "arn:aws:sqs:us-west-2:222222222222:onboarding",
            "external SQS queue must be in the configured AWS Region",
        ),
    ],
)
def test_environment_config_rejects_invalid_external_queue(
    queue_arn: str,
    expected_error: str,
) -> None:
    raw_config = _valid_config()
    raw_config["environment"] = "staging"
    gitlab = raw_config["integrations"]["gitlab"]  # type: ignore[index]
    assert isinstance(gitlab, dict)
    gitlab["tls_verify"] = True
    sqs = raw_config["ingestion"]["sqs"]  # type: ignore[index]
    assert isinstance(sqs, dict)
    sqs["mode"] = "external"
    sqs["external"] = {"queue_arn": queue_arn}

    with pytest.raises(ValidationError, match=expected_error):
        EnvironmentConfig.model_validate(raw_config)


def test_environment_config_rejects_external_sqs_in_development() -> None:
    raw_config = _valid_config()
    sqs = raw_config["ingestion"]["sqs"]  # type: ignore[index]
    assert isinstance(sqs, dict)
    sqs["mode"] = "external"
    sqs["external"] = {
        "queue_arn": "arn:aws:sqs:us-east-1:222222222222:onboarding",
    }

    with pytest.raises(ValidationError, match="external SQS mode cannot be used in development"):
        EnvironmentConfig.model_validate(raw_config)


def test_environment_config_rejects_unknown_fields() -> None:
    raw_config = _valid_config()
    raw_config["secret"] = "must not be accepted"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        EnvironmentConfig.model_validate(raw_config)


def test_environment_config_is_immutable() -> None:
    config = EnvironmentConfig.model_validate(_valid_config())

    with pytest.raises(ValidationError, match="Instance is frozen"):
        config.aws_region = "us-west-2"


def test_loaded_environment_must_match_requested_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_config = _valid_config()
    raw_config["environment"] = "staging"
    integrations = raw_config["integrations"]
    assert isinstance(integrations, dict)
    gitlab = integrations["gitlab"]
    assert isinstance(gitlab, dict)
    gitlab["tls_verify"] = True
    ingestion = raw_config["ingestion"]
    assert isinstance(ingestion, dict)
    sqs = ingestion["sqs"]
    assert isinstance(sqs, dict)
    sqs["mode"] = "disabled"

    def fake_safe_load(_stream: object) -> Mapping[str, object]:
        return raw_config

    monkeypatch.setattr(yaml, "safe_load", fake_safe_load)

    with pytest.raises(
        ValueError,
        match="Configuration environment 'staging' does not match requested environment 'dev'",
    ):
        load_environment_config("dev")
