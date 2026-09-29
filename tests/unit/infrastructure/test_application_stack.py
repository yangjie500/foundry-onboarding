from typing import Any, cast

import aws_cdk as cdk
import pytest
from aws_cdk import aws_lambda as lambda_
from aws_cdk.assertions import Match, Template

from infrastructure.configuration import EnvironmentName, load_environment_config
from infrastructure.stacks.application_stack import ApplicationStack


def _template(environment: EnvironmentName = "dev") -> Template:
    app = cdk.App()
    config = load_environment_config(environment)
    stack = ApplicationStack(
        app,
        f"test-foundry-{environment}",
        config=config,
        generic_processor_code=lambda_.Code.from_inline(
            "def handler(event, context): return event"
        ),
        env=cdk.Environment(
            account="111111111111",
            region=config.aws_region,
        ),
    )

    return Template.from_stack(stack)


def test_application_stack_defaults_to_packaged_processor_asset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asset_paths: list[str] = []

    def code_from_asset(path: str) -> lambda_.Code:
        asset_paths.append(path)
        return lambda_.Code.from_inline("def handler(event, context): return event")

    monkeypatch.setattr(lambda_.Code, "from_asset", code_from_asset)

    app = cdk.App()
    config = load_environment_config("dev")
    ApplicationStack(app, "test-default-asset", config=config)

    assert len(asset_paths) == 1
    assert asset_paths[0].endswith("/build/generic-processor")


def _logical_id(template: Template, resource_type: str) -> str:
    resources = template.find_resources(resource_type)
    assert len(resources) == 1
    return next(iter(resources))


def test_application_stack_creates_expected_resource_graph() -> None:
    template = _template()

    template.resource_count_is("AWS::Lambda::Function", 1)
    template.resource_count_is("AWS::StepFunctions::StateMachine", 1)
    template.resource_count_is("AWS::Logs::LogGroup", 2)
    template.resource_count_is("AWS::IAM::Role", 2)


@pytest.mark.parametrize(
    ("environment", "retention_days", "workflow_log_level", "removal_policy"),
    [
        ("dev", 14, "ALL", "Delete"),
        ("staging", 30, "ALL", "Delete"),
        ("production", 90, "ERROR", "Retain"),
    ],
)
def test_application_stack_applies_environment_configuration(
    environment: EnvironmentName,
    retention_days: int,
    workflow_log_level: str,
    removal_policy: str,
) -> None:
    template = _template(environment)

    template.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "Architectures": ["x86_64"],
            "Environment": {"Variables": {"APP_ENV": environment}},
            "FunctionName": f"foundry-{environment}-generic-processor",
            "Handler": "foundry_onboarding.handlers.generic_processor.handler",
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
        "AWS::StepFunctions::StateMachine",
        {
            "LoggingConfiguration": {
                "IncludeExecutionData": False,
                "Level": workflow_log_level,
            },
            "StateMachineName": f"foundry-{environment}-generic-workflow",
            "StateMachineType": "STANDARD",
            "TracingConfiguration": {"Enabled": True},
        },
    )

    log_groups = cast(
        dict[str, dict[str, Any]],
        template.find_resources("AWS::Logs::LogGroup"),
    )
    assert len(log_groups) == 2
    for log_group in log_groups.values():
        assert log_group["Properties"]["RetentionInDays"] == retention_days
        assert log_group["DeletionPolicy"] == removal_policy
        assert log_group["UpdateReplacePolicy"] == removal_policy


def test_workflow_definition_and_policy_reference_the_processor() -> None:
    template = _template()
    processor_logical_id = _logical_id(template, "AWS::Lambda::Function")

    processor_arn = {"Fn::GetAtt": [processor_logical_id, "Arn"]}
    template.has_resource_properties(
        "AWS::StepFunctions::StateMachine",
        {
            "DefinitionString": {
                "Fn::Join": [
                    "",
                    Match.array_with([processor_arn]),
                ]
            }
        },
    )
    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        {
                            "Action": "lambda:InvokeFunction",
                            "Effect": "Allow",
                            "Resource": [
                                processor_arn,
                                {
                                    "Fn::Join": [
                                        "",
                                        [processor_arn, ":*"],
                                    ]
                                },
                            ],
                        }
                    ]
                )
            }
        },
    )


def test_stack_outputs_reference_created_resources() -> None:
    template = _template()
    processor_logical_id = _logical_id(template, "AWS::Lambda::Function")
    workflow_logical_id = _logical_id(template, "AWS::StepFunctions::StateMachine")

    template.has_output(
        "GenericProcessorName",
        {
            "Description": "Name of the generic processor Lambda",
            "Value": {"Ref": processor_logical_id},
        },
    )
    template.has_output(
        "GenericWorkflowArn",
        {
            "Description": "ARN of the generic onboarding workflow",
            "Value": {"Ref": workflow_logical_id},
        },
    )
