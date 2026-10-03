import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import pytest

from foundry_onboarding.adapters.aws.step_functions import WorkflowStartStatus
from foundry_onboarding.errors import ConfigurationError, InvalidInputError, WorkflowStartError
from foundry_onboarding.handlers import sqs_workflow_ingress
from foundry_onboarding.runtime_configuration.workflow_ingress import (
    WorkflowIngressConfiguration,
)

EVENTS_DIRECTORY = Path(__file__).parents[3] / "events" / "functions" / "sqs_workflow_ingress"
STATE_MACHINE_ARN = "arn:aws:states:us-east-1:111122223333:stateMachine:foundry-dev-onboarding"


def read_event(name: str) -> dict[str, object]:
    event = json.loads((EVENTS_DIRECTORY / name).read_text(encoding="utf-8"))
    assert isinstance(event, dict)
    return cast(dict[str, object], event)


@dataclass
class FakeWorkflowStarter:
    statuses: list[WorkflowStartStatus | Exception] = field(default_factory=list)
    calls: list[dict[str, str]] = field(default_factory=list)

    def start_workflow(self, **kwargs: str) -> WorkflowStartStatus:
        self.calls.append(kwargs)
        result = self.statuses.pop(0) if self.statuses else "started"
        if isinstance(result, Exception):
            raise result
        return result


@dataclass
class HandlerHarness:
    starter: FakeWorkflowStarter = field(default_factory=FakeWorkflowStarter)
    configuration: WorkflowIngressConfiguration = field(
        default_factory=lambda: WorkflowIngressConfiguration(STATE_MACHINE_ARN)
    )
    calls: list[str] = field(default_factory=list)


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> HandlerHarness:
    harness = HandlerHarness()

    def load_configuration() -> WorkflowIngressConfiguration:
        harness.calls.append("load_configuration")
        return harness.configuration

    def create_starter() -> FakeWorkflowStarter:
        harness.calls.append("create_starter")
        return harness.starter

    monkeypatch.setattr(
        sqs_workflow_ingress,
        "load_workflow_ingress_configuration",
        load_configuration,
    )
    monkeypatch.setattr(sqs_workflow_ingress, "create_step_functions", create_starter)
    return harness


def test_valid_batch_starts_workflow_and_returns_no_failures(harness: HandlerHarness) -> None:
    result = sqs_workflow_ingress.handler(read_event("valid-batch.json"), object())

    assert result == {"batchItemFailures": []}
    assert harness.calls == ["load_configuration", "create_starter"]
    assert len(harness.starter.calls) == 1
    assert harness.starter.calls[0]["state_machine_arn"] == STATE_MACHINE_ARN


def test_duplicate_execution_is_acknowledged(harness: HandlerHarness) -> None:
    harness.starter.statuses = ["duplicate"]

    result = sqs_workflow_ingress.handler(read_event("valid-batch.json"), object())

    assert result == {"batchItemFailures": []}


def test_mixed_batch_returns_only_invalid_records_and_continues(
    harness: HandlerHarness,
) -> None:
    result = sqs_workflow_ingress.handler(read_event("mixed-batch.json"), object())

    assert result == {
        "batchItemFailures": [
            {"itemIdentifier": "22222222-2222-4222-8222-222222222222"},
            {"itemIdentifier": "33333333-3333-4333-8333-333333333333"},
        ]
    }
    assert len(harness.starter.calls) == 2


def test_workflow_failure_marks_only_its_record_failed_and_continues(
    harness: HandlerHarness,
) -> None:
    harness.starter.statuses = [WorkflowStartError("sensitive detail"), "started"]

    result = sqs_workflow_ingress.handler(read_event("mixed-batch.json"), object())

    assert result == {
        "batchItemFailures": [
            {"itemIdentifier": "11111111-1111-4111-8111-111111111111"},
            {"itemIdentifier": "22222222-2222-4222-8222-222222222222"},
            {"itemIdentifier": "33333333-3333-4333-8333-333333333333"},
        ]
    }
    assert len(harness.starter.calls) == 2


def test_invalid_envelope_fails_before_loading_dependencies(harness: HandlerHarness) -> None:
    with pytest.raises(InvalidInputError, match="SQS event envelope is invalid"):
        sqs_workflow_ingress.handler(read_event("malformed-envelope.json"), object())

    assert harness.calls == []


@pytest.mark.parametrize(
    "event",
    [
        None,
        {},
        {"Records": []},
        {"Records": [None]},
        {"Records": [{"messageId": "valid-id", "body": 123, "eventSource": "aws:sqs"}]},
        {"Records": [{"messageId": "valid-id", "body": "{}", "eventSource": "aws:sns"}]},
    ],
)
def test_rejects_invalid_aws_event_envelopes(event: object, harness: HandlerHarness) -> None:
    with pytest.raises(InvalidInputError):
        sqs_workflow_ingress.handler(event, object())

    assert harness.calls == []


def test_configuration_failure_raises_for_full_batch(
    harness: HandlerHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_configuration() -> WorkflowIngressConfiguration:
        raise ConfigurationError("configuration unavailable")

    monkeypatch.setattr(
        sqs_workflow_ingress,
        "load_workflow_ingress_configuration",
        fail_configuration,
    )

    with pytest.raises(ConfigurationError):
        sqs_workflow_ingress.handler(read_event("valid-batch.json"), object())

    assert harness.starter.calls == []


def test_logs_only_safe_metadata(harness: HandlerHarness, caplog: pytest.LogCaptureFixture) -> None:
    harness.starter.statuses = [WorkflowStartError("sensitive AWS detail"), "duplicate"]

    with caplog.at_level(
        logging.INFO,
        logger="foundry_onboarding.handlers.sqs_workflow_ingress",
    ):
        sqs_workflow_ingress.handler(read_event("mixed-batch.json"), object())

    assert "Jane Smith" not in caplog.text
    assert "jane.smith@example.com" not in caplog.text
    assert "jane.smith" not in caplog.text
    assert "John Smith" not in caplog.text
    assert "john.smith@example.com" not in caplog.text
    assert "sensitive AWS detail" not in caplog.text
    failure_records = [
        record
        for record in caplog.records
        if record.getMessage() == "SQS onboarding workflow start failed"
    ]
    accepted_records = [
        record
        for record in caplog.records
        if record.getMessage() == "SQS onboarding message accepted"
    ]
    assert len(failure_records) == 1
    assert failure_records[0].__dict__["error_code"] == "WORKFLOW_START_ERROR"
    assert len(accepted_records) == 1
    assert accepted_records[0].__dict__["status"] == "duplicate"
