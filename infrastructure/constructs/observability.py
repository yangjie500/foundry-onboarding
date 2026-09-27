from aws_cdk import RemovalPolicy
from aws_cdk import aws_logs as logs
from aws_cdk import aws_stepfunctions as sfn

from infrastructure.configuration import EnvironmentConfig

_RETENTION_BY_DAYS = {
    14: logs.RetentionDays.TWO_WEEKS,
    30: logs.RetentionDays.ONE_MONTH,
    90: logs.RetentionDays.THREE_MONTHS,
}

_WORKFLOW_LOG_LEVELS = {
    "ALL": sfn.LogLevel.ALL,
    "ERROR": sfn.LogLevel.ERROR,
    "FATAL": sfn.LogLevel.FATAL,
    "OFF": sfn.LogLevel.OFF,
}

def log_retention_for(config: EnvironmentConfig) -> logs.RetentionDays:
    """Return the CDK retention value selected by application configuration."""

    return _RETENTION_BY_DAYS[config.observability.log_retention_days]


def log_removal_policy_for(config: EnvironmentConfig) -> RemovalPolicy:
    """Retain production logs and remove logs for non-production stacks."""

    if config.environment == "production":
        return RemovalPolicy.RETAIN

    return RemovalPolicy.DESTROY


def workflow_log_level_for(config: EnvironmentConfig) -> sfn.LogLevel:
    """Return the Step Functions log level selected for the environment."""

    return _WORKFLOW_LOG_LEVELS[config.observability.workflow_log_level]
