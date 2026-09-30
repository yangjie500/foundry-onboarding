from collections.abc import Iterator

import pytest

from foundry_onboarding.errors import ConfigurationError
from foundry_onboarding.runtime_configuration import generic_processor

VARIABLE_NAME = "/foundry/dev/generic/example-variable"
SECRET_NAME = "/foundry/dev/generic/example-secret"


class FakeParameterStore:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], bool]] = []

    def get_parameters(
        self,
        names: list[str],
        *,
        with_decryption: bool = False,
    ) -> dict[str, str]:
        self.calls.append((names, with_decryption))
        return {
            VARIABLE_NAME: "hello-from-dev-parameter-store",
            SECRET_NAME: "not-a-real-secret",
        }


@pytest.fixture(autouse=True)
def clear_configuration_cache() -> Iterator[None]:
    generic_processor.load_generic_processor_parameters.cache_clear()
    yield
    generic_processor.load_generic_processor_parameters.cache_clear()


@pytest.mark.parametrize(
    "missing_environment",
    [
        generic_processor.VARIABLE_PARAMETER_ENV,
        generic_processor.SECRET_PARAMETER_ENV,
    ],
)
def test_load_parameters_requires_environment_variables(
    monkeypatch: pytest.MonkeyPatch,
    missing_environment: str,
) -> None:
    monkeypatch.setenv(generic_processor.VARIABLE_PARAMETER_ENV, VARIABLE_NAME)
    monkeypatch.setenv(generic_processor.SECRET_PARAMETER_ENV, SECRET_NAME)
    monkeypatch.delenv(missing_environment)

    with pytest.raises(ConfigurationError, match=missing_environment):
        generic_processor.load_generic_processor_parameters()


def test_load_parameters_composes_and_caches_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FakeParameterStore()
    monkeypatch.setenv(generic_processor.VARIABLE_PARAMETER_ENV, VARIABLE_NAME)
    monkeypatch.setenv(generic_processor.SECRET_PARAMETER_ENV, SECRET_NAME)
    monkeypatch.setattr(generic_processor, "_create_parameter_store", lambda: store)

    first = generic_processor.load_generic_processor_parameters()
    second = generic_processor.load_generic_processor_parameters()

    assert first is second
    assert first.example_variable == "hello-from-dev-parameter-store"
    assert first.example_secret == "not-a-real-secret"
    assert store.calls == [([VARIABLE_NAME, SECRET_NAME], True)]
