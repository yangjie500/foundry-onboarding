# Slack user onboarding plan

## Status and objective

This document records the proposed implementation plan for adding Slack user
onboarding through Slack's `admin.users.invite` API method.

The target onboarding flow is:

```text
SQS
  -> workflow-ingress Lambda
  -> Step Functions
  -> GitLab user Lambda
  -> Slack user Lambda
  -> provider-safe onboarding result
```

The Slack Lambda input and output contracts, fixtures, contract tests, typed
infrastructure references, runtime loader, API adapter, provider error model,
service, Lambda handler, and focused tests are implemented. Packaging,
definitions and hashed requirements, CDK infrastructure, workflow
orchestration, and sanitized combined output are implemented. The Docker
artifact build has not been run. Do not deploy the integration until the
remaining operational details and package validation in this document are
resolved and the development change set has been reviewed.

## Slack prerequisites

Before implementation, confirm all of the following:

- The target Slack organization is on an Enterprise plan.
- The target workspace ID is known.
- At least one channel ID is available for every invitation.
- A Slack app can be installed across the Enterprise organization by an org
  admin or owner.
- The app can receive the `admin.users:write` scope.
- The resulting user OAuth token can be stored through the approved secret
  entry and rotation process.

`admin.users.invite` requires a user OAuth token with `admin.users:write`. A bot
token is not sufficient. The app must be installed on the Enterprise
organization rather than only an individual workspace.

Every API request requires:

- `team_id`: target workspace ID.
- `email`: email address to invite.
- `channel_ids`: a comma-separated list containing at least one channel ID.

The API also accepts the user's real name, guest membership options, an
optional invitation message, and an optional guest expiration timestamp. The
documented rate limit is Tier 2, currently 20 or more requests per minute.

References:

- [Slack `admin.users.invite` reference](https://docs.slack.dev/reference/methods/admin.users.invite/)
- [Slack user administration guide](https://docs.slack.dev/admins/managing-users/)
- [Slack Admin API installation requirements](https://docs.slack.dev/reference/scopes/admin.invites.read/)

## Accepted defaults and remaining operational details

The following product defaults are accepted:

- Invite full workspace members.
- Treat an existing member as successful reconciliation.
- Treat an existing pending invitation as successful reconciliation.
- Do not resend invitations automatically.
- Do not add a custom invitation message initially.
- Keep GitLab external-user status independent from Slack membership type.
- Plan initially for no more than 10 invitations per minute.

The concrete workspace ID, default channel IDs, Slack app owner, and token
rotation owner remain to be recorded before development integration testing.

A Slack OAuth token has already been obtained outside the repository. Its
value must remain outside source code, fixtures, documentation, YAML, workflow
state, and shell history. Before using it, verify that it is a user token with
`admin.users:write` from an organization-wide installation.

## Remaining operational details

Record these remaining operational details:

1. Which Enterprise workspace receives new users?
2. Which channels must every new user join?
3. Who owns the Slack app and organization-wide installation?
4. Who owns token rotation?

Do not automatically map the existing GitLab `external` field to a Slack guest
type. GitLab external-user status and Slack guest membership have different
provider meanings. Add an explicit shared business rule or a dedicated Slack
field if guest membership is required.

## Implemented contracts

The models are implemented in
`src/foundry_onboarding/contracts/slack_user.py` with fixtures under
`events/functions/slack_user/` and focused tests in
`tests/contract/test_slack_user_contract.py`.

The Slack Lambda input should contain only workflow identity and business data:

```json
{
  "schema_version": "1.0",
  "request_id": "f084a40c-2d45-4bc9-96b2-d650bb746413",
  "name": "Jane Smith",
  "email": "jane.smith@example.com"
}
```

Workspace IDs, channel IDs, and credentials belong in runtime configuration,
not workflow input.

Recommended output statuses are:

- `invited`: Slack accepted a new invitation.
- `already_member`: Slack returned `already_in_team`.
- `already_invited`: Slack returned `already_in_team_invited_user`.

Slack's normal success response contains only `{"ok": true}`. Do not invent or
return a Slack user ID when the API did not provide one. A successful Lambda
response can therefore remain minimal:

```json
{
  "schema_version": "1.0",
  "request_id": "f084a40c-2d45-4bc9-96b2-d650bb746413",
  "status": "invited"
}
```

Unknown fields must be rejected. Credentials and provider configuration must
never be accepted through the public workflow contract.

## Implemented runtime configuration

`IntegrationSettings` now contains typed Slack configuration references such
as:

```yaml
integrations:
  slack:
    team_id_parameter_name: /foundry/dev/slack/team-id
    channel_ids_parameter_name: /foundry/dev/slack/channel-ids
    credentials_secret_name: foundry/dev/slack/credentials
```

Use Parameter Store for non-secret configuration:

```text
/foundry/<environment>/onboarding/allowed-email-domains
/foundry/<environment>/slack/team-id
/foundry/<environment>/slack/channel-ids
```

The onboarding parameter contains a comma-separated list of exact permitted
email domains. Matching is case-insensitive, but subdomains must be listed
explicitly; wildcards are not supported. GitLab and Slack enforce the same
policy before calling either provider.

Use Secrets Manager for the user OAuth token:

```json
{
  "user_token": "stored-through-an-approved-secret-entry-process"
}
```

The planned integration documentation previously mentioned `bot_token` and
`signing_secret`. The implemented design corrects that:

- `admin.users.invite` requires a user token.
- A signing secret is unnecessary because this Lambda makes outbound requests
  and does not receive Slack webhooks or interactive requests.

Pass only references to Lambda environment variables:

```text
APP_ENV=dev
SLACK_TEAM_ID_PARAMETER_NAME=/foundry/dev/slack/team-id
SLACK_CHANNEL_IDS_PARAMETER_NAME=/foundry/dev/slack/channel-ids
SLACK_CREDENTIALS_SECRET_NAME=foundry/dev/slack/credentials
```

`runtime_configuration/slack.py` loads and validates the parameters and secret
through the existing reusable AWS adapters. It validates nonblank values, the
Slack workspace ID, the channel list, duplicate channel IDs, and the presence
of a nonblank user token. It retrieves current values on every call so token
rotation is visible without a warm-runtime cache. Resolved values are not
logged.

## Implemented Slack API adapter

`adapters/slack/client.py` follows the existing GitLab adapter boundary and
calls:

```http
POST https://slack.com/api/admin.users.invite
Authorization: Bearer <user OAuth token>
Content-Type: application/json; charset=utf-8
```

The request body should contain only approved fields:

```json
{
  "team_id": "T12345678",
  "email": "jane.smith@example.com",
  "channel_ids": "C12345678,C87654321",
  "real_name": "Jane Smith"
}
```

Add guest flags, guest expiration, resend behavior, or a custom message only
after the corresponding product decisions are explicit.

Slack commonly reports application errors in an HTTP 200 response with
`{"ok": false, "error": "..."}`. The adapter validates the HTTP status,
parses a bounded JSON response, and inspects `ok` and `error`.

Use explicit timeouts and a safe user agent. Never include the token in the URL,
request body, exception message, logs, representation, or test failure output.

## Implemented error model

The provider-specific application errors are:

```text
SlackAuthenticationError
SlackRequestError
SlackUnavailableError
SlackProtocolError
```

Recommended classifications:

### Successful reconciliation

- `already_in_team` becomes `already_member`.
- `already_in_team_invited_user` becomes `already_invited`.

This makes a retry after an uncertain result safe.

### Authentication or configuration failures

Examples include:

- `invalid_auth`
- `not_authed`
- `token_expired`
- `token_revoked`
- `missing_scope`
- `not_allowed_token_type`
- `not_an_admin`
- `failed_to_validate_caller`
- `team_access_not_granted`

These raise `SlackAuthenticationError` or `ConfigurationError` and should not
be retried automatically.

### Permanent request failures

Examples include invalid email, team, channel, guest, expiration, or custom
message arguments. These raise `SlackRequestError` and should not be retried
automatically.

### Transient or uncertain failures

Examples include:

- HTTP 429 and Slack `ratelimited` responses.
- HTTP 5xx responses.
- `service_unavailable`.
- `internal_error` or `fatal_error`, where Slack warns that some work may have
  succeeded.
- Connection and read timeouts.

These raise `SlackUnavailableError`. A retry that encounters an existing
member or pending invitation then resolves successfully through the statuses
above.

Malformed, oversized, or contradictory Slack responses raise
`SlackProtocolError` without exposing response contents.

## Implemented service and handler

The implementation is in:

```text
src/foundry_onboarding/services/slack_user.py
src/foundry_onboarding/handlers/slack_user.py
```

The service depends on a small gateway protocol and translates adapter results
into the typed Slack output. The handler follows the existing GitLab
composition pattern:

1. Validate input before loading configuration.
2. Load and enforce the shared email-domain policy.
3. Load Slack runtime configuration.
4. Create the Slack client.
5. Invoke the service.
6. Return the typed, provider-safe output.

Safe logs may contain:

- Request ID.
- Reconciliation status.
- Application error code.

Logs must not contain:

- Email address or real name.
- User token.
- Workspace or channel configuration unless explicitly approved as safe.
- Raw Slack request or response bodies.
- Secrets Manager values.

## Deployment package

The separate `lambda-slack` dependency group contains:

- boto3
- email-validator
- Pydantic
- urllib3

The packaging configuration defines:

```text
requirements/slack-user.txt
build/slack-user/
foundry_onboarding.handlers.slack_user.handler
```

The following are updated:

- `pyproject.toml` and `uv.lock`.
- `Makefile` requirements and package targets.
- `scripts/build-lambda-asset.sh` guarded target list and verification.
- `docs/development-workflow.md` package documentation.

The Docker build uses Python 3.14 on `linux/amd64`, hashed requirements, binary
wheels only, and container import verification. It remains to be run on a
machine with a working Docker daemon.

## CDK infrastructure

A separate function is implemented with the name:

```text
foundry-<environment>-slack-user
```

It uses `StandardPythonLambda`, allows code injection in infrastructure tests,
and configures only reference environment variables.

The function is granted:

- `ssm:GetParameters` for only the shared email-domain allowlist and configured
  Slack team and channel parameters.
- `secretsmanager:GetSecretValue` for only the Slack credential secret.
- No explicit `kms:Decrypt` permission because the current configuration does
  not identify a customer-managed KMS key. Add exact-key access if one is used.

The Slack Lambda must not be able to read GitLab parameters or unrelated
secrets. Do not put the user token in CDK context, YAML, CloudFormation
parameters, Lambda environment variables, fixtures, or stack outputs.

The stack outputs the Slack function name. It does not output secret names or
values.

## Implemented Step Functions changes

The GitLab result is stored separately so the original onboarding input remains
available for the Slack invocation. The Slack result is then stored separately,
and a final transformation removes the original payload from successful output.

The intermediate state shape is:

```json
{
  "schema_version": "1.0",
  "request_id": "...",
  "action": "onboard_user",
  "payload": {
    "username": "jane.smith",
    "name": "Jane Smith",
    "email": "jane.smith@example.com",
    "external": false
  },
  "gitlab": {
    "status": "created",
    "result": {
      "id": 123,
      "username": "jane.smith"
    }
  },
  "slack": {
    "status": "invited"
  }
}
```

The workflow uses explicit Step Functions transformations:

1. Validate the onboarding input.
2. Invoke GitLab with only its allowed fields.
3. Store the GitLab result without replacing the original payload.
4. Invoke Slack with only schema version, request ID, name, and email.
5. Store the Slack result.
6. Transform the state into a final correlation-safe result that excludes name,
   email, credentials, and raw provider responses.

Slack-specific failure states cover:

- Configuration or authentication failure.
- Permanent provisioning rejection.
- Unexpected provider protocol failure.

The shared permanent `Onboarding policy rejected` state handles a domain that
is not explicitly allowlisted. Neither provider task retries this error.

The Slack task retries only:

- `SlackUnavailableError`.
- Transient Lambda service errors.

Use exponential backoff and full jitter. Preserve safe Step Functions logging
with `IncludeExecutionData` disabled.

## Partial-success policy

Use forward recovery rather than compensation:

- Do not delete or deactivate a successfully created GitLab account when Slack
  invitation fails.
- Retry transient Slack failures in the workflow.
- Surface a Slack-stage failure after retries are exhausted.
- Permit the same onboarding request to run again.
- Let GitLab return `existing` and Slack return `already_member` or
  `already_invited` on a repeated execution.

This policy avoids destructive rollback and makes provider operations
reconcilable after uncertain failures.

## Rate-limit strategy

The Slack endpoint is documented as Tier 2, currently 20 or more calls per
minute. The existing SQS ingress may start several workflow executions in a
short period, so rate limiting must be considered across concurrent workflows.

For controlled, low-volume development traffic:

- Translate HTTP 429 and `ratelimited` to `SlackUnavailableError`.
- Use bounded Step Functions retries with exponential backoff and full jitter.
- Monitor throttling and exhausted retries.

Before production, estimate the maximum invitation burst. If it can exceed the
Slack limit, add a shared rate-control mechanism such as a dedicated Slack work
queue and controlled consumer or a central token-bucket implementation.
Step Functions retry settings alone do not enforce a global rate across
concurrent executions.

## Tests

### Contract tests

- Accept valid input and each valid status.
- Reject malformed UUIDs and email addresses.
- Reject blank or oversized names.
- Reject unknown fields and credentials.

### Runtime configuration tests

- Load the expected Parameter Store values and Secrets Manager field.
- Reject missing, blank, duplicate, or malformed configuration.
- Reject missing or malformed `user_token` secret data.
- Ensure validation errors do not reveal secret values.

### Adapter tests

- Send the exact HTTP method, URL, headers, and JSON fields.
- Handle `{"ok": true}`.
- Reconcile `already_in_team` and `already_in_team_invited_user`.
- Classify authentication, request, rate-limit, HTTP, network, and protocol
  errors.
- Respect explicit connect and read timeouts.
- Never expose token, email, name, or raw response body in exceptions or logs.

### Service tests

- Return `invited`, `already_member`, and `already_invited` correctly.
- Propagate typed provider errors.
- Avoid local retry loops; orchestration owns workflow retries.

### Handler tests

- Reject invalid input before loading configuration.
- Compose the loader, adapter, and service correctly.
- Return JSON-compatible typed output.
- Log only approved metadata on success and failure.

### Infrastructure tests

- Create exactly one Slack Lambda with the expected handler and runtime.
- Inject inline code so unit tests do not require Docker.
- Pass only configuration references through environment variables.
- Grant exact SSM and Secrets Manager access.
- Prove the role cannot access GitLab configuration or wildcard secrets.
- Confirm no secret value appears in the synthesized template.

### Workflow tests

- Invoke GitLab before Slack.
- Preserve the original input between provider tasks.
- Pass only the allowed fields to Slack.
- Retry only transient Slack and Lambda service errors.
- Route permanent Slack errors to the correct failure state.
- Return a sanitized combined result.
- Preserve disabled execution-data logging.

### Packaging tests

- Export a hashed Slack-only requirements file.
- Build `build/slack-user` in the SAM Python 3.14 image.
- Verify the handler and required native dependencies import in the container.
- Keep the generated artifact ignored by Git.

## Development rollout

1. Resolve the product and operational decisions in this document.
2. Create and configure the Slack app with `admin.users:write`.
3. Install it across the Enterprise organization as an org admin or owner.
4. Store the user OAuth token through an approved secret-entry process.
5. Create the environment-specific team and channel parameters.
6. Contracts, configuration, the API adapter, service, and handler are
   complete.
7. The CDK resources are complete; validate the package on a Docker-capable
   machine.
8. The Step Functions workflow and final output transformation are complete.
9. Run:

   ```bash
   uv lock
   make package
   make check ENV=dev
   git diff --check
   ```

10. Review `cdk diff` for exact IAM, environment references, workflow changes,
    and absence of secrets.
11. Deploy only the development environment after review.
12. Test with a controlled email address.
13. Repeat the same request to verify idempotent reconciliation.
14. Exercise a controlled transient failure and verify retry behavior.
15. Review CloudWatch logs and Step Functions history for sensitive-data
    exposure before enabling normal traffic.

## Acceptance criteria

The Slack integration is ready for development deployment when:

- Enterprise plan and org-wide Slack app installation are confirmed.
- The token is a user OAuth token with `admin.users:write`.
- Workspace, channel, membership, duplicate, and resend policies are approved.
- Slack credentials exist only in Secrets Manager.
- The Slack Lambda has least-privilege access to its exact configuration.
- A new email can be invited successfully.
- Repeating the request produces an idempotent success status.
- Transient Slack failures are retried and permanent failures are not.
- GitLab success followed by Slack failure can be recovered by rerunning the
  onboarding request.
- Workflow output and logs exclude email, name, credentials, and raw provider
  responses.
- Rate-limit behavior is tested at the expected development load.
- The Slack deployment artifact builds and imports successfully in the Python
  3.14 `linux/amd64` container.
- Ruff, strict mypy, pytest, CDK synthesis, and `git diff --check` pass.
- The CDK diff contains no secret values or unintended broad IAM permissions.
