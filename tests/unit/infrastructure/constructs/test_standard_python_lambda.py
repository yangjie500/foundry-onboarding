import aws_cdk as cdk
from aws_cdk import aws_lambda as lambda_
from aws_cdk.assertions import Match, Template

from infrastructure.configuration import EnvironmentConfig
from infrastructure.constructs import StandardPythonLambda


def _config(
    *,
    environment: str = "dev",
    log_retention_days: int = 14,
    enable_tracing: bool = True,
) -> EnvironmentConfig:
    return EnvironmentConfig.model_validate(
        {
            "environment": environment,
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
                "log_retention_days": log_retention_days,
                "enable_tracing": enable_tracing,
                "workflow_log_level": "ALL",
            },
            "ingestion": {
                "sqs": {
                    "mode": "disabled",
                }
            },
            "parameters": {
                "generic_variable_name": f"/foundry/{environment}/generic/example-variable",
                "generic_variable_value": "example-value",
                "generic_secret_name": f"/foundry/{environment}/generic/example-secret",
            },
            "integrations": {
                "gitlab": {
                    "base_url_parameter_name": f"/foundry/{environment}/gitlab/base-url",
                    "api_token_parameter_name": f"/foundry/{environment}/gitlab/api-token",
                }
            },
        }
    )


def _template(config: EnvironmentConfig) -> Template:
    app = cdk.App()
    stack = cdk.Stack(app, "TestStack")

    StandardPythonLambda(
        stack,
        "Processor",
        function_name=f"foundry-{config.environment}-generic-processor",
        handler="index.handler",
        code=lambda_.Code.from_inline("def handler(event, context): return event"),
        config=config,
        description="Process a generic workflow request",
    )

    return Template.from_stack(stack)


def test_standard_python_lambda_uses_project_defaults() -> None:
    template = _template(_config())

    template.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "Architectures": ["x86_64"],
            "Description": "Process a generic workflow request",
            "Environment": {"Variables": {"APP_ENV": "dev"}},
            "FunctionName": "foundry-dev-generic-processor",
            "Handler": "index.handler",
            "LoggingConfig": {
                "ApplicationLogLevel": "INFO",
                "LogFormat": "JSON",
                "SystemLogLevel": "WARN",
            },
            "MemorySize": 256,
            "Runtime": "python3.14",
            "Timeout": 30,
            "TracingConfig": {"Mode": "Active"},
        },
    )
    template.has_resource_properties(
        "AWS::Logs::LogGroup",
        {
            "LogGroupName": "/aws/lambda/foundry-dev-generic-processor",
            "RetentionInDays": 14,
        },
    )
    template.has_resource(
        "AWS::Logs::LogGroup",
        {
            "DeletionPolicy": "Delete",
            "UpdateReplacePolicy": "Delete",
        },
    )


def test_standard_python_lambda_can_disable_tracing() -> None:
    template = _template(_config(enable_tracing=False))

    template.has_resource_properties(
        "AWS::Lambda::Function",
        {"TracingConfig": Match.absent()},
    )


def test_standard_python_lambda_retains_production_logs() -> None:
    template = _template(_config(environment="production", log_retention_days=90))

    template.has_resource(
        "AWS::Logs::LogGroup",
        {
            "DeletionPolicy": "Retain",
            "UpdateReplacePolicy": "Retain",
            "Properties": Match.object_like({"RetentionInDays": 90}),
        },
    )
