# Planned GitLab and Slack integration architecture

## Status and purpose

This document records the intended Phase 2 integration direction so that
future work does not infer provider-specific requirements from the temporary
generic workflow.

The standalone GitLab user Lambda is implemented through CDK definition. It
has typed contracts and runtime configuration, a GitLab API adapter,
reconciliation service, Lambda handler, separate deployment package, scoped
Parameter Store permissions, optional custom CA support, and tests. Custom CA
support is not activated in the current development configuration. The Lambda
is connected to Step Functions through the `onboard_user` route, but it has not
been connected to SQS, deployed, or validated end to end. Slack remains planned
and unimplemented.

The SQS workflow-ingress application code is implemented with a dedicated
external contract, runtime state-machine reference, Step Functions adapter,
ingestion service, partial-batch Lambda handler, safe logging, fixtures, and
unit tests. Its isolated dependency group, hashed requirements export, and
guarded Lambda asset build target are defined and the Docker package build has
been completed. CDK now defines an encrypted, TLS-only Standard SQS simulation
queue and dead-letter queue in development only. The development ingress Lambda
is defined in CDK and connected with partial batch failure reporting. Its role
can consume only the development input queue and start only the onboarding state
machine; it cannot access the DLQ, provider configuration, or provider
credentials. The resources have not yet been deployed or validated end to end.
Staging and production do not provision an SQS queue, ingress Lambda, or event
source from this project.

The current generic processor and its example Parameter Store values should
remain available through deployment validation. Its runtime loader already
uses the shared AWS adapter foundation described below. Remove the generic
example only when the provider-specific Lambda functions and contracts are
ready.

## Implemented shared foundation

The provider-neutral runtime configuration foundation is implemented:

```text
src/foundry_onboarding/
├── adapters/aws/
│   ├── parameter_store.py
│   └── secrets_manager.py
└── runtime_configuration/
    ├── environment.py
    └── generic_processor.py
```

`ParameterStore` accepts arbitrary parameter names, retrieves them in a batch,
supports optional decryption, validates missing values, and translates AWS SDK
errors into safe application errors. `SecretStore` accepts any secret name,
retrieves a Secrets Manager value, requires a JSON object, and translates AWS
SDK and decoding failures without exposing the secret.

The shared environment reader validates reference environment variables. The
generic processor loader is a thin consumer that composes these reusable
pieces and caches its typed configuration for a warm Lambda execution
environment.

GitLab reuses this shared adapter through its typed loader. Slack should follow
the same pattern rather than duplicate boto3 retrieval code. Secrets Manager
support is implemented and tested but is not granted to or called by the
current generic or GitLab Lambda.

## Current workflow direction

The intended onboarding sequence is:

1. Receive onboarding information, eventually from Amazon SQS.
2. Validate the public workflow input.
3. Transform it into the GitLab Lambda contract.
4. Create or reconcile the GitLab user.
5. Transform the result into the Slack Lambda contract.
6. Create or reconcile the Slack user.
7. Return a correlation-safe onboarding result.

A proposed version 1 SQS onboarding message is defined in
`docs/sqs-onboarding-contract.md` and validated by the dedicated
`SqsOnboardingMessage` contract. It intentionally supports only the current
`onboard_user` fields and must still be approved by the external queue-owning
team. Queue settings, ownership boundaries, and provider requirements remain
open. Do not add guessed provider fields to shared contracts.

## Resource ownership

Use a separate Lambda function for each provider:

```text
Step Functions
├── GitLab Lambda
│   ├── GitLab base URL from Parameter Store String
│   ├── GitLab API token from Parameter Store SecureString (current choice)
│   └── Optional public CA bundle from Parameter Store String
└── Slack Lambda
    ├── Slack non-secret configuration from Parameter Store
    └── Slack credentials from Secrets Manager
```

Step Functions passes business data such as names, email addresses, request
IDs, and provider-safe results. It must never pass provider credentials.

## Environment configuration model

Replace the temporary flat generic parameter settings with settings grouped by
integration. Configuration contains only parameter and secret names, never
their values.

```python
class GitLabSettings(SettingsModel):
    base_url_parameter_name: str
    api_token_parameter_name: str
    ca_bundle_parameter_name: str | None
    tls_verify: bool


class SlackSettings(SettingsModel):
    default_channel_parameter_name: str
    credentials_secret_name: str


class IntegrationSettings(SettingsModel):
    gitlab: GitLabSettings
    slack: SlackSettings


class EnvironmentConfig(SettingsModel):
    environment: EnvironmentName
    aws_region: str
    lambda_function: LambdaSettings
    workflow: WorkflowSettings
    observability: ObservabilitySettings
    ingestion: IngestionSettings
    integrations: IntegrationSettings
```

Keep the existing validation conventions: reject unknown fields, require valid
hierarchical names, and keep loaded configuration immutable.

The current GitLab development configuration and eventual Slack configuration
resemble:

```yaml
integrations:
  gitlab:
    base_url_parameter_name: /foundry/dev/gitlab/base-url
    api_token_parameter_name: /foundry/dev/gitlab/api-token
    tls_verify: false

  slack:
    default_channel_parameter_name: /foundry/dev/slack/default-channel
    credentials_secret_name: foundry/dev/slack/credentials
```

Staging and production must use environment-specific names under their own
paths. Actual credential values must not appear in these files.

## Parameter Store

Use Parameter Store `String` parameters for non-secret runtime configuration,
for example:

```text
/foundry/dev/gitlab/base-url
/foundry/dev/slack/default-channel
```

CDK may create and manage these non-secret parameters. Prefer exact parameter
names and exact IAM resource ARNs over broad path access.

By explicit project choice, the current GitLab API token is stored in
`/foundry/<environment>/gitlab/api-token` as a `SecureString`. It is created and
managed outside the application stack. This is the implemented exception to
the preferred Secrets Manager design below.

## Secrets Manager

Prefer separate Secrets Manager secrets for genuine provider credentials in
the eventual production design:

```text
foundry/dev/gitlab/credentials
foundry/dev/slack/credentials
```

A possible GitLab secret document is:

```json
{
  "api_token": "..."
}
```

A possible Slack secret document is:

```json
{
  "bot_token": "...",
  "signing_secret": "..."
}
```

Group secret fields only when they are consumed by the same Lambda and share
the same access and rotation lifecycle. Use separate secrets when credentials
rotate independently, require different access, or serve different functions.

Create genuine secret values through an approved secret-entry process. Do not
put them in CDK source, CloudFormation parameters, shell history, fixtures, or
documentation examples.

## Lambda environment variables

Lambda environment variables contain references only. The implemented GitLab
function receives:

```text
APP_ENV=dev
GITLAB_BASE_URL_PARAMETER_NAME=/foundry/dev/gitlab/base-url
GITLAB_API_TOKEN_PARAMETER_NAME=/foundry/dev/gitlab/api-token
GITLAB_TLS_VERIFY=false
```

The planned Slack function would receive:

```text
APP_ENV=dev
SLACK_DEFAULT_CHANNEL_PARAMETER_NAME=/foundry/dev/slack/default-channel
SLACK_CREDENTIALS_SECRET_NAME=foundry/dev/slack/credentials
```

Never resolve a secret into a Lambda environment variable during synthesis or
deployment. Retrieve it at runtime.

## Runtime configuration objects

Keep provider configuration separate in application code:

```python
class GitLabConfiguration(BaseModel):
    base_url: HttpUrl
    api_token: SecretStr
    ca_bundle_pem: str | None
    tls_verify: StrictBool


@dataclass(frozen=True, slots=True)
class SlackConfiguration:
    default_channel: str
    bot_token: str
    signing_secret: str
```

Provider services should receive only their own dependencies. Keep AWS SDK
calls in adapters rather than handlers, services, or contract models. The
current GitLab loader retrieves its two values on each invocation; introduce
caching only with a documented refresh policy. Never log or return secret
values.

## IAM boundaries

The GitLab Lambda may read only its two GitLab parameters. The Slack Lambda may
eventually read only its Slack parameter and Slack secret.

Expected actions are narrowly scoped forms of:

```text
ssm:GetParameter or ssm:GetParameters
secretsmanager:GetSecretValue
```

The implemented GitLab role has `ssm:GetParameters` for the exact base URL and
API token parameter ARNs. It has no Secrets Manager permission.

Do not use `ssm:*`, `secretsmanager:*`, or `Resource: *` for provider
configuration. If customer-managed KMS keys are introduced, add only the
corresponding key-specific decrypt permission.

## Contracts and workflow transformations

Each provider Lambda owns its input, output, and result models. Shared contract
models should contain only truly shared workflow identity fields such as schema
version and request ID.

The state machine should explicitly transform data between states. Provider
responses must not be forwarded wholesale, and secrets must never enter state
input, output, execution history, or logs.

Define idempotency and partial-failure behavior before implementation. Creating
a GitLab user and then failing to create a Slack user must have an intentional
retry, reconciliation, or compensation policy.

## Open requirements

Resolve these before completing the end-to-end onboarding workflow:

- External-team approval of the proposed SQS message schema, validation rules,
  and immutable request-ID requirement.
- Required GitLab group and project-role assignment after account creation.
- Required Slack provisioning API, account capabilities, and user fields.
- Existing-user and duplicate-request behavior for Slack and the overall
  workflow. GitLab account reconciliation is implemented.
- Idempotency keys and retry-safe provider operations.
- Partial-success and compensation policy.
- Credential ownership and rotation process.
- Whether default channels or groups are global or request-specific.

## Suggested implementation sequence

1. Create the development CA bundle parameter and activate trusted TLS.
2. Confirm network and DNS connectivity from Lambda to the GitLab instance.
3. Package, synthesize, and review an accurate GitLab Lambda change-set diff.
4. Deploy the standalone GitLab function to development and run a controlled
   create-and-reconcile test.
5. Finalize public SQS and onboarding contracts.
6. Implement the separate Slack Lambda with its own configuration and
   least-privilege IAM.
7. Extend the existing explicit Step Functions transformation, retries, and
   failure paths with the Slack task.
8. Define idempotency and partial-success behavior across GitLab and Slack.
9. Add end-to-end contract, infrastructure, and security assertions.
10. Deploy the complete development workflow and run controlled fixtures.
