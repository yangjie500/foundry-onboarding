import json
from typing import Any, cast

import aws_cdk as cdk
from aws_cdk import aws_lambda as lambda_
from aws_cdk.assertions import Match, Template

from infrastructure.configuration import EnvironmentConfig
from infrastructure.constructs import GenericWorkflow


def _config(
    *,
    environment: str = "dev",
    log_retention_days: int = 14,
    enable_tracing: bool = True,
    workflow_log_level: str = "ALL",
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
                "workflow_log_level": workflow_log_level,
            },
            "parameters": {
                "generic_variable_name": f"/foundry/{environment}/generic/example-variable",
                "generic_variable_value": "example-value",
                "generic_secret_name": f"/foundry/{environment}/generic/example-secret",
            },
        }
    )


def _template(config: EnvironmentConfig | None = None) -> Template:
    resolved_config = config or _config()
    app = cdk.App()
    stack = cdk.Stack(app, "TestStack")
    processor = lambda_.Function(
        stack,
        "Processor",
        runtime=lambda_.Runtime.PYTHON_3_14,
        handler="index.handler",
        code=lambda_.Code.from_inline("def handler(event, context): return event"),
    )

    GenericWorkflow(
        stack,
        "Workflow",
        state_machine_name=f"foundry-{resolved_config.environment}-generic-workflow",
        processor=processor,
        config=resolved_config,
    )

    return Template.from_stack(stack)


def _state_machine_definition(template: Template) -> dict[str, object]:
    template_json = cast(dict[str, Any], template.to_json())
    resources = cast(dict[str, dict[str, Any]], template_json["Resources"])
    state_machine = next(
        resource
        for resource in resources.values()
        if resource["Type"] == "AWS::StepFunctions::StateMachine"
    )
    definition = cast(dict[str, Any], state_machine["Properties"]["DefinitionString"])
    join = cast(list[Any], definition["Fn::Join"])
    parts = cast(list[Any], join[1])
    serialized = "".join(part if isinstance(part, str) else "PROCESSOR_ARN" for part in parts)

    return cast(dict[str, object], json.loads(serialized))


def test_generic_workflow_routes_and_transforms_echo_input() -> None:
    template = _template()

    template.has_resource_properties(
        "AWS::StepFunctions::StateMachine",
        {
            "StateMachineName": "foundry-dev-generic-workflow",
            "StateMachineType": "STANDARD",
            "LoggingConfiguration": {
                "IncludeExecutionData": False,
                "Level": "ALL",
            },
            "TracingConfiguration": {"Enabled": True},
        },
    )

    assert _state_machine_definition(template) == {
        "StartAt": "Route action",
        "States": {
            "Route action": {
                "Type": "Choice",
                "Choices": [
                    {
                        "Variable": "$.action",
                        "StringEquals": "echo",
                        "Next": "Validate echo input",
                    }
                ],
                "Default": "Unsupported action",
            },
            "Unsupported action": {
                "Type": "Fail",
                "Error": "UnsupportedAction",
                "Cause": "The requested workflow action is not supported",
            },
            "Validate echo input": {
                "Type": "Choice",
                "Choices": [
                    {
                        "And": [
                            {"Variable": "$.schema_version", "IsPresent": True},
                            {"Variable": "$.schema_version", "IsString": True},
                            {"Variable": "$.request_id", "IsPresent": True},
                            {"Variable": "$.request_id", "IsString": True},
                            {"Variable": "$.payload.message", "IsPresent": True},
                            {"Variable": "$.payload.message", "IsString": True},
                        ],
                        "Next": "Invoke generic processor",
                    }
                ],
                "Default": "Invalid workflow input",
            },
            "Invalid workflow input": {
                "Type": "Fail",
                "Error": "InvalidWorkflowInput",
                "Cause": "The workflow input is invalid",
            },
            "Invoke generic processor": {
                "End": True,
                "Retry": [
                    {
                        "ErrorEquals": [
                            "Lambda.ServiceException",
                            "Lambda.AWSLambdaException",
                            "Lambda.SdkClientException",
                            "Lambda.TooManyRequestsException",
                        ],
                        "IntervalSeconds": 2,
                        "MaxAttempts": 3,
                        "BackoffRate": 2,
                        "JitterStrategy": "FULL",
                    }
                ],
                "Catch": [
                    {
                        "ErrorEquals": ["InvalidInputError"],
                        "ResultPath": None,
                        "Next": "Invalid workflow input",
                    },
                    {
                        "ErrorEquals": ["States.ALL"],
                        "ResultPath": None,
                        "Next": "Processor failed",
                    },
                ],
                "Type": "Task",
                "Resource": "PROCESSOR_ARN",
                "Parameters": {
                    "schema_version.$": "$.schema_version",
                    "request_id.$": "$.request_id",
                    "message.$": "$.payload.message",
                },
            },
            "Processor failed": {
                "Type": "Fail",
                "Error": "ProcessorFailed",
                "Cause": "The generic processor failed",
            },
        },
        "TimeoutSeconds": 300,
    }


def test_generic_workflow_configures_safe_development_logs() -> None:
    template = _template()

    template.has_resource_properties(
        "AWS::Logs::LogGroup",
        {
            "LogGroupName": "/aws/vendedlogs/states/foundry-dev-generic-workflow",
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


def test_generic_workflow_retains_production_logs() -> None:
    template = _template(
        _config(
            environment="production",
            log_retention_days=90,
            workflow_log_level="ERROR",
        )
    )

    template.has_resource(
        "AWS::Logs::LogGroup",
        {
            "DeletionPolicy": "Retain",
            "UpdateReplacePolicy": "Retain",
            "Properties": Match.object_like(
                {
                    "LogGroupName": "/aws/vendedlogs/states/foundry-production-generic-workflow",
                    "RetentionInDays": 90,
                }
            ),
        },
    )
    template.has_resource_properties(
        "AWS::StepFunctions::StateMachine",
        {"LoggingConfiguration": {"Level": "ERROR"}},
    )


def test_generic_workflow_can_disable_tracing() -> None:
    template = _template(_config(enable_tracing=False))

    template.has_resource_properties(
        "AWS::StepFunctions::StateMachine",
        {"TracingConfiguration": {"Enabled": False}},
    )


def test_generic_workflow_can_invoke_only_the_processor() -> None:
    template = _template()

    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Action": "lambda:InvokeFunction",
                                "Effect": "Allow",
                                "Resource": Match.array_with(
                                    [
                                        {
                                            "Fn::GetAtt": [
                                                Match.string_like_regexp("^Processor"),
                                                "Arn",
                                            ]
                                        }
                                    ]
                                ),
                            }
                        )
                    ]
                )
            }
        },
    )
