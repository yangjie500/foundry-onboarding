from aws_cdk import RemovalPolicy
from aws_cdk import aws_logs as logs

from infrastructure.configuration import EnvironmentConfig

_RETENTION_BY_DAYS = {
    14: logs.RetentionDays.TWO_WEEKS,
    30: logs.RetentionDays.ONE_MONTH,
    90: logs.RetentionDays.THREE_MONTHS,
}

def log_retention_for(config: EnvironmentConfig) -> logs.RetentionDays:
    """Return the CDK retention value selected by application configuration."""

    try:
        return _RETENTION_BY_DAYS[config.log_retention_days]
    except KeyError as error:
        supported_days = ", ".join(str(days) for days in sorted(_RETENTION_BY_DAYS))
        raise ValueError(
            f"Unsupported log retention of {config.log_retention_days} days; "
            f"expected one of: {supported_days}"
        ) from error


def log_removal_policy_for(config: EnvironmentConfig) -> RemovalPolicy:
    """Retain production logs and remove logs for non-production stacks."""

    if config.environment == "production":
        return RemovalPolicy.RETAIN

    return RemovalPolicy.DESTROY
