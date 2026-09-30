from dataclasses import dataclass

from foundry_onboarding.contracts.generic_processor import (
    EchoResult,
    GenericProcessorInput,
    GenericProcessorOutput,
)


@dataclass(frozen=True, slots=True)
class GenericProcessorParameters:
    """Runtime values loaded from Parameter Store for the generic processor."""

    example_variable: str
    example_secret: str


def process_request(
    request: GenericProcessorInput,
    parameters: GenericProcessorParameters,
) -> GenericProcessorOutput:
    """Process a validated generic Lambda request."""

    return GenericProcessorOutput(
        schema_version=request.schema_version,
        request_id=request.request_id,
        status="succeeded",
        result=EchoResult(
            message=request.message,
            example_variable=parameters.example_variable,
            example_secret_loaded=bool(parameters.example_secret),
        ),
    )
