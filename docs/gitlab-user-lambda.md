# GitLab user Lambda

## Purpose and current scope

The GitLab user Lambda creates or reconciles one user in a self-managed GitLab
instance. CDK defines it as `foundry-<environment>-gitlab-user` with the handler
`foundry_onboarding.handlers.gitlab_user.handler`.

The function is independently invokable and is also called by the generic Step
Functions workflow for the `onboard_user` action. It is not an SQS consumer;
the development SQS event source invokes a dedicated ingress Lambda, which
validates the message and starts the workflow before the workflow invokes this
function.

For a valid request, the service:

1. Searches for an exact, case-insensitive username match.
2. Searches for an exact, case-insensitive email match if the username is not
   found.
3. Returns `existing` only when username, email, `external`, and active state
   are compatible with the request.
4. Creates the user when no match exists.
5. Repeats the lookup after a rejected create to reconcile a concurrent user
   creation.

New users are created with `reset_password=true`, `admin=false`,
`can_create_group=false`, and `private_profile=true`. The Lambda does not add
users to groups, assign project roles, set a password, or create Slack users.

## Prerequisites

Before invoking the function, provide all of the following:

- A self-managed GitLab base URL that uses HTTPS and does not include
  credentials, query parameters, fragments, or an `/api/v4` suffix.
- A GitLab API token belonging to an administrator and authorized to call the
  administrator Users API. Use the `api` scope and the narrowest practical
  owner and expiry policy. See GitLab's
  [Users API](https://docs.gitlab.com/api/users/#create-a-user) and
  [personal access token scopes](https://docs.gitlab.com/user/profile/personal_access_tokens/#personal-access-token-scopes).
- Working GitLab outbound email if users are expected to receive the password
  reset email requested during creation.
- Network and DNS connectivity from AWS Lambda to the GitLab base URL.
- The two environment-specific Parameter Store entries described below.

The current CDK stack does not attach the function to a VPC. A private GitLab
endpoint therefore requires additional VPC, routing, DNS, security-group, and
possibly VPN or Direct Connect configuration before this Lambda can reach it.
Do not deploy on the assumption that Parameter Store configuration provides
network connectivity.

## Parameter Store configuration

Development expects these externally managed parameters:

| Name | Type | Value |
| --- | --- | --- |
| `/foundry/dev/gitlab/base-url` | `String` | GitLab origin, for example `https://gitlab.example.com` |
| `/foundry/dev/gitlab/api-token` | `SecureString` | GitLab administrator API token |
| `/foundry/dev/gitlab/ca-bundle` | `String` | Optional public CA certificate bundle for the GitLab server |

The user explicitly selected Parameter Store `SecureString` for the current
token design. Secrets Manager remains the preferred future location for a
genuine production credential because it provides a clearer secret lifecycle
and rotation model.

Create the token using an approved secret-entry process. Never put its value in
Git, environment YAML, CDK source, CloudFormation parameters, Lambda
environment variables, event fixtures, command history, workflow state, or
logs.

Verify metadata without printing either value:

```bash
aws ssm get-parameters \
  --names \
    /foundry/dev/gitlab/base-url \
    /foundry/dev/gitlab/api-token \
  --region us-east-1 \
  --query 'Parameters[].{Name:Name,Type:Type,Version:Version}' \
  --output table
```

The expected required types are `String` and `SecureString`; the optional CA
bundle is another `String`. If the secure parameter uses a customer-managed KMS
key, the Lambda role also needs `kms:Decrypt` for that exact key. Step 9
currently assumes the default AWS-managed SSM key.

CDK puts only these references in the Lambda environment:

```text
APP_ENV=dev
GITLAB_BASE_URL_PARAMETER_NAME=/foundry/dev/gitlab/base-url
GITLAB_API_TOKEN_PARAMETER_NAME=/foundry/dev/gitlab/api-token
GITLAB_TLS_VERIFY=false
```

When custom CA verification is activated, the environment instead includes:

```text
GITLAB_CA_BUNDLE_PARAMETER_NAME=/foundry/dev/gitlab/ca-bundle
GITLAB_TLS_VERIFY=true
```

The role receives `ssm:GetParameters` for exactly the configured parameter
ARNs. At invocation time, the runtime loader retrieves them together with
decryption enabled and validates the resulting URL, nonblank token, and
optional CA bundle. Values are loaded on every invocation so a parameter update
does not depend on warm-container cache expiry.

## TLS behavior

Development currently sets `GITLAB_TLS_VERIFY=false` to support initial testing
against a self-hosted instance whose certificate is not yet trusted. The
client emits a warning whenever verification is disabled.

Staging and production configuration require `GITLAB_TLS_VERIFY=true`; the
configuration model rejects disabling it outside development. Sending a token
over an unverified TLS connection is vulnerable to interception, so use the
development exception only in a controlled network.

Custom CA support is implemented but is not activated in the checked-in
development configuration. When configured, the client creates a default SSL
context containing the normal operating-system trust roots and adds the public
CA bundle in memory. Certificate and hostname verification remain enabled. An
invalid PEM bundle becomes a safe `ConfigurationError` without logging the
certificate contents.

### Activate a custom CA in development

Export the public root CA and any required intermediate CA certificates in PEM
format. Do not export or store the CA private key, the GitLab server private
key, or a PKCS#12 file containing private-key material. The certificate subject
alternative name presented by GitLab must match the hostname in the configured
base URL.

Create or update the public bundle as a Parameter Store `String`. The
certificate is public trust material rather than a credential, but it must
still be change-controlled:

```bash
aws ssm put-parameter \
  --name /foundry/dev/gitlab/ca-bundle \
  --description "Public CA bundle used to verify the development GitLab server" \
  --type String \
  --value file://path/to/gitlab-ca-bundle.pem \
  --overwrite \
  --region us-east-1
```

Confirm only its metadata:

```bash
aws ssm get-parameter \
  --name /foundry/dev/gitlab/ca-bundle \
  --region us-east-1 \
  --query 'Parameter.{Name:Name,Type:Type,Version:Version}' \
  --output table
```

Then change `config/dev.yaml` to:

```yaml
integrations:
  gitlab:
    base_url_parameter_name: /foundry/dev/gitlab/base-url
    api_token_parameter_name: /foundry/dev/gitlab/api-token
    ca_bundle_parameter_name: /foundry/dev/gitlab/ca-bundle
    tls_verify: true
```

Package, test, and review the CDK diff before deployment. The diff should add
the CA parameter name to the Lambda environment and its exact ARN to the
existing `ssm:GetParameters` statement. It must not contain the PEM value.

## Input contract

The schema version is `1.0`. The Lambda accepts exactly:

| Field | Type | Requirements |
| --- | --- | --- |
| `schema_version` | string | Must be `1.0` |
| `request_id` | UUID string | Correlation identifier |
| `username` | string | 2-255 characters; valid GitLab username form |
| `name` | string | 1-255 characters |
| `email` | string | Valid email address, at most 254 characters |
| `external` | boolean | Required strict JSON boolean |

Unknown fields are rejected. Credentials and passwords are not accepted.
See `events/functions/gitlab_user/valid.json` for a development fixture.

Example:

```json
{
  "schema_version": "1.0",
  "request_id": "f084a40c-2d45-4bc9-96b2-d650bb746413",
  "username": "jane.smith",
  "name": "Jane Smith",
  "email": "jane.smith@example.com",
  "external": false
}
```

## Success output

The function returns only the provider-safe user ID and username. It does not
return an email address, token, raw GitLab response, or password-reset data.

```json
{
  "schema_version": "1.0",
  "request_id": "f084a40c-2d45-4bc9-96b2-d650bb746413",
  "status": "created",
  "result": {
    "id": 123,
    "username": "jane.smith"
  }
}
```

`status` is `created` for a new identity or `existing` for a compatible active
identity.

## Failure behavior

| Exception | Meaning | Retry guidance |
| --- | --- | --- |
| `InvalidInputError` | Event violates the Lambda contract | Do not retry unchanged input |
| `ConfigurationError` | Parameter references, retrieval, or values are invalid | Repair configuration first |
| `GitLabAuthenticationError` | GitLab returned 401 or 403 | Repair token or authorization |
| `GitLabIdentityConflictError` | Existing identity does not match the request | Resolve identity data manually |
| `GitLabRequestError` | GitLab rejected creation and no concurrent user appeared | Inspect the request and GitLab policy |
| `GitLabUnavailableError` | Network error, rate limit, or GitLab 5xx response | Retry with bounded backoff |
| `GitLabProtocolError` | Unexpected status or malformed/incompatible response | Investigate compatibility before retrying |

The Step Functions integration retries only `GitLabUnavailableError` and AWS
Lambda service failures. It discards caught error payloads and must not place
raw errors, provider responses, or credentials in execution history.

## Logging and observability

The function uses structured JSON logs in
`/aws/lambda/foundry-<environment>-gitlab-user`. Successful logs contain only
the request ID, result status, and GitLab numeric user ID. Expected failure logs
contain only the request ID and safe application error code. Invalid input logs
contain a validation error count and a canonical request ID when available.

The handler never logs the full event, token, email address, name, raw GitLab
response, or exception cause containing provider data. X-Ray follows the
environment's shared observability setting.

## Package, review, and deploy

Build both Lambda artifacts and run the quality gate:

```bash
make package
make check ENV=dev
```

Authenticate to the intended development account, confirm the identity, and
review an accurate change-set diff:

```bash
export AWS_PROFILE=foundry-dev
export AWS_REGION=us-east-1
aws sso login --profile "$AWS_PROFILE"
aws sts get-caller-identity
npx cdk diff foundry-dev -c env=dev --method change-set
```

The GitLab portion of the diff should contain one Lambda, one log group, one
execution role and scoped policy, one file asset, and the
`GitLabUserFunctionName` output. The workflow role should gain permission to
invoke the GitLab Lambda, and the state-machine definition should gain the
`onboard_user` route. The diff must not include any parameter value.

Deploy only after reviewing the diff:

```bash
make deploy ENV=dev
```

## Controlled direct invocation

Direct invocation can create a real GitLab account. Use a reviewed fixture with
a unique development identity and confirm the selected AWS account and GitLab
instance before running it.

```bash
aws lambda invoke \
  --function-name foundry-dev-gitlab-user \
  --cli-binary-format raw-in-base64-out \
  --payload fileb://events/functions/gitlab_user/valid.json \
  /tmp/foundry-gitlab-user-response.json

jq . /tmp/foundry-gitlab-user-response.json
```

Invoke the same request a second time to confirm reconciliation returns
`existing` rather than creating another user. Verify the user independently in
the GitLab administrator interface. Do not use a production identity for this
development check.

## Controlled workflow invocation

After direct invocation succeeds, start the state machine with the workflow
fixture. This can create a real GitLab account and requires the same review as
direct invocation.

```bash
foundry_workflow_arn=$(aws cloudformation describe-stacks \
  --stack-name foundry-dev \
  --query "Stacks[0].Outputs[?OutputKey=='GenericWorkflowArn'].OutputValue" \
  --output text)

aws stepfunctions start-execution \
  --state-machine-arn "$foundry_workflow_arn" \
  --name onboarding-test-001 \
  --input file://events/workflows/onboarding/valid.json
```

Use a unique execution name for later runs. A successful execution returns the
same provider-safe `created` or `existing` output as the GitLab Lambda. The
workflow explicitly transforms input and never passes credentials.
