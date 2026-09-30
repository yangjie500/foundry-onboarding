from functools import cache

from foundry_onboarding.adapters.aws.parameter_store import (
    ParameterStore,
    create_parameter_store,
)
from foundry_onboarding.runtime_configuration.environment import (
    required_environment_variable,
)
from foundry_onboarding.services.generic_processor import GenericProcessorParameters

VARIABLE_PARAMETER_ENV = "GENERIC_VARIABLE_PARAMETER_NAME"
SECRET_PARAMETER_ENV = "GENERIC_SECRET_PARAMETER_NAME"


def _create_parameter_store() -> ParameterStore:
    return create_parameter_store()


@cache
def load_generic_processor_parameters() -> GenericProcessorParameters:
    """Compose generic processor configuration from reusable AWS adapters."""

    variable_name = required_environment_variable(VARIABLE_PARAMETER_ENV)
    secret_name = required_environment_variable(SECRET_PARAMETER_ENV)
    values = _create_parameter_store().get_parameters(
        [variable_name, secret_name],
        with_decryption=True,
    )

    return GenericProcessorParameters(
        example_variable=values[variable_name],
        example_secret=values[secret_name],
    )
