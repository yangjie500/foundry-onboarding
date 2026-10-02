from pathlib import Path
from typing import Any

from aws_cdk import CfnOutput, RemovalPolicy, Stack
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_ssm as ssm
from aws_cdk import aws_stepfunctions as sfn
from constructs import Construct

from infrastructure.configuration import EnvironmentConfig
from infrastructure.constructs import GenericWorkflow, StandardPythonLambda

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_GENERIC_PROCESSOR_ASSET = _PROJECT_ROOT / "build" / "generic-processor"
_GITLAB_USER_ASSET = _PROJECT_ROOT / "build" / "gitlab-user"


class ApplicationStack(Stack):
    generic_processor: lambda_.Function
    gitlab_user: lambda_.Function
    generic_workflow: sfn.StateMachine

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: EnvironmentConfig,
        generic_processor_code: lambda_.Code | None = None,
        gitlab_user_code: lambda_.Code | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.config = config

        processor = StandardPythonLambda(
            self,
            "GenericProcessor",
            function_name=f"foundry-{config.environment}-generic-processor",
            handler="foundry_onboarding.handlers.generic_processor.handler",
            code=generic_processor_code or lambda_.Code.from_asset(str(_GENERIC_PROCESSOR_ASSET)),
            config=config,
            description="Process a generic workflow request",
        )
        self.generic_processor = processor.function

        gitlab_user = StandardPythonLambda(
            self,
            "GitLabUser",
            function_name=f"foundry-{config.environment}-gitlab-user",
            handler="foundry_onboarding.handlers.gitlab_user.handler",
            code=gitlab_user_code or lambda_.Code.from_asset(str(_GITLAB_USER_ASSET)),
            config=config,
            description="Create or reconcile a GitLab user",
        )
        self.gitlab_user = gitlab_user.function

        gitlab_config = config.integrations.gitlab
        self.gitlab_user.add_environment(
            "GITLAB_BASE_URL_PARAMETER_NAME",
            gitlab_config.base_url_parameter_name,
        )
        self.gitlab_user.add_environment(
            "GITLAB_API_TOKEN_PARAMETER_NAME",
            gitlab_config.api_token_parameter_name,
        )
        self.gitlab_user.add_environment(
            "GITLAB_TLS_VERIFY",
            str(gitlab_config.tls_verify).lower(),
        )

        gitlab_parameter_arns = [
            self.format_arn(
                service="ssm",
                resource="parameter",
                resource_name=parameter_name.removeprefix("/"),
            )
            for parameter_name in (
                gitlab_config.base_url_parameter_name,
                gitlab_config.api_token_parameter_name,
            )
        ]
        self.gitlab_user.add_to_role_policy(
            iam.PolicyStatement(
                actions=["ssm:GetParameters"],
                resources=gitlab_parameter_arns,
            )
        )

        generic_variable = ssm.StringParameter(
            self,
            "GenericExampleVariable",
            parameter_name=config.parameters.generic_variable_name,
            string_value=config.parameters.generic_variable_value,
            description="Example variable used by the generic processor",
        )
        generic_variable.apply_removal_policy(
            RemovalPolicy.RETAIN if config.environment == "production" else RemovalPolicy.DESTROY
        )

        self.generic_processor.add_environment(
            "GENERIC_VARIABLE_PARAMETER_NAME",
            config.parameters.generic_variable_name,
        )
        self.generic_processor.add_environment(
            "GENERIC_SECRET_PARAMETER_NAME",
            config.parameters.generic_secret_name,
        )

        generic_secret_arn = self.format_arn(
            service="ssm",
            resource="parameter",
            resource_name=config.parameters.generic_secret_name.removeprefix("/"),
        )
        self.generic_processor.add_to_role_policy(
            iam.PolicyStatement(
                actions=["ssm:GetParameters"],
                resources=[generic_variable.parameter_arn, generic_secret_arn],
            )
        )

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
        CfnOutput(
            self,
            "GitLabUserFunctionName",
            value=self.gitlab_user.function_name,
            description="Name of the GitLab user Lambda",
        )
