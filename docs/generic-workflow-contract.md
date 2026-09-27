# Generic Workflow Contract

## Purpose

This contract supports a minimal Lambda and Step Functions deployment while the
final onboarding requirements are still being determined.

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

The only currently supported action is `echo`.

The request is implemented by `GenericWorkflowInput` in
`foundry_onboarding.contracts.generic_workflow`.

## Generic processor input

Step Functions transforms the public workflow input into the smaller Lambda
input below:

- `schema_version`
- `request_id`
- `message`

The Lambda does not receive `action` or the nested workflow `payload`. Its input
is implemented by `GenericProcessorInput` in
`foundry_onboarding.contracts.generic_processor`.

## Output

A successful execution returns:

- `schema_version`
- `request_id`
- `status`
- `result`

The output must preserve the input request ID.

The response is implemented by `GenericProcessorOutput` in
`foundry_onboarding.contracts.generic_processor`.

## Invalid input

A request is invalid when:

- The schema version is unsupported.
- The request ID is not a UUID.
- The action is unsupported.
- The message is empty.
- An unknown field is present.

Invalid input is a permanent error and should not be retried.

## Sensitive data

Requests must not contain credentials, passwords, access tokens, or other
secrets. The complete payload must not be written to logs.

## Contract organization

Fields shared by workflow states belong in `contracts/common.py`. Public
workflow-start contracts and Lambda invocation contracts are kept in separate
modules. Each Lambda owns its input, output, and result models. Provider-specific
fields must not be added to the common contract.
