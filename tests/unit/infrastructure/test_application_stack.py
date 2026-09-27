import aws_cdk as cdk
from aws_cdk.assertions import Template

from infrastructure.configuration import EnvironmentConfig
from infrastructure.stacks.application_stack import ApplicationStack


def test_application_stack_synthesizes() -> None:
    app = cdk.App()
    config = EnvironmentConfig(
        environment="dev",
        aws_region="us-east-1",
        log_retention_days=14,
        enable_tracing=True,
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

    assert template.to_json() is not None
