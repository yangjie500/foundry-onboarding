from aws_cdk import Duration, RemovalPolicy
from aws_cdk import aws_sqs as sqs
from constructs import Construct

from infrastructure.configuration import EnvironmentConfig


class DevelopmentOnboardingQueue(Construct):
    """Development-owned SQS queue and dead-letter queue for onboarding simulation."""

    queue: sqs.Queue
    dead_letter_queue: sqs.Queue

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: EnvironmentConfig,
    ) -> None:
        super().__init__(scope, construct_id)

        settings = config.ingestion.sqs
        if config.environment != "dev" or settings.mode != "development":
            raise ValueError("Development onboarding queue requires development configuration")

        self.dead_letter_queue = sqs.Queue(
            self,
            "DeadLetterQueue",
            queue_name="foundry-dev-onboarding-dlq",
            encryption=sqs.QueueEncryption.SQS_MANAGED,
            enforce_ssl=True,
            retention_period=Duration.days(settings.dead_letter_retention_days),
            removal_policy=RemovalPolicy.DESTROY,
        )

        self.queue = sqs.Queue(
            self,
            "Queue",
            queue_name="foundry-dev-onboarding",
            encryption=sqs.QueueEncryption.SQS_MANAGED,
            enforce_ssl=True,
            visibility_timeout=Duration.seconds(settings.visibility_timeout_seconds),
            retention_period=Duration.days(settings.message_retention_days),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=settings.max_receive_count,
                queue=self.dead_letter_queue,
            ),
            removal_policy=RemovalPolicy.DESTROY,
        )
