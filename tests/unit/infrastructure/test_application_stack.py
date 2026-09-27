import aws_cdk as cdk
from aws_cdk.assertions import Match, Template

from infrastructure.configuration import EnvironmentConfig
from infrastructure.stacks.application_stack import ApplicationStack


def test_application_stack_synthesizes() -> None:
    app = cdk.App()
    config = EnvironmentConfig.model_validate(
        {
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
        }
    )

    stack = ApplicationStack(
        app,
        "test-foundry-dev",
        config=config,
        env=cdk.Environment(
            account="111111111111",
            region="us-east-1",
        ),
    )

    template = Template.from_stack(stack)

    template.resource_count_is("AWS::Lambda::Function", 1)
    template.resource_count_is("AWS::StepFunctions::StateMachine", 1)
    template.resource_count_is("AWS::Logs::LogGroup", 2)

    template.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "FunctionName": "foundry-dev-generic-processor",
            "Handler": "foundry_onboarding.handlers.generic_processor.handler",
        },
    )
    template.has_resource_properties(
        "AWS::StepFunctions::StateMachine",
        {"StateMachineName": "foundry-dev-generic-workflow"},
    )
    template.has_output(
        "GenericProcessorName",
        {
            "Description": "Name of the generic processor Lambda",
            "Value": Match.any_value(),
        },
    )
    template.has_output(
        "GenericWorkflowArn",
        {
            "Description": "ARN of the generic onboarding workflow",
            "Value": Match.any_value(),
        },
    )
