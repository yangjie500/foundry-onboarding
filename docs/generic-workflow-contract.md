# Generic Workflow Contract

## Purpose

This contract supports a minimal generic operation and the current GitLab user
onboarding operation while the later SQS and Slack requirements are still being
determined.

## Version

The current schema version is `1.0`.

Removing fields, renaming fields, or changing their meaning requires a new
schema version.

## Input

The workflow accepts:

- `schema_version`: Contract version.
- `request_id`: UUID used for correlation.
- `action`: Operation requested by the caller.
- `payload`: Action-specific input.

The supported actions are:

- `echo`, with `payload.message`.
- `onboard_user`, with `payload.username`, `payload.name`, `payload.email`, and
  the strict boolean `payload.external`.

The action and payload shape must match. Unknown fields are rejected by the
Pydantic public contract.

The request is implemented by `GenericWorkflowInput` in
`foundry_onboarding.contracts.generic_workflow`.

## State-machine validation

The state machine checks the action, schema version, presence, and basic JSON
types before invoking a task. Step Functions Choice rules do not fully validate
UUID, email, username, length, or unknown-field constraints. Each Lambda
therefore performs strict Pydantic validation after the workflow explicitly
selects its allowed fields. The planned SQS ingress Lambda will validate the
dedicated `SqsOnboardingMessage` contract before starting the workflow; its
proposed external contract is documented in `docs/sqs-onboarding-contract.md`.

## Echo transformation

Step Functions transforms the public workflow input into the smaller Lambda
input below:

- `schema_version`
- `request_id`
- `message`

The Lambda does not receive `action` or the nested workflow `payload`. Its input
is implemented by `GenericProcessorInput` in
`foundry_onboarding.contracts.generic_processor`.

## Echo output

A successful execution returns:

- `schema_version`
- `request_id`
- `status`
- `result.message`: The echoed input message.
- `result.example_variable`: The non-secret example value loaded from Parameter
  Store.
- `result.example_secret_loaded`: Whether the example `SecureString` was loaded.

The output must preserve the input request ID.

The response is implemented by `GenericProcessorOutput` in
`foundry_onboarding.contracts.generic_processor`.

## Onboarding transformation

For `onboard_user`, Step Functions invokes the GitLab user Lambda with only:

- `schema_version`
- `request_id`
- `username`
- `name`
- `email`
- `external`

The Lambda does not receive `action` or the nested workflow `payload`. Its input
and output are implemented by `GitLabUserInput` and `GitLabUserOutput` in
`foundry_onboarding.contracts.gitlab_user`.

A successful GitLab operation returns:

- `schema_version`
- `request_id`
- `status`: `created` or `existing`
- `result.id`: GitLab's numeric user ID
- `result.username`: The reconciled username

The workflow does not return the email address, name, token, or raw GitLab
response.

## Retries and failures

The GitLab task retries `GitLabUnavailableError` and AWS Lambda service or
throttling failures using the configured bounded exponential backoff with full
jitter. Validation, configuration, authentication, identity conflict, request,
and protocol failures are not retried.

Caught error payloads are discarded before the workflow enters a safe Fail
state. Failures distinguish invalid input, GitLab configuration/authentication,
provisioning rejection, and other GitLab integration failures.

## Invalid input

A request is invalid when:

- The schema version is unsupported.
- The request ID is not a UUID.
- The action is unsupported.
- The selected action's payload is missing required fields or contains invalid
  values.
- An unknown field is present.

Invalid input is a permanent error and is not retried. Unsupported actions are
routed to a separate permanent failure.

## Sensitive data

Requests must not contain credentials, passwords, access tokens, or other
secrets. Step Functions logging has `IncludeExecutionData` disabled. Standard
workflow execution history still contains the business input and safe task
output, so access to execution history must remain restricted.

The generic processor and GitLab Lambda retrieve their configuration directly
from Parameter Store. Parameter values and raw provider responses must never
appear in workflow input, output, history, fixtures, or logs.

## Contract organization

Fields shared by workflow states belong in `contracts/common.py`. Public
workflow-start contracts and Lambda invocation contracts are kept in separate
modules. Each Lambda owns its input, output, and result models. Provider-specific
fields must not be added to the common contract.
