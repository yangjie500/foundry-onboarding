from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_lambda_event_sources as lambda_event_sources
from aws_cdk import aws_sqs as sqs
from aws_cdk import aws_stepfunctions as sfn
from constructs import Construct

from infrastructure.configuration import EnvironmentConfig
from infrastructure.constructs.standard_python_lambda import StandardPythonLambda


class SqsWorkflowIngress(Construct):
    """Consume validated onboarding requests and start the workflow."""

    function: lambda_.Function

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        queue: sqs.IQueue,
        state_machine: sfn.IStateMachine,
        code: lambda_.Code,
        config: EnvironmentConfig,
        connect_event_source: bool,
        kms_key_arn: str | None = None,
    ) -> None:
        super().__init__(scope, construct_id)

        ingress = StandardPythonLambda(
            self,
            "Lambda",
            function_name=f"foundry-{config.environment}-sqs-workflow-ingress",
            handler="foundry_onboarding.handlers.sqs_workflow_ingress.handler",
            code=code,
            config=config,
            description="Validate SQS onboarding messages and start the onboarding workflow",
        )
        self.function = ingress.function
        self.function.add_environment(
            "ONBOARDING_STATE_MACHINE_ARN",
            state_machine.state_machine_arn,
        )

        state_machine.grant_start_execution(self.function)
        if kms_key_arn is not None:
            self.function.add_to_role_policy(
                iam.PolicyStatement(actions=["kms:Decrypt"], resources=[kms_key_arn])
            )
        if connect_event_source:
            self.function.add_event_source(
                lambda_event_sources.SqsEventSource(
                    queue,
                    batch_size=config.ingestion.sqs.batch_size,
                    enabled=True,
                    report_batch_item_failures=True,
                )
            )
        else:
            queue.grant_consume_messages(self.function)
