from typing import ClassVar


class ApplicationError(Exception):
    """Base class for expected application failures."""

    error_code: ClassVar[str] = "APPLICATION_ERROR"


class InvalidInputError(ApplicationError):
    """Raised when a Lambda event violates its input contract."""

    error_code: ClassVar[str] = "INVALID_INPUT"


class ConfigurationError(ApplicationError):
    """Raised when required runtime configuration cannot be loaded."""

    error_code: ClassVar[str] = "CONFIGURATION_ERROR"


class GitLabAuthenticationError(ApplicationError):
    """Raised when GitLab rejects the configured API credential."""

    error_code: ClassVar[str] = "GITLAB_AUTHENTICATION_ERROR"


class GitLabRequestError(ApplicationError):
    """Raised when GitLab permanently rejects a user request."""

    error_code: ClassVar[str] = "GITLAB_REQUEST_ERROR"


class GitLabUnavailableError(ApplicationError):
    """Raised when GitLab cannot be reached or should be retried later."""

    error_code: ClassVar[str] = "GITLAB_UNAVAILABLE"


class GitLabProtocolError(ApplicationError):
    """Raised when GitLab returns an unexpected or malformed response."""

    error_code: ClassVar[str] = "GITLAB_PROTOCOL_ERROR"


class GitLabIdentityConflictError(ApplicationError):
    """Raised when an existing GitLab identity conflicts with a request."""

    error_code: ClassVar[str] = "GITLAB_IDENTITY_CONFLICT"
