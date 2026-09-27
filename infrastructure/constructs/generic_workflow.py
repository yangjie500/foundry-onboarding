from aws_cdk import Duration
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_stepfunctions as sfn
from aws_cdk import aws_stepfunctions_tasks as tasks
from constructs import Construct


class GenericWorkflow(Construct):
    """Route generic workflow actions to their task-specific Lambda functions."""

    state_machine: sfn.StateMachine

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        state_machine_name: str,
        processor: lambda_.IFunction,
    ) -> None:
        super().__init__(scope, construct_id)

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
        definition = route_action.when(
            sfn.Condition.string_equals("$.action", "echo"),
            invoke_processor,
        ).otherwise(unsupported_action)

        self.state_machine = sfn.StateMachine(
            self,
            "StateMachine",
            state_machine_name=state_machine_name,
            definition_body=sfn.DefinitionBody.from_chainable(definition),
            state_machine_type=sfn.StateMachineType.STANDARD,
            timeout=Duration.minutes(5),
        )
