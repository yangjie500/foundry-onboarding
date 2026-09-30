import os

from foundry_onboarding.errors import ConfigurationError


def required_environment_variable(name: str) -> str:
    """Return a non-empty environment variable or raise a safe error."""

    value = os.environ.get(name)
    if value is None or not value.strip():
        raise ConfigurationError(f"Required environment variable {name} is not configured")

    return value
