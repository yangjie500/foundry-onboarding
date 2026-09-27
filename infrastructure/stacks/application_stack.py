from typing import Any

from aws_cdk import Stack
from constructs import Construct

from infrastructure.configuration import EnvironmentConfig


class ApplicationStack(Stack):
    def __init__(
        self, scope: Construct, construct_id: str, *, config: EnvironmentConfig, **kwargs: Any
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.config = config
