from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

EnvironmentName = Literal["dev", "staging", "production"]


class EnvironmentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    environment: EnvironmentName
    aws_region: str = Field(min_length=1)
    log_retention_days: int = Field(gt=0)
    enable_tracing: bool = True


def load_environment_config(environment: EnvironmentName) -> EnvironmentConfig:
    config_path = Path(__file__).parent.parent / "config" / f"{environment}.yaml"

    with config_path.open(encoding="utf-8") as config_file:
        raw_config = yaml.safe_load(config_file)

    config = EnvironmentConfig.model_validate(raw_config)

    if config.environment != environment:
        raise ValueError(
            f"Configuration environment {config.environment!r} does not match "
            f"requested environment {environment!r}"
        )

    return config
