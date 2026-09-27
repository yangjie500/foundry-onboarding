from typing import ClassVar


class ApplicationError(Exception):
    """Base class for expected application failures."""

    error_code: ClassVar[str] = "APPLICATION_ERROR"


class InvalidInputError(ApplicationError):
    """Raised when a Lambda event violates its input contract."""

    error_code: ClassVar[str] = "INVALID_INPUT"
