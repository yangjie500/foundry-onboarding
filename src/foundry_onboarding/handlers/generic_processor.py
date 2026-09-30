import logging

from pydantic import ValidationError

from foundry_onboarding.contracts.generic_processor import GenericProcessorInput
from foundry_onboarding.errors import InvalidInputError
from foundry_onboarding.runtime_configuration.generic_processor import (
    load_generic_processor_parameters,
)
from foundry_onboarding.services.generic_processor import process_request

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _safe_request_id(event: object) -> str:
    """Return a request ID without trusting the incoming event shape."""

    if not isinstance(event, dict):
        return "unknown"

    request_id = event.get("request_id")

    if not isinstance(request_id, str):
        return "unknown"

    return request_id


def handler(event: object, _context: object) -> dict[str, object]:
    """Validate and process a generic Lambda invocation."""

    try:
        request = GenericProcessorInput.model_validate(event)
    except ValidationError as error:
        logger.warning(
            "Generic processor rejected invalid input",
            extra={
                "request_id": _safe_request_id(event),
                "validation_error_count": error.error_count(),
            },
        )
        raise InvalidInputError("Generic processor input is invalid") from error

    parameters = load_generic_processor_parameters()
    result = process_request(request, parameters)

    logger.info(
        "Generic processor completed request",
        extra={
            "request_id": str(request.request_id),
            "status": result.status,
        },
    )

    return result.model_dump(mode="json")
