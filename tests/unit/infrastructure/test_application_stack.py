import json
from typing import Any, cast

import aws_cdk as cdk
import pytest
from aws_cdk import aws_lambda as lambda_
from aws_cdk.assertions import Match, Template

from infrastructure.configuration import EnvironmentName, load_environment_config
from infrastructure.stacks.application_stack import ApplicationStack


def _template(
    environment: EnvironmentName = "dev",
    *,
    ca_bundle_parameter_name: str | None = None,
) -> Template:
    app = cdk.App()
    config = load_environment_config(environment)
    if ca_bundle_parameter_name is not None:
        raw_config = config.model_dump()
        integrations = cast(dict[str, Any], raw_config["integrations"])
        gitlab = cast(dict[str, Any], integrations["gitlab"])
        gitlab["ca_bundle_parameter_name"] = ca_bundle_parameter_name
        gitlab["tls_verify"] = True
        config = config.model_validate(raw_config)
    stack = ApplicationStack(
        app,
        f"test-foundry-{environment}",
        config=config,
        generic_processor_code=lambda_.Code.from_inline(
            "def handler(event, context): return event"
        ),
        gitlab_user_code=lambda_.Code.from_inline("def handler(event, context): return event"),
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

    assert len(asset_paths) == 2
    assert {path.rsplit("/", maxsplit=1)[-1] for path in asset_paths} == {
        "generic-processor",
        "gitlab-user",
    }


def _logical_id(template: Template, resource_type: str) -> str:
    resources = template.find_resources(resource_type)
    assert len(resources) == 1
    return next(iter(resources))


def _function_logical_id(template: Template, function_name: str) -> str:
    resources = template.find_resources(
        "AWS::Lambda::Function",
        {"Properties": {"FunctionName": function_name}},
    )
    assert len(resources) == 1
    return next(iter(resources))


def test_application_stack_creates_expected_resource_graph() -> None:
    template = _template()

    template.resource_count_is("AWS::Lambda::Function", 2)
    template.resource_count_is("AWS::StepFunctions::StateMachine", 1)
    template.resource_count_is("AWS::Logs::LogGroup", 3)
    template.resource_count_is("AWS::IAM::Role", 3)
    template.resource_count_is("AWS::SSM::Parameter", 1)


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
            "Environment": {
                "Variables": {
                    "APP_ENV": environment,
                    "GENERIC_VARIABLE_PARAMETER_NAME": (
                        f"/foundry/{environment}/generic/example-variable"
                    ),
                    "GENERIC_SECRET_PARAMETER_NAME": (
                        f"/foundry/{environment}/generic/example-secret"
                    ),
                }
            },
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
        "AWS::Lambda::Function",
        {
            "Architectures": ["x86_64"],
            "Description": "Create or reconcile a GitLab user",
            "Environment": {
                "Variables": {
                    "APP_ENV": environment,
                    "GITLAB_BASE_URL_PARAMETER_NAME": (f"/foundry/{environment}/gitlab/base-url"),
                    "GITLAB_API_TOKEN_PARAMETER_NAME": (f"/foundry/{environment}/gitlab/api-token"),
                    "GITLAB_TLS_VERIFY": "false" if environment == "dev" else "true",
                }
            },
            "FunctionName": f"foundry-{environment}-gitlab-user",
            "Handler": "foundry_onboarding.handlers.gitlab_user.handler",
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
    assert len(log_groups) == 3
    for log_group in log_groups.values():
        assert log_group["Properties"]["RetentionInDays"] == retention_days
        assert log_group["DeletionPolicy"] == removal_policy
        assert log_group["UpdateReplacePolicy"] == removal_policy

    parameters = cast(
        dict[str, dict[str, Any]],
        template.find_resources("AWS::SSM::Parameter"),
    )
    assert len(parameters) == 1
    parameter = next(iter(parameters.values()))
    assert parameter["DeletionPolicy"] == removal_policy
    assert parameter["UpdateReplacePolicy"] == removal_policy


def test_application_stack_configures_parameter_store_access() -> None:
    template = _template()

    template.has_resource_properties(
        "AWS::SSM::Parameter",
        {
            "Name": "/foundry/dev/generic/example-variable",
            "Type": "String",
            "Value": "hello-from-dev-parameter-store",
        },
    )

    policies = cast(
        dict[str, dict[str, Any]],
        template.find_resources("AWS::IAM::Policy"),
    )
    statements = [
        statement
        for policy in policies.values()
        for statement in policy["Properties"]["PolicyDocument"]["Statement"]
        if statement["Action"] == "ssm:GetParameters"
    ]
    assert len(statements) == 2

    resource_documents = [json.dumps(statement["Resource"]) for statement in statements]
    generic_resources = next(
        resources for resources in resource_documents if "GenericExampleVariable" in resources
    )
    assert "parameter/foundry/dev/generic/example-secret" in generic_resources

    gitlab_resources = next(
        resources for resources in resource_documents if "gitlab/base-url" in resources
    )
    assert "parameter/foundry/dev/gitlab/base-url" in gitlab_resources
    assert "parameter/foundry/dev/gitlab/api-token" in gitlab_resources
    assert "generic" not in gitlab_resources
    assert len(json.loads(gitlab_resources)) == 2

    template_json = json.dumps(template.to_json())
    assert "not-a-real-secret" not in template_json
    assert "glpat-" not in template_json


def test_application_stack_configures_optional_gitlab_ca_bundle_access() -> None:
    ca_bundle_parameter_name = "/foundry/dev/gitlab/ca-bundle"
    template = _template(ca_bundle_parameter_name=ca_bundle_parameter_name)

    template.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "Environment": {
                "Variables": Match.object_like(
                    {
                        "GITLAB_CA_BUNDLE_PARAMETER_NAME": ca_bundle_parameter_name,
                        "GITLAB_TLS_VERIFY": "true",
                    }
                )
            },
            "FunctionName": "foundry-dev-gitlab-user",
        },
    )

    policies = cast(
        dict[str, dict[str, Any]],
        template.find_resources("AWS::IAM::Policy"),
    )
    gitlab_statement = next(
        statement
        for policy in policies.values()
        for statement in policy["Properties"]["PolicyDocument"]["Statement"]
        if statement["Action"] == "ssm:GetParameters"
        and "gitlab/ca-bundle" in json.dumps(statement["Resource"])
    )
    resources = json.dumps(gitlab_statement["Resource"])
    assert "parameter/foundry/dev/gitlab/base-url" in resources
    assert "parameter/foundry/dev/gitlab/api-token" in resources
    assert "parameter/foundry/dev/gitlab/ca-bundle" in resources
    assert len(json.loads(resources)) == 3


def test_workflow_definition_and_policy_reference_both_task_functions() -> None:
    template = _template()
    processor_logical_id = _function_logical_id(
        template,
        "foundry-dev-generic-processor",
    )
    gitlab_user_logical_id = _function_logical_id(
        template,
        "foundry-dev-gitlab-user",
    )

    processor_arn = {"Fn::GetAtt": [processor_logical_id, "Arn"]}
    gitlab_user_arn = {"Fn::GetAtt": [gitlab_user_logical_id, "Arn"]}
    template.has_resource_properties(
        "AWS::StepFunctions::StateMachine",
        {
            "DefinitionString": {
                "Fn::Join": [
                    "",
                    Match.array_with([processor_arn, gitlab_user_arn]),
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
                        },
                        {
                            "Action": "lambda:InvokeFunction",
                            "Effect": "Allow",
                            "Resource": [
                                gitlab_user_arn,
                                {
                                    "Fn::Join": [
                                        "",
                                        [gitlab_user_arn, ":*"],
                                    ]
                                },
                            ],
                        },
                    ]
                )
            }
        },
    )


def test_stack_outputs_reference_created_resources() -> None:
    template = _template()
    processor_logical_id = _function_logical_id(
        template,
        "foundry-dev-generic-processor",
    )
    gitlab_user_logical_id = _function_logical_id(
        template,
        "foundry-dev-gitlab-user",
    )
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
    template.has_output(
        "GitLabUserFunctionName",
        {
            "Description": "Name of the GitLab user Lambda",
            "Value": {"Ref": gitlab_user_logical_id},
        },
    )
