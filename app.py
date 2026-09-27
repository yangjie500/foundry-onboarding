import os
from typing import cast

import aws_cdk as cdk

from infrastructure.configuration import EnvironmentName, load_environment_config
from infrastructure.stacks.application_stack import ApplicationStack

app = cdk.App()

environment_name = cast(EnvironmentName, app.node.try_get_context("env") or "dev")

config = load_environment_config(environment_name)

account = os.environ.get("CDK_DEFAULT_ACCOUNT")
region = os.environ.get("CDK_DEFAULT_REGION", config.aws_region)

ApplicationStack(
    app,
    f"foundry-{config.environment}",
    config=config,
    env=cdk.Environment(
        account=account,
        region=region,
    ),
    description=f"Foundry application resources for {config.environment}",
    tags={"Application": "foundry", "Environment": config.environment, "ManagedBy": "aws-cdk"},
)

app.synth()
