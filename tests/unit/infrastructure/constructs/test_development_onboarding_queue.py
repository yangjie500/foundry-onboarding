import aws_cdk as cdk
import pytest

from infrastructure.configuration import load_environment_config
from infrastructure.constructs.development_onboarding_queue import (
    DevelopmentOnboardingQueue,
)


def test_construct_rejects_configuration_without_development_queue() -> None:
    app = cdk.App()
    stack = cdk.Stack(app, "test-development-onboarding-queue-guard")

    with pytest.raises(
        ValueError,
        match="Development onboarding queue requires development configuration",
    ):
        DevelopmentOnboardingQueue(
            stack,
            "DevelopmentOnboardingQueue",
            config=load_environment_config("staging"),
        )
