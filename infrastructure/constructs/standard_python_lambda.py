from aws_cdk import Duration, RemovalPolicy
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from constructs import Construct

from infrastructure.configuration import EnvironmentConfig

_RETENTION_BY_DAYS = {
    14: logs.RetentionDays.TWO_WEEKS,
    30: logs.RetentionDays.ONE_MONTH,
    90: logs.RetentionDays.THREE_MONTHS,
}


class StandardPythonLambda(Construct):
    """A Python Lambda with the operational defaults shared by this application."""

    function: lambda_.Function
    log_group: logs.LogGroup

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        function_name: str,
        handler: str,
        code: lambda_.Code,
        config: EnvironmentConfig,
        description: str,
    ) -> None:
        super().__init__(scope, construct_id)

        try:
            retention = _RETENTION_BY_DAYS[config.log_retention_days]
        except KeyError as error:
            supported_days = ", ".join(str(days) for days in sorted(_RETENTION_BY_DAYS))
            raise ValueError(
                f"Unsupported log retention of {config.log_retention_days} days; "
                f"expected one of: {supported_days}"
            ) from error

        removal_policy = (
            RemovalPolicy.RETAIN
            if config.environment == "production"
            else RemovalPolicy.DESTROY
        )

        self.log_group = logs.LogGroup(
            self,
            "LogGroup",
            log_group_name=f"/aws/lambda/{function_name}",
            retention=retention,
            removal_policy=removal_policy,
        )

        self.function = lambda_.Function(
            self,
            "Function",
            function_name=function_name,
            description=description,
            runtime=lambda_.Runtime.PYTHON_3_14,
            architecture=lambda_.Architecture.X86_64,
            handler=handler,
            code=code,
            memory_size=256,
            timeout=Duration.seconds(30),
            environment={"APP_ENV": config.environment},
            tracing=(
                lambda_.Tracing.ACTIVE if config.enable_tracing else lambda_.Tracing.DISABLED
            ),
            logging_format=lambda_.LoggingFormat.JSON,
            application_log_level_v2=lambda_.ApplicationLogLevel.INFO,
            system_log_level_v2=lambda_.SystemLogLevel.WARN,
            log_group=self.log_group,
        )
