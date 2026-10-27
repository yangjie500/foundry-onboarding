import pytest

from foundry_onboarding.errors import OnboardingPolicyRejectedError
from foundry_onboarding.services.onboarding_policy import (
    normalize_email_domain,
    require_allowed_email_domain,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Example.COM", "example.com"),
        ("example.com.", "example.com"),
        ("bücher.example", "xn--bcher-kva.example"),
    ],
)
def test_normalize_email_domain(value: str, expected: str) -> None:
    assert normalize_email_domain(value) == expected


@pytest.mark.parametrize(
    "value",
    ["", " ", ".example.com", "example..com", "-example.com", "example-.com", "*.com"],
)
def test_normalize_email_domain_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValueError, match="email domain is invalid"):
        normalize_email_domain(value)


def test_policy_accepts_an_exact_domain_case_insensitively() -> None:
    require_allowed_email_domain(
        "Jane.Smith@Example.COM",
        ("example.com", "subsidiary.example.com"),
    )


@pytest.mark.parametrize(
    "email",
    [
        "jane@engineering.example.com",
        "jane@fake-example.com",
        "jane@other.example",
    ],
)
def test_policy_rejects_domains_that_are_not_explicitly_allowed(email: str) -> None:
    with pytest.raises(OnboardingPolicyRejectedError, match="Email domain is not allowed"):
        require_allowed_email_domain(email, ("example.com",))


def test_policy_error_does_not_expose_the_email_or_domain() -> None:
    email = "sensitive@private.example"

    with pytest.raises(OnboardingPolicyRejectedError) as raised:
        require_allowed_email_domain(email, ("example.com",))

    assert email not in str(raised.value)
    assert "private.example" not in str(raised.value)
