import subprocess
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).parents[2]
REQUIREMENTS_FILE = REPOSITORY_ROOT / "requirements" / "slack-user.txt"
BUILD_SCRIPT = REPOSITORY_ROOT / "scripts" / "build-lambda-asset.sh"


def test_slack_requirements_are_pinned_and_hashed() -> None:
    lines = REQUIREMENTS_FILE.read_text(encoding="utf-8").splitlines()
    package_indexes = [
        index
        for index, line in enumerate(lines)
        if line and not line.startswith((" ", "#")) and "==" in line
    ]

    assert package_indexes
    for index in package_indexes:
        assert lines[index].endswith("\\")
        assert lines[index + 1].lstrip().startswith("--hash=sha256:")

    requirements = "\n".join(lines)
    for dependency in ("boto3", "email-validator", "pydantic", "urllib3"):
        assert f"\n{dependency}==" in f"\n{requirements}"


def test_slack_package_target_is_guarded_and_imports_the_handler() -> None:
    makefile = (REPOSITORY_ROOT / "Makefile").read_text(encoding="utf-8")
    script = BUILD_SCRIPT.read_text(encoding="utf-8")

    assert "--only-group lambda-slack" in makefile
    assert "./scripts/build-lambda-asset.sh slack-user" in makefile
    assert '"${REPOSITORY_ROOT}/build/slack-user"' in script
    assert "foundry_onboarding.handlers.slack_user.handler" in script

    result = subprocess.run(
        ["bash", "-n", str(BUILD_SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
