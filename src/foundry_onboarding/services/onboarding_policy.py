import re
from collections.abc import Collection

from foundry_onboarding.errors import OnboardingPolicyRejectedError

_DOMAIN_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def normalize_email_domain(value: str) -> str:
    """Return a lowercase ASCII domain suitable for exact policy matching."""

    candidate = value.strip().removesuffix(".")
    if not candidate or len(candidate) > 253:
        raise ValueError("email domain is invalid")

    try:
        normalized = candidate.encode("idna").decode("ascii").lower()
    except UnicodeError:
        raise ValueError("email domain is invalid") from None

    labels = normalized.split(".")
    if any(not _DOMAIN_LABEL.fullmatch(label) for label in labels):
        raise ValueError("email domain is invalid")

    return normalized


def require_allowed_email_domain(
    email: str,
    allowed_domains: Collection[str],
) -> None:
    """Reject an email whose normalized domain is not explicitly allowed."""

    separator_index = email.rfind("@")
    if separator_index < 1:
        raise OnboardingPolicyRejectedError("Email domain is not allowed")

    try:
        domain = normalize_email_domain(email[separator_index + 1 :])
    except ValueError:
        raise OnboardingPolicyRejectedError("Email domain is not allowed") from None

    if domain not in allowed_domains:
        raise OnboardingPolicyRejectedError("Email domain is not allowed")
