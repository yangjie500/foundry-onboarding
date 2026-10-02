"""GitLab provider adapters."""

from foundry_onboarding.adapters.gitlab.client import (
    GitLabClient,
    GitLabUserRecord,
    create_gitlab_client,
)

__all__ = ["GitLabClient", "GitLabUserRecord", "create_gitlab_client"]
