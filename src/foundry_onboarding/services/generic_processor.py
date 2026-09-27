from foundry_onboarding.contracts.generic_processor import (
    EchoResult,
    GenericProcessorInput,
    GenericProcessorOutput,
)


def process_request(request: GenericProcessorInput) -> GenericProcessorOutput:
    """Process a validated generic Lambda request."""

    return GenericProcessorOutput(
        schema_version=request.schema_version,
        request_id=request.request_id,
        status="succeeded",
        result=EchoResult(message=request.message),
    )
