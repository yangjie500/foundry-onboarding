import logging

from pydantic import ValidationError

from foundry_onboarding.adapters.gitlab.client import create_gitlab_client
from foundry_onboarding.contracts.gitlab_user import GitLabUserInput
from foundry_onboarding.errors import ApplicationError, InvalidInputError
from foundry_onboarding.handlers.common import safe_request_id
from foundry_onboarding.runtime_configuration.gitlab import load_gitlab_configuration
from foundry_onboarding.services.gitlab_user import reconcile_gitlab_user

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def handler(event: object, _context: object) -> dict[str, object]:
    """Validate and reconcile a GitLab user without exposing sensitive data."""

    try:
        request = GitLabUserInput.model_validate(event)
    except ValidationError as error:
        logger.warning(
            "GitLab user provisioning rejected invalid input",
            extra={
                "request_id": safe_request_id(event),
                "validation_error_count": error.error_count(),
            },
        )
        raise InvalidInputError("GitLab user input is invalid") from None

    try:
        configuration = load_gitlab_configuration()
        client = create_gitlab_client(configuration)
        result = reconcile_gitlab_user(request, client)
    except ApplicationError as error:
        logger.warning(
            "GitLab user provisioning failed",
            extra={
                "request_id": str(request.request_id),
                "error_code": error.error_code,
            },
        )
        raise

    logger.info(
        "GitLab user provisioning completed",
        extra={
            "request_id": str(request.request_id),
            "status": result.status,
            "gitlab_user_id": result.result.id,
        },
    )

    return result.model_dump(mode="json")
