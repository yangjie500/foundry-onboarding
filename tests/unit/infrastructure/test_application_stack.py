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
    external_queue_arn: str | None = None,
    external_kms_key_arn: str | None = None,
    event_source_mapping_enabled: bool = False,
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
    if external_queue_arn is not None:
        raw_config = config.model_dump()
        ingestion = cast(dict[str, Any], raw_config["ingestion"])
        sqs_config = cast(dict[str, Any], ingestion["sqs"])
        sqs_config["mode"] = "external"
        sqs_config["external"] = {
            "queue_arn": external_queue_arn,
            "kms_key_arn": external_kms_key_arn,
            "event_source_mapping_enabled": event_source_mapping_enabled,
        }
        config = config.model_validate(raw_config)
    stack = ApplicationStack(
        app,
        f"test-foundry-{environment}",
        config=config,
        generic_processor_code=lambda_.Code.from_inline(
            "def handler(event, context): return event"
        ),
        gitlab_user_code=lambda_.Code.from_inline("def handler(event, context): return event"),
        sqs_workflow_ingress_code=lambda_.Code.from_inline(
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

    assert len(asset_paths) == 3
    assert {path.rsplit("/", maxsplit=1)[-1] for path in asset_paths} == {
        "generic-processor",
        "gitlab-user",
        "sqs-workflow-ingress",
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


def _queue_logical_id(template: Template, queue_name: str) -> str:
    resources = template.find_resources(
        "AWS::SQS::Queue",
        {"Properties": {"QueueName": queue_name}},
    )
    assert len(resources) == 1
    return next(iter(resources))


def _function_role_logical_id(template: Template, function_name: str) -> str:
    resources = template.find_resources(
        "AWS::Lambda::Function",
        {"Properties": {"FunctionName": function_name}},
    )
    assert len(resources) == 1
    function = next(iter(resources.values()))
    role = function["Properties"]["Role"]
    assert isinstance(role, dict)
    get_att = role["Fn::GetAtt"]
    assert isinstance(get_att, list)
    role_logical_id = get_att[0]
    assert isinstance(role_logical_id, str)
    return role_logical_id


def test_application_stack_creates_expected_resource_graph() -> None:
    template = _template()

    template.resource_count_is("AWS::Lambda::Function", 3)
    template.resource_count_is("AWS::StepFunctions::StateMachine", 1)
    template.resource_count_is("AWS::Logs::LogGroup", 4)
    template.resource_count_is("AWS::IAM::Role", 4)
    template.resource_count_is("AWS::SSM::Parameter", 1)
    template.resource_count_is("AWS::SQS::Queue", 2)
    template.resource_count_is("AWS::SQS::QueuePolicy", 2)
    template.resource_count_is("AWS::Lambda::EventSourceMapping", 1)


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
    if environment == "dev":
        template.has_resource_properties(
            "AWS::Lambda::Function",
            {
                "Architectures": ["x86_64"],
                "Description": (
                    "Validate SQS onboarding messages and start the onboarding workflow"
                ),
                "Environment": {
                    "Variables": {
                        "APP_ENV": "dev",
                        "ONBOARDING_STATE_MACHINE_ARN": Match.any_value(),
                    }
                },
                "FunctionName": "foundry-dev-sqs-workflow-ingress",
                "Handler": "foundry_onboarding.handlers.sqs_workflow_ingress.handler",
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

    log_groups = cast(
        dict[str, dict[str, Any]],
        template.find_resources("AWS::Logs::LogGroup"),
    )
    expected_log_group_count = 4 if environment == "dev" else 3
    assert len(log_groups) == expected_log_group_count
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


def test_application_stack_configures_development_onboarding_queues() -> None:
    template = _template()
    dead_letter_queue_logical_id = _queue_logical_id(
        template,
        "foundry-dev-onboarding-dlq",
    )

    template.has_resource_properties(
        "AWS::SQS::Queue",
        {
            "QueueName": "foundry-dev-onboarding",
            "MessageRetentionPeriod": 345600,
            "SqsManagedSseEnabled": True,
            "VisibilityTimeout": 180,
            "RedrivePolicy": {
                "deadLetterTargetArn": {
                    "Fn::GetAtt": [dead_letter_queue_logical_id, "Arn"],
                },
                "maxReceiveCount": 5,
            },
        },
    )
    template.has_resource_properties(
        "AWS::SQS::Queue",
        {
            "QueueName": "foundry-dev-onboarding-dlq",
            "MessageRetentionPeriod": 1209600,
            "SqsManagedSseEnabled": True,
        },
    )

    queues = cast(
        dict[str, dict[str, Any]],
        template.find_resources("AWS::SQS::Queue"),
    )
    assert len(queues) == 2
    for queue in queues.values():
        assert queue["DeletionPolicy"] == "Delete"
        assert queue["UpdateReplacePolicy"] == "Delete"

    queue_policies = cast(
        dict[str, dict[str, Any]],
        template.find_resources("AWS::SQS::QueuePolicy"),
    )
    assert len(queue_policies) == 2
    for queue_policy in queue_policies.values():
        statements = queue_policy["Properties"]["PolicyDocument"]["Statement"]
        tls_denials = [
            statement
            for statement in statements
            if statement["Effect"] == "Deny"
            and statement["Action"] == "sqs:*"
            and statement["Condition"] == {"Bool": {"aws:SecureTransport": "false"}}
        ]
        assert len(tls_denials) == 1
        assert tls_denials[0]["Principal"] == {"AWS": "*"}

    template_json = json.dumps(template.to_json())
    assert '"Action": "sqs:SendMessage"' not in template_json
    assert "foundry-dev-sqs-workflow-ingress" in template_json


def test_application_stack_connects_queue_to_workflow_ingress() -> None:
    template = _template()
    queue_logical_id = _queue_logical_id(template, "foundry-dev-onboarding")
    ingress_logical_id = _function_logical_id(
        template,
        "foundry-dev-sqs-workflow-ingress",
    )
    workflow_logical_id = _logical_id(template, "AWS::StepFunctions::StateMachine")

    template.has_resource_properties(
        "AWS::Lambda::EventSourceMapping",
        {
            "BatchSize": 10,
            "Enabled": True,
            "EventSourceArn": {"Fn::GetAtt": [queue_logical_id, "Arn"]},
            "FunctionName": {"Ref": ingress_logical_id},
            "FunctionResponseTypes": ["ReportBatchItemFailures"],
        },
    )
    template.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "Environment": {
                "Variables": {
                    "APP_ENV": "dev",
                    "ONBOARDING_STATE_MACHINE_ARN": {"Ref": workflow_logical_id},
                }
            },
            "FunctionName": "foundry-dev-sqs-workflow-ingress",
        },
    )


def test_workflow_ingress_role_has_only_scoped_application_permissions() -> None:
    template = _template()
    queue_logical_id = _queue_logical_id(template, "foundry-dev-onboarding")
    dead_letter_queue_logical_id = _queue_logical_id(
        template,
        "foundry-dev-onboarding-dlq",
    )
    workflow_logical_id = _logical_id(template, "AWS::StepFunctions::StateMachine")
    ingress_role_logical_id = _function_role_logical_id(
        template,
        "foundry-dev-sqs-workflow-ingress",
    )

    policies = cast(
        dict[str, dict[str, Any]],
        template.find_resources("AWS::IAM::Policy"),
    )
    ingress_policy = next(
        policy
        for policy in policies.values()
        if {"Ref": ingress_role_logical_id} in policy["Properties"]["Roles"]
    )
    statements = ingress_policy["Properties"]["PolicyDocument"]["Statement"]

    start_execution = next(
        statement for statement in statements if statement["Action"] == "states:StartExecution"
    )
    assert start_execution == {
        "Action": "states:StartExecution",
        "Effect": "Allow",
        "Resource": {"Ref": workflow_logical_id},
    }

    consume_messages = next(
        statement
        for statement in statements
        if isinstance(statement["Action"], list) and "sqs:ReceiveMessage" in statement["Action"]
    )
    assert set(consume_messages["Action"]) == {
        "sqs:ReceiveMessage",
        "sqs:ChangeMessageVisibility",
        "sqs:GetQueueUrl",
        "sqs:DeleteMessage",
        "sqs:GetQueueAttributes",
    }
    assert consume_messages["Effect"] == "Allow"
    assert consume_messages["Resource"] == {"Fn::GetAtt": [queue_logical_id, "Arn"]}
    assert dead_letter_queue_logical_id not in json.dumps(ingress_policy)

    application_actions = {
        action
        for statement in statements
        for action in (
            statement["Action"] if isinstance(statement["Action"], list) else [statement["Action"]]
        )
        if not action.startswith("xray:")
    }
    assert application_actions == {
        "states:StartExecution",
        "sqs:ReceiveMessage",
        "sqs:ChangeMessageVisibility",
        "sqs:GetQueueUrl",
        "sqs:DeleteMessage",
        "sqs:GetQueueAttributes",
    }


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_application_stack_does_not_provision_queues_outside_development(
    environment: EnvironmentName,
) -> None:
    template = _template(environment)

    template.resource_count_is("AWS::SQS::Queue", 0)
    template.resource_count_is("AWS::SQS::QueuePolicy", 0)
    template.resource_count_is("AWS::Lambda::EventSourceMapping", 0)
    template.resource_count_is("AWS::Lambda::Function", 2)


def test_external_queue_first_deployment_creates_permissions_without_mapping() -> None:
    queue_arn = "arn:aws:sqs:us-east-1:222222222222:external-onboarding"
    key_arn = "arn:aws:kms:us-east-1:222222222222:key/11111111-2222-3333-4444-555555555555"
    template = _template(
        "staging",
        external_queue_arn=queue_arn,
        external_kms_key_arn=key_arn,
    )

    template.resource_count_is("AWS::SQS::Queue", 0)
    template.resource_count_is("AWS::SQS::QueuePolicy", 0)
    template.resource_count_is("AWS::Lambda::EventSourceMapping", 0)
    template.resource_count_is("AWS::Lambda::Function", 3)
    ingress_role_logical_id = _function_role_logical_id(
        template,
        "foundry-staging-sqs-workflow-ingress",
    )
    policies = cast(dict[str, dict[str, Any]], template.find_resources("AWS::IAM::Policy"))
    ingress_policy = next(
        policy
        for policy in policies.values()
        if {"Ref": ingress_role_logical_id} in policy["Properties"]["Roles"]
    )
    statements = ingress_policy["Properties"]["PolicyDocument"]["Statement"]
    queue_access = next(
        statement
        for statement in statements
        if isinstance(statement["Action"], list) and "sqs:ReceiveMessage" in statement["Action"]
    )
    assert queue_access["Resource"] == queue_arn
    assert next(statement for statement in statements if statement["Action"] == "kms:Decrypt") == {
        "Action": "kms:Decrypt",
        "Effect": "Allow",
        "Resource": key_arn,
    }
    template.has_output(
        "ExternalOnboardingQueueArn",
        {
            "Description": "ARN of the externally managed onboarding queue",
            "Value": queue_arn,
        },
    )
    template.has_output(
        "SqsWorkflowIngressRoleArn",
        {
            "Description": "Role ARN that an external SQS queue and KMS key must trust",
            "Value": {"Fn::GetAtt": [ingress_role_logical_id, "Arn"]},
        },
    )


def test_external_queue_mapping_can_be_enabled_after_handoff() -> None:
    queue_arn = "arn:aws:sqs:us-east-1:222222222222:external-onboarding"
    template = _template(
        "production",
        external_queue_arn=queue_arn,
        event_source_mapping_enabled=True,
    )

    ingress_logical_id = _function_logical_id(
        template,
        "foundry-production-sqs-workflow-ingress",
    )
    template.has_resource_properties(
        "AWS::Lambda::EventSourceMapping",
        {
            "BatchSize": 10,
            "Enabled": True,
            "EventSourceArn": queue_arn,
            "FunctionName": {"Ref": ingress_logical_id},
            "FunctionResponseTypes": ["ReportBatchItemFailures"],
        },
    )
    template.resource_count_is("AWS::SQS::Queue", 0)
    template.resource_count_is("AWS::SQS::QueuePolicy", 0)


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
    ingress_logical_id = _function_logical_id(
        template,
        "foundry-dev-sqs-workflow-ingress",
    )
    workflow_logical_id = _logical_id(template, "AWS::StepFunctions::StateMachine")
    queue_logical_id = _queue_logical_id(template, "foundry-dev-onboarding")
    dead_letter_queue_logical_id = _queue_logical_id(
        template,
        "foundry-dev-onboarding-dlq",
    )

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
    template.has_output(
        "DevelopmentOnboardingQueueUrl",
        {
            "Description": "URL of the development onboarding simulation queue",
            "Value": {"Ref": queue_logical_id},
        },
    )
    template.has_output(
        "DevelopmentOnboardingQueueArn",
        {
            "Description": "ARN of the development onboarding simulation queue",
            "Value": {"Fn::GetAtt": [queue_logical_id, "Arn"]},
        },
    )
    template.has_output(
        "DevelopmentOnboardingDeadLetterQueueUrl",
        {
            "Description": "URL of the development onboarding dead-letter queue",
            "Value": {"Ref": dead_letter_queue_logical_id},
        },
    )
    template.has_output(
        "DevelopmentOnboardingDeadLetterQueueArn",
        {
            "Description": "ARN of the development onboarding dead-letter queue",
            "Value": {"Fn::GetAtt": [dead_letter_queue_logical_id, "Arn"]},
        },
    )
    template.has_output(
        "SqsWorkflowIngressFunctionName",
        {
            "Description": "Name of the SQS workflow-ingress Lambda",
            "Value": {"Ref": ingress_logical_id},
        },
    )
