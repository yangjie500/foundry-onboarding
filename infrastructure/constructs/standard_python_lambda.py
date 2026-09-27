from aws_cdk import Duration
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from constructs import Construct

from infrastructure.configuration import EnvironmentConfig
from infrastructure.constructs.observability import (
    log_removal_policy_for,
    log_retention_for,
)


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

        self.log_group = logs.LogGroup(
            self,
            "LogGroup",
            log_group_name=f"/aws/lambda/{function_name}",
            retention=log_retention_for(config),
            removal_policy=log_removal_policy_for(config),
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
            memory_size=config.lambda_function.memory_size_mb,
            timeout=Duration.seconds(config.lambda_function.timeout_seconds),
            environment={"APP_ENV": config.environment},
            tracing=(
                lambda_.Tracing.ACTIVE
                if config.observability.enable_tracing
                else lambda_.Tracing.DISABLED
            ),
            logging_format=lambda_.LoggingFormat.JSON,
            application_log_level_v2=lambda_.ApplicationLogLevel.INFO,
            system_log_level_v2=lambda_.SystemLogLevel.WARN,
            log_group=self.log_group,
        )
