import pytest

from foundry_onboarding.errors import ConfigurationError
from foundry_onboarding.runtime_configuration.workflow_ingress import (
    STATE_MACHINE_ARN_ENV,
    load_workflow_ingress_configuration,
)

STATE_MACHINE_ARN = "arn:aws:states:us-east-1:111122223333:stateMachine:foundry-dev-onboarding"


def test_loads_valid_state_machine_arn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(STATE_MACHINE_ARN_ENV, STATE_MACHINE_ARN)

    configuration = load_workflow_ingress_configuration()

    assert configuration.state_machine_arn == STATE_MACHINE_ARN


@pytest.mark.parametrize(
    "value",
    [
        "",
        "not-an-arn",
        "arn:aws:sqs:us-east-1:111122223333:stateMachine:wrong-service",
        "arn:aws:states::111122223333:stateMachine:missing-region",
        "arn:aws:states:us-east-1:invalid:stateMachine:invalid-account",
        "arn:aws:states:us-east-1:111122223333:execution:wrong-resource",
        "arn:aws:states:us-east-1:111122223333:stateMachine:",
    ],
)
def test_rejects_missing_or_invalid_state_machine_arn(
    value: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(STATE_MACHINE_ARN_ENV, value)

    with pytest.raises(ConfigurationError):
        load_workflow_ingress_configuration()


def test_rejects_unset_state_machine_arn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(STATE_MACHINE_ARN_ENV, raising=False)

    with pytest.raises(ConfigurationError):
        load_workflow_ingress_configuration()
