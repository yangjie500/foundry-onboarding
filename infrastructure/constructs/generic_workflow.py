from aws_cdk import Duration
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_stepfunctions as sfn
from aws_cdk import aws_stepfunctions_tasks as tasks
from constructs import Construct

from infrastructure.configuration import EnvironmentConfig
from infrastructure.constructs.observability import (
    log_removal_policy_for,
    log_retention_for,
    workflow_log_level_for,
)


class GenericWorkflow(Construct):
    """Route generic workflow actions to their task-specific Lambda functions."""

    state_machine: sfn.StateMachine
    log_group: logs.LogGroup

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        state_machine_name: str,
        processor: lambda_.IFunction,
        gitlab_user: lambda_.IFunction,
        config: EnvironmentConfig,
    ) -> None:
        super().__init__(scope, construct_id)

        self.log_group = logs.LogGroup(
            self,
            "LogGroup",
            log_group_name=f"/aws/vendedlogs/states/{state_machine_name}",
            retention=log_retention_for(config),
            removal_policy=log_removal_policy_for(config),
        )

        invoke_processor = tasks.LambdaInvoke(
            self,
            "InvokeGenericProcessor",
            state_name="Invoke generic processor",
            lambda_function=processor,
            payload=sfn.TaskInput.from_object(
                {
                    "schema_version": sfn.JsonPath.string_at("$.schema_version"),
                    "request_id": sfn.JsonPath.string_at("$.request_id"),
                    "message": sfn.JsonPath.string_at("$.payload.message"),
                }
            ),
            payload_response_only=True,
            retry_on_service_exceptions=False,
        )

        retry = config.workflow.retry
        invoke_processor.add_retry(
            errors=[
                "Lambda.ServiceException",
                "Lambda.AWSLambdaException",
                "Lambda.SdkClientException",
                "Lambda.TooManyRequestsException",
            ],
            interval=Duration.seconds(retry.interval_seconds),
            backoff_rate=retry.backoff_rate,
            max_attempts=retry.max_attempts,
            jitter_strategy=sfn.JitterType.FULL,
        )

        invoke_gitlab_user = tasks.LambdaInvoke(
            self,
            "InvokeGitLabUser",
            state_name="Invoke GitLab user",
            lambda_function=gitlab_user,
            payload=sfn.TaskInput.from_object(
                {
                    "schema_version": sfn.JsonPath.string_at("$.schema_version"),
                    "request_id": sfn.JsonPath.string_at("$.request_id"),
                    "username": sfn.JsonPath.string_at("$.payload.username"),
                    "name": sfn.JsonPath.string_at("$.payload.name"),
                    "email": sfn.JsonPath.string_at("$.payload.email"),
                    "external": sfn.JsonPath.string_at("$.payload.external"),
                }
            ),
            payload_response_only=True,
            retry_on_service_exceptions=False,
        )
        invoke_gitlab_user.add_retry(
            errors=["GitLabUnavailableError"],
            interval=Duration.seconds(retry.interval_seconds),
            backoff_rate=retry.backoff_rate,
            max_attempts=retry.max_attempts,
            jitter_strategy=sfn.JitterType.FULL,
        )
        invoke_gitlab_user.add_retry(
            errors=[
                "Lambda.ServiceException",
                "Lambda.AWSLambdaException",
                "Lambda.SdkClientException",
                "Lambda.TooManyRequestsException",
            ],
            interval=Duration.seconds(retry.interval_seconds),
            backoff_rate=retry.backoff_rate,
            max_attempts=retry.max_attempts,
            jitter_strategy=sfn.JitterType.FULL,
        )

        invalid_workflow_input = sfn.Fail(
            self,
            "InvalidWorkflowInput",
            state_name="Invalid workflow input",
            error="InvalidWorkflowInput",
            cause="The workflow input is invalid",
        )

        processor_failed = sfn.Fail(
            self,
            "ProcessorFailed",
            state_name="Processor failed",
            error="ProcessorFailed",
            cause="The generic processor failed",
        )

        gitlab_configuration_failed = sfn.Fail(
            self,
            "GitLabConfigurationFailed",
            state_name="GitLab configuration failed",
            error="GitLabConfigurationFailed",
            cause="GitLab configuration or authentication failed",
        )

        gitlab_provisioning_rejected = sfn.Fail(
            self,
            "GitLabProvisioningRejected",
            state_name="GitLab provisioning rejected",
            error="GitLabProvisioningRejected",
            cause="GitLab user provisioning was rejected",
        )

        gitlab_integration_failed = sfn.Fail(
            self,
            "GitLabIntegrationFailed",
            state_name="GitLab integration failed",
            error="GitLabIntegrationFailed",
            cause="The GitLab integration failed",
        )

        invoke_processor.add_catch(
            invalid_workflow_input,
            errors=["InvalidInputError"],
            result_path=sfn.JsonPath.DISCARD,
        )
        invoke_gitlab_user.add_catch(
            invalid_workflow_input,
            errors=["InvalidInputError"],
            result_path=sfn.JsonPath.DISCARD,
        )
        invoke_gitlab_user.add_catch(
            gitlab_configuration_failed,
            errors=["ConfigurationError", "GitLabAuthenticationError"],
            result_path=sfn.JsonPath.DISCARD,
        )
        invoke_gitlab_user.add_catch(
            gitlab_provisioning_rejected,
            errors=["GitLabIdentityConflictError", "GitLabRequestError"],
            result_path=sfn.JsonPath.DISCARD,
        )
        invoke_gitlab_user.add_catch(
            gitlab_integration_failed,
            errors=["GitLabProtocolError"],
            result_path=sfn.JsonPath.DISCARD,
        )
        invoke_gitlab_user.add_catch(
            gitlab_integration_failed,
            errors=["States.ALL"],
            result_path=sfn.JsonPath.DISCARD,
        )
        invoke_processor.add_catch(
            processor_failed,
            errors=["States.ALL"],
            result_path=sfn.JsonPath.DISCARD,
        )

        unsupported_action = sfn.Fail(
            self,
            "UnsupportedAction",
            state_name="Unsupported action",
            error="UnsupportedAction",
            cause="The requested workflow action is not supported",
        )

        route_action = sfn.Choice(
            self,
            "RouteAction",
            state_name="Route action",
        )

        validate_echo_input = sfn.Choice(
            self,
            "ValidateEchoInput",
            state_name="Validate echo input",
        )
        valid_echo_input = sfn.Condition.and_(
            sfn.Condition.is_present("$.schema_version"),
            sfn.Condition.is_string("$.schema_version"),
            sfn.Condition.is_present("$.request_id"),
            sfn.Condition.is_string("$.request_id"),
            sfn.Condition.is_present("$.payload.message"),
            sfn.Condition.is_string("$.payload.message"),
        )
        validate_echo_input.when(valid_echo_input, invoke_processor).otherwise(
            invalid_workflow_input
        )

        validate_onboard_user_input = sfn.Choice(
            self,
            "ValidateOnboardUserInput",
            state_name="Validate onboarding input",
        )
        valid_onboard_user_input = sfn.Condition.and_(
            sfn.Condition.string_equals("$.schema_version", "1.0"),
            sfn.Condition.is_present("$.request_id"),
            sfn.Condition.is_string("$.request_id"),
            sfn.Condition.is_present("$.payload.username"),
            sfn.Condition.is_string("$.payload.username"),
            sfn.Condition.is_present("$.payload.name"),
            sfn.Condition.is_string("$.payload.name"),
            sfn.Condition.is_present("$.payload.email"),
            sfn.Condition.is_string("$.payload.email"),
            sfn.Condition.is_present("$.payload.external"),
            sfn.Condition.is_boolean("$.payload.external"),
        )
        validate_onboard_user_input.when(
            valid_onboard_user_input,
            invoke_gitlab_user,
        ).otherwise(invalid_workflow_input)

        definition = (
            route_action.when(
                sfn.Condition.string_equals("$.action", "echo"),
                validate_echo_input,
            )
            .when(
                sfn.Condition.string_equals("$.action", "onboard_user"),
                validate_onboard_user_input,
            )
            .otherwise(unsupported_action)
        )

        self.state_machine = sfn.StateMachine(
            self,
            "StateMachine",
            state_machine_name=state_machine_name,
            definition_body=sfn.DefinitionBody.from_chainable(definition),
            state_machine_type=sfn.StateMachineType.STANDARD,
            timeout=Duration.seconds(config.workflow.timeout_seconds),
            logs=sfn.LogOptions(
                destination=self.log_group,
                level=workflow_log_level_for(config),
                include_execution_data=False,
            ),
            tracing_enabled=config.observability.enable_tracing,
        )
