import os

from foundry_onboarding.errors import ConfigurationError


def required_environment_variable(name: str) -> str:
    """Return a non-empty environment variable or raise a safe error."""

    value = os.environ.get(name)
    if value is None or not value.strip():
        raise ConfigurationError(f"Required environment variable {name} is not configured")

    return value


def boolean_environment_variable(name: str, *, default: bool) -> bool:
    """Return a strict boolean environment variable or its default."""

    value = os.environ.get(name)
    if value is None:
        return default

    normalized_value = value.strip().lower()
    if normalized_value == "true":
        return True
    if normalized_value == "false":
        return False

    raise ConfigurationError(f"Environment variable {name} must be true or false")
