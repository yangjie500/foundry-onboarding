from dataclasses import dataclass

from foundry_onboarding.errors import ConfigurationError
from foundry_onboarding.runtime_configuration.environment import required_environment_variable

STATE_MACHINE_ARN_ENV = "ONBOARDING_STATE_MACHINE_ARN"


@dataclass(frozen=True, slots=True)
class WorkflowIngressConfiguration:
    """Non-secret configuration required by the SQS ingress Lambda."""

    state_machine_arn: str


def load_workflow_ingress_configuration() -> WorkflowIngressConfiguration:
    """Load and validate the onboarding state-machine reference."""

    state_machine_arn = required_environment_variable(STATE_MACHINE_ARN_ENV)
    if not _is_state_machine_arn(state_machine_arn):
        raise ConfigurationError("Onboarding state machine ARN is invalid")

    return WorkflowIngressConfiguration(state_machine_arn=state_machine_arn)


def _is_state_machine_arn(value: str) -> bool:
    arn_parts = value.split(":", maxsplit=6)
    if len(arn_parts) != 7:
        return False

    arn, partition, service, region, account_id, resource_type, resource_name = arn_parts
    return (
        arn == "arn"
        and partition.startswith("aws")
        and service == "states"
        and bool(region)
        and len(account_id) == 12
        and account_id.isdigit()
        and resource_type == "stateMachine"
        and bool(resource_name)
    )
