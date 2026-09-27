from uuid import UUID

from foundry_onboarding.contracts.generic_processor import GenericProcessorInput
from foundry_onboarding.services.generic_processor import process_request

REQUEST_ID = UUID("8e95a486-d4e4-4aee-afc7-327f029311ee")


def test_process_request_returns_successful_result() -> None:
    request = GenericProcessorInput(
        schema_version="1.0",
        request_id=REQUEST_ID,
        message="Hello from Step Functions",
    )

    result = process_request(request)

    assert result.schema_version == "1.0"
    assert result.status == "succeeded"
    assert result.result.message == "Hello from Step Functions"


def test_process_request_preserves_request_identity() -> None:
    request = GenericProcessorInput(
        schema_version="1.0",
        request_id=REQUEST_ID,
        message="Identity must be preserved",
    )

    result = process_request(request)

    assert result.request_id == request.request_id


def test_process_request_returns_json_compatible_output() -> None:
    request = GenericProcessorInput(
        schema_version="1.0",
        request_id=REQUEST_ID,
        message="Serialize me",
    )

    result = process_request(request)
    serialized = result.model_dump(mode="json")

    assert serialized == {
        "schema_version": "1.0",
        "request_id": str(REQUEST_ID),
        "status": "succeeded",
        "result": {
            "message": "Serialize me",
        },
    }


def test_process_request_does_not_modify_input() -> None:
    request = GenericProcessorInput(
        schema_version="1.0",
        request_id=REQUEST_ID,
        message="Original message",
    )

    process_request(request)

    assert request.message == "Original message"
