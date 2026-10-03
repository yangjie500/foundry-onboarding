import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import ValidationError

from foundry_onboarding.adapters.aws.step_functions import create_step_functions
from foundry_onboarding.contracts.sqs_onboarding import SqsOnboardingMessage
from foundry_onboarding.errors import ApplicationError, InvalidInputError
from foundry_onboarding.runtime_configuration.workflow_ingress import (
    load_workflow_ingress_configuration,
)
from foundry_onboarding.services.workflow_ingress import start_onboarding_workflow

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_MESSAGE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


@dataclass(frozen=True, slots=True)
class _SqsRecord:
    message_id: str
    body: str


def handler(event: object, _context: object) -> dict[str, list[dict[str, str]]]:
    """Validate SQS records and start one onboarding workflow per valid message."""

    records = _extract_records(event)
    configuration = load_workflow_ingress_configuration()
    starter = create_step_functions()
    failures: list[dict[str, str]] = []

    for record in records:
        try:
            message = SqsOnboardingMessage.model_validate_json(record.body)
        except ValidationError as error:
            logger.warning(
                "SQS onboarding message rejected",
                extra={
                    "message_id": record.message_id,
                    "validation_error_count": error.error_count(),
                },
            )
            failures.append({"itemIdentifier": record.message_id})
            continue

        try:
            status = start_onboarding_workflow(
                message,
                configuration.state_machine_arn,
                starter,
            )
        except ApplicationError as error:
            logger.warning(
                "SQS onboarding workflow start failed",
                extra={
                    "message_id": record.message_id,
                    "request_id": str(message.request_id),
                    "error_code": error.error_code,
                },
            )
            failures.append({"itemIdentifier": record.message_id})
            continue

        logger.info(
            "SQS onboarding message accepted",
            extra={
                "message_id": record.message_id,
                "request_id": str(message.request_id),
                "status": status,
            },
        )

    return {"batchItemFailures": failures}


def _extract_records(event: object) -> list[_SqsRecord]:
    if not isinstance(event, Mapping):
        raise InvalidInputError("SQS event envelope is invalid")

    raw_records = event.get("Records")
    if not isinstance(raw_records, list) or not raw_records:
        raise InvalidInputError("SQS event envelope is invalid")

    records: list[_SqsRecord] = []
    for raw_record in raw_records:
        if not isinstance(raw_record, Mapping):
            raise InvalidInputError("SQS event envelope is invalid")

        message_id = raw_record.get("messageId")
        body = raw_record.get("body")
        event_source = raw_record.get("eventSource")
        if (
            not isinstance(message_id, str)
            or _MESSAGE_ID_PATTERN.fullmatch(message_id) is None
            or not isinstance(body, str)
            or event_source != "aws:sqs"
        ):
            raise InvalidInputError("SQS event envelope is invalid")

        records.append(_SqsRecord(message_id=message_id, body=body))

    return records
