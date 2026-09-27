from pathlib import Path
from typing import Any

from aws_cdk import CfnOutput, Stack
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_stepfunctions as sfn
from constructs import Construct

from infrastructure.configuration import EnvironmentConfig
from infrastructure.constructs import GenericWorkflow, StandardPythonLambda

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ApplicationStack(Stack):
    generic_processor: lambda_.Function
    generic_workflow: sfn.StateMachine

    def __init__(
        self, scope: Construct, construct_id: str, *, config: EnvironmentConfig, **kwargs: Any
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.config = config

        processor = StandardPythonLambda(
            self,
            "GenericProcessor",
            function_name=f"foundry-{config.environment}-generic-processor",
            handler="foundry_onboarding.handlers.generic_processor.handler",
            # Step 4 will replace this source-only asset with a dependency-complete build.
            code=lambda_.Code.from_asset(str(_PROJECT_ROOT / "src")),
            config=config,
            description="Process a generic workflow request",
        )
        self.generic_processor = processor.function

        workflow = GenericWorkflow(
            self,
            "GenericWorkflow",
            state_machine_name=f"foundry-{config.environment}-generic-workflow",
            processor=self.generic_processor,
            config=config,
        )
        self.generic_workflow = workflow.state_machine

        CfnOutput(
            self,
            "GenericProcessorName",
            value=self.generic_processor.function_name,
            description="Name of the generic processor Lambda",
        )
        CfnOutput(
            self,
            "GenericWorkflowArn",
            value=self.generic_workflow.state_machine_arn,
            description="ARN of the generic onboarding workflow",
        )
