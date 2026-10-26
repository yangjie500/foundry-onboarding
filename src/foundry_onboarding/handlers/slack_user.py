import logging

from pydantic import ValidationError

from foundry_onboarding.adapters.slack.client import create_slack_client
from foundry_onboarding.contracts.slack_user import SlackUserInput
from foundry_onboarding.errors import ApplicationError, InvalidInputError
from foundry_onboarding.handlers.common import safe_request_id
from foundry_onboarding.runtime_configuration.slack import load_slack_configuration
from foundry_onboarding.services.slack_user import reconcile_slack_user

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def handler(event: object, _context: object) -> dict[str, object]:
    """Validate and reconcile a Slack invitation without exposing sensitive data."""

    try:
        request = SlackUserInput.model_validate(event)
    except ValidationError as error:
        logger.warning(
            "Slack user provisioning rejected invalid input",
            extra={
                "request_id": safe_request_id(event),
                "validation_error_count": error.error_count(),
            },
        )
        raise InvalidInputError("Slack user input is invalid") from None

    try:
        configuration = load_slack_configuration()
        client = create_slack_client(configuration)
        result = reconcile_slack_user(request, client)
    except ApplicationError as error:
        logger.warning(
            "Slack user provisioning failed",
            extra={
                "request_id": str(request.request_id),
                "error_code": error.error_code,
            },
        )
        raise

    logger.info(
        "Slack user provisioning completed",
        extra={
            "request_id": str(request.request_id),
            "status": result.status,
        },
    )

    return result.model_dump(mode="json")
