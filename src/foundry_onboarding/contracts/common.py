from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ContractModel(BaseModel):
    """Shared validation rules for workflow contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class WorkflowIdentity(ContractModel):
    """Fields that identify a request throughout a workflow execution."""

    schema_version: Literal["1.0"]
    request_id: UUID
