# Development and packaging workflow

This document describes how to install the project, change application code or
dependencies, build the Lambda artifacts, and validate the result locally.

## Prerequisites

Install these tools before working with the repository:

- Docker with the daemon running
- AWS CLI v2
- `uv`
- Node.js and npm
- GNU Make

The project uses Python 3.14. `uv` installs and manages the required Python
environment from the version constraints in `pyproject.toml`.

## First-time setup

Install the locked Python and Node.js dependencies:

```bash
make install
```

Build the Lambda deployment artifacts and run the complete local quality gate:

```bash
make package
make check ENV=dev
```

`make package` automatically runs `make requirements`, so it is unnecessary to
run both commands during the normal workflow.

Before the first AWS diff or deployment from a new machine, configure and log
in to the development account as described in
[AWS SSO authentication](#aws-sso-authentication). Then confirm that the target
AWS account and Region have been prepared for CDK by following
[CDK bootstrap](#cdk-bootstrap).

Bootstrapping is normally an account-and-Region setup task rather than a
per-machine task. If the shared `CDKToolkit` stack already exists and the
current SSO identity can assume its roles, do not create another bootstrap
stack; continue with `make diff ENV=dev`.

## Dependency groups

Dependencies are separated by where they are used:

| Group | Purpose | Examples |
| --- | --- | --- |
| `infra` | CDK synthesis and infrastructure configuration | AWS CDK, Pydantic, PyYAML |
| `lambda-generic` | Code required by the generic processor in Lambda | Pydantic |
| `lambda-gitlab` | Code required by the GitLab user Lambda | Pydantic, email-validator, urllib3 |
| `dev` | Local quality and test tools | pytest, Ruff, mypy |

The groups are declared in `pyproject.toml`. A normal `uv sync --locked`
installs all four groups for local development.

### Adding or changing a Lambda dependency

Add the dependency to the group for the Lambda that imports it:
`lambda-generic` or `lambda-gitlab`. Add it to both only when both deployment
packages require it. If the infrastructure code imports the same dependency,
add it to `infra` as well. Then update and validate the generated files:

```bash
uv lock
make package
make check ENV=dev
```

Commit `pyproject.toml`, `uv.lock`, and the affected files under
`requirements/` together. Do not edit generated requirements by hand;
`make package` regenerates them from the lockfile.

### Adding an infrastructure dependency

Add it to the `infra` group, then run:

```bash
uv lock
uv sync --locked
make check ENV=dev
```

Rebuild the Lambda package only if the dependency is also used by Lambda code.

### Adding a development dependency

Add it to the `dev` group, then run:

```bash
uv lock
uv sync --locked
make check ENV=dev
```

Development dependencies are not included in the Lambda artifact.

## Changing Lambda source code

After changing files under `src/foundry_onboarding`, rebuild the artifacts
before synthesis, diff, or deployment:

```bash
make package
make check ENV=dev
```

The package step copies the current source into each Lambda artifact, so
existing artifacts do not update automatically when source files change.

## How packaging works

`make requirements` exports each Lambda dependency group from `uv.lock`:

- `lambda-generic` to `requirements/generic-processor.txt`.
- `lambda-gitlab` to `requirements/gitlab-user.txt`.

Each export contains exact versions and package hashes.

`make package` refreshes both requirements files and invokes
`scripts/build-lambda-asset.sh` once for each supported target. The guarded
script accepts only `generic-processor` or `gitlab-user`. For each target it:

1. Recreates only the selected directory under `build/`.
2. Runs `public.ecr.aws/sam/build-python3.14` for `linux/amd64`.
3. Installs hashed dependencies using binary wheels only.
4. Copies `src/foundry_onboarding` into the artifact.
5. Removes Python cache files from the copied source.
6. Confirms that the source, Pydantic, and the native `pydantic-core` extension
   are present.
7. Imports the target's configured handler inside the Python 3.14 container.

The resulting directories are the roots of the Lambda zip assets:

```text
build/
├── generic-processor/
│   ├── foundry_onboarding/
│   └── generic runtime dependencies
└── gitlab-user/
    ├── foundry_onboarding/
    └── GitLab runtime dependencies
```

`build/` is generated locally and ignored by Git. Do not commit it.

## Local validation

Run the complete quality gate after packaging:

```bash
make check ENV=dev
```

This runs, in order:

1. Ruff formatting and lint checks.
2. Strict mypy type checking.
3. The complete pytest suite with coverage.
4. CDK synthesis for the selected environment.

Infrastructure unit tests inject inline Lambda code, so the tests themselves do
not need Docker or pre-existing packages. Normal application synthesis uses
both directories under `build/`, so package before running the complete quality
gate.

Before handing changes off for review, also run:

```bash
git diff --check
git status --short
```

## AWS SSO authentication

AWS authentication is not required for local tests or synthesis, but it is
required for `make diff` and `make deploy`. This project uses a named profile so
that CDK does not accidentally use credentials from the default profile or a
different AWS account.

List the profiles already configured on the machine:

```bash
aws configure list-profiles
```

If `foundry-dev` is not listed, configure it using the values supplied by the
AWS administrator:

```bash
aws configure sso --profile foundry-dev
```

The SSO region requested by this command is the region where IAM Identity
Center is configured. It may differ from the application deployment region.
When prompted for the default AWS region, use `us-east-1` for this project.

Select the profile and application region in each new terminal session:

```bash
export AWS_PROFILE=foundry-dev
export AWS_REGION=us-east-1
```

`AWS_PROFILE` tells the AWS CLI, SDKs, and CDK which named profile to use.
Setting it is not strictly required because `--profile foundry-dev` can be
passed to individual AWS commands, but the Make targets do not pass a profile.
Exporting it therefore keeps all commands in the session on the intended
development account.

Sign in when the machine has no cached SSO session or when the existing session
has expired:

```bash
aws sso login --profile "$AWS_PROFILE"
```

Before running a diff or deployment, verify the active identity and confirm
that the returned account ID is the intended development account:

```bash
aws sts get-caller-identity
```

Then review the proposed infrastructure changes:

```bash
make diff ENV=dev
```

## CDK bootstrap

CDK bootstrapping prepares one AWS account and Region for CDK deployments. It
deploys a shared CloudFormation stack named `CDKToolkit`; it does not deploy the
`foundry-dev` application stack.

The default bootstrap stack provides resources used by CDK, including:

- An S3 bucket for file assets such as the packaged Lambda code.
- An ECR repository for projects that publish container image assets.
- A lookup role for reading AWS context during synthesis and deployment.
- File- and image-publishing roles for uploading deployment assets.
- A deployment role used by the CDK CLI.
- A CloudFormation execution role that creates the application resources.
- An SSM parameter that records the bootstrap template version.

For this project, `make package` creates `build/generic-processor` and
`build/gitlab-user` locally. CDK packages both directories and uploads them to
the bootstrap S3 bucket before CloudFormation creates or updates the Lambda
functions.

Bootstrap status is specific to an account and Region. Check the development
environment with:

```bash
aws cloudformation describe-stacks \
  --stack-name CDKToolkit \
  --region us-east-1 \
  --query 'Stacks[0].StackStatus' \
  --output text
```

`CREATE_COMPLETE` or `UPDATE_COMPLETE` means the bootstrap stack exists. If
CloudFormation reports that `CDKToolkit` does not exist, an authorized
administrator can bootstrap the currently selected account:

```bash
development_account_id=$(aws sts get-caller-identity --query Account --output text)
npx cdk bootstrap "aws://${development_account_id}/us-east-1"
```

Bootstrapping creates shared IAM roles, an S3 bucket, an ECR repository, and
other account-level deployment resources. Confirm the account ID and coordinate
with the AWS administrator before running it. The operation normally needs to
be performed once per account and Region, although it may be rerun later to
update the bootstrap template.

### Bootstrap lifecycle and cleanup

Do not delete `CDKToolkit` when development work is finished. The bootstrap
stack is shared deployment infrastructure and may be used by other CDK
applications, developers, or deployment pipelines in the same account and
Region. Deleting it removes the resources that support CDK deployments and can
break those workflows.

Use the following distinction when cleaning up:

| Situation | Action |
| --- | --- |
| Finished coding or deploying for the day | Keep `CDKToolkit` |
| Permanently removing only this application | Destroy `foundry-dev`; keep `CDKToolkit` |
| Decommissioning the entire account and Region | An administrator may remove `CDKToolkit` last |

Destroying the application stack is a destructive operation. Run it only when
the `foundry-dev` resources are intentionally being permanently removed:

```bash
npx cdk destroy foundry-dev -c env=dev
```

Only consider removing `CDKToolkit` after every dependent CDK application and
pipeline has been removed, no other team uses it, and the AWS administrator has
approved the deletion. Removing the bootstrap stack does not substitute for
destroying the application stack.

AWS recommends termination protection for the bootstrap stack. An authorized
administrator can enable it on a new or existing bootstrap stack with:

```bash
development_account_id=$(aws sts get-caller-identity --query Account --output text)
npx cdk bootstrap \
  "aws://${development_account_id}/us-east-1" \
  --termination-protection
```

This command updates the shared bootstrap stack. Confirm the selected account
and coordinate with its administrator before running it.

If CDK reports that the current credentials cannot assume a bootstrap lookup or
deployment role, first confirm that `CDKToolkit` exists. Re-running bootstrap
can repair a missing or outdated stack, but it does not grant the current SSO
identity permission to call `sts:AssumeRole`. An AWS administrator may also
need to update the SSO permission set or the bootstrap role trust policy.

Do not proceed to application deployment until CDK can use the required
bootstrap roles. To require an accurate CloudFormation change-set diff instead
of allowing CDK to fall back to a template-only comparison, run:

```bash
npx cdk diff -c env=dev --method change-set
```

## Generic processor Parameter Store configuration

The generic processor demonstrates runtime configuration with two Systems
Manager Parameter Store values:

| Parameter | Type | Ownership |
| --- | --- | --- |
| `/foundry/dev/generic/example-variable` | `String` | Created and managed by the application CDK stack |
| `/foundry/dev/generic/example-secret` | `SecureString` | Created outside CloudFormation and retained independently |

The ordinary parameter value is defined in `config/dev.yaml`. The secure value
must never be added to the environment YAML, CDK source, Lambda environment,
events, logs, or Git. AWS CloudFormation does not support creating Parameter
Store `SecureString` parameters directly.

Before the first development deployment, create the fake secure parameter in
the authenticated development account. The literal below is intentionally not
a real secret:

```bash
export AWS_PROFILE=foundry-dev
export AWS_REGION=us-east-1
aws sso login --profile "$AWS_PROFILE"
aws sts get-caller-identity

aws ssm put-parameter \
  --name "/foundry/dev/generic/example-secret" \
  --description "Non-production fake secret for generic processor testing" \
  --type "SecureString" \
  --value "not-a-real-secret" \
  --region us-east-1
```

Do not place a genuine secret directly in a shell command because the value may
remain in shell history. Use an approved secret-entry process for real
credentials, and prefer Secrets Manager for production API tokens.

Verify the parameter metadata without decrypting or printing its value:

```bash
aws ssm get-parameter \
  --name "/foundry/dev/generic/example-secret" \
  --region us-east-1 \
  --query 'Parameter.{Name:Name,Type:Type,Version:Version}' \
  --output table
```

CDK adds only the parameter names to the Lambda environment:

```text
GENERIC_VARIABLE_PARAMETER_NAME=/foundry/dev/generic/example-variable
GENERIC_SECRET_PARAMETER_NAME=/foundry/dev/generic/example-secret
```

The Lambda role receives `ssm:GetParameters` for exactly those two parameter
ARNs. The generic runtime configuration loader uses the reusable
`adapters/aws/parameter_store.py` adapter to retrieve both values in one request
with decryption enabled. It caches the composed result for the lifetime of the
warm Lambda execution environment. Updating a parameter therefore may not
affect an already warm execution environment immediately.

The reusable `adapters/aws/secrets_manager.py` adapter is also available for
future provider integrations. It validates JSON secret documents and handles
AWS failures without exposing values, but the current generic Lambda neither
calls Secrets Manager nor receives permission to access it.

The generic response returns the ordinary example value and
`example_secret_loaded: true` to demonstrate successful access. It never
returns or logs the secure value. The fake secure parameter is managed outside
the application stack and remains after `foundry-dev` is destroyed; clean it up
separately only when it is no longer needed.

After changing parameter names, ordinary values, dependencies, or retrieval
code, rebuild and validate before reviewing the deployment diff:

```bash
make package
make check ENV=dev
npx cdk diff foundry-dev -c env=dev --method change-set
```

The generic-processor portion of the diff should contain one
`AWS::SSM::Parameter`, two Lambda environment variables containing names rather
than values, and a scoped `ssm:GetParameters` policy. It must not contain
`not-a-real-secret` or any real secret value.

## GitLab user Lambda configuration

The GitLab user Lambda reads its base URL and API token from two externally
managed Parameter Store entries. Its contract,
required GitLab authorization, exact parameter names, network and TLS
prerequisites, failure behavior, safe logging rules, and controlled invocation
procedure are documented in the
[GitLab user Lambda guide](gitlab-user-lambda.md).

The generic Step Functions workflow invokes this function for the
`onboard_user` action using an explicit input transformation. The workflow role
can invoke the function but cannot read its Parameter Store configuration.

## Deploy the development stack

Deployment creates and updates real AWS resources. Do not deploy while CDK
reports that it cannot assume the bootstrap lookup or deployment roles.

First, select the development profile, sign in, and verify that the active
identity belongs to the intended account:

```bash
export AWS_PROFILE=foundry-dev
export AWS_REGION=us-east-1
aws sso login --profile "$AWS_PROFILE"
aws sts get-caller-identity
```

Require an accurate CloudFormation change-set diff before deployment:

```bash
npx cdk diff foundry-dev \
  -c env=dev \
  --method change-set
```

This command must complete without bootstrap-role warnings. Review every
proposed resource and IAM change. If role assumption still fails, stop and
resolve the SSO permission or bootstrap trust configuration with the AWS
administrator.

Rebuild and validate the exact application code that will be deployed:

```bash
make package
make check ENV=dev
git status --short
```

All checks must pass, and any tracked working-tree changes must be intentional.
Deploy using the project Make target:

```bash
make deploy ENV=dev
```

The project currently contains one stack, `foundry-dev`. The equivalent
explicit command, with complete CloudFormation event output, is:

```bash
npx cdk deploy foundry-dev \
  -c env=dev \
  --require-approval broadening \
  --progress events
```

The first deployment prompts for approval because it creates IAM roles and
policies. Approve only if the security changes match the reviewed diff. Keep
the default rollback behavior; do not add `--no-rollback` to the initial
deployment.

During deployment, CDK uploads both Lambda assets to the bootstrap S3 bucket
and uses CloudFormation to create the Lambda functions, Step Functions state
machine, log groups, IAM roles and policies, tracing configuration, and stack
outputs.

After deployment, confirm that CloudFormation completed successfully:

```bash
aws cloudformation describe-stacks \
  --stack-name foundry-dev \
  --region us-east-1 \
  --query 'Stacks[0].StackStatus' \
  --output text
```

The expected status for a first successful deployment is `CREATE_COMPLETE`.
Display the Lambda names and workflow ARN exported by the stack:

```bash
aws cloudformation describe-stacks \
  --stack-name foundry-dev \
  --region us-east-1 \
  --query 'Stacks[0].Outputs' \
  --output table
```

Verify the deployed Lambda configuration:

```bash
aws lambda get-function-configuration \
  --function-name foundry-dev-generic-processor \
  --region us-east-1 \
  --query '{State:State,Runtime:Runtime,Architecture:Architectures[0],Memory:MemorySize,Timeout:Timeout,Tracing:TracingConfig.Mode}' \
  --output table
```

Expected values are an `Active` function using `python3.14`, `x86_64`, 256 MB
of memory, a 30-second timeout, and `Active` X-Ray tracing.

Run the same configuration check for the standalone GitLab function:

```bash
aws lambda get-function-configuration \
  --function-name foundry-dev-gitlab-user \
  --region us-east-1 \
  --query '{State:State,Runtime:Runtime,Architecture:Architectures[0],Memory:MemorySize,Timeout:Timeout,Tracing:TracingConfig.Mode}' \
  --output table
```

If deployment fails, do not immediately destroy or re-bootstrap the
environment. Inspect the first `CREATE_FAILED` event and its reason:

```bash
aws cloudformation describe-stack-events \
  --stack-name foundry-dev \
  --region us-east-1 \
  --max-items 20
```

Default CDK deployment uses CloudFormation rollback, so AWS normally removes
partial changes after a failure. Diagnose the failure before taking any
destructive action.

Development deployment is complete when the change-set diff and local checks
pass, `foundry-dev` reaches `CREATE_COMPLETE`, the Lambda reports `Active`, and
the `GenericWorkflowArn` and `GitLabUserFunctionName` outputs are available.
Executing the workflow or directly invoking the GitLab function is a separate
validation step.

## Make targets

| Command | Action |
| --- | --- |
| `make install` | Install locked Node.js and Python development dependencies |
| `make requirements` | Export hashed Lambda requirements from `uv.lock` |
| `make package` | Export requirements, build both Lambda artifacts, and verify their imports |
| `make format` | Apply Ruff formatting and safe lint fixes |
| `make lint` | Check formatting and lint rules |
| `make typecheck` | Run strict mypy checks |
| `make test` | Run pytest with coverage |
| `make synth ENV=dev` | Synthesize the selected CDK environment |
| `make check ENV=dev` | Run lint, type checking, tests, and synthesis |
| `make diff ENV=dev` | Compare the synthesized stack with AWS |
| `make deploy ENV=dev` | Deploy the selected environment to AWS |

`make diff` and `make deploy` require valid AWS authentication, the correct AWS
account and region, and a bootstrapped CDK environment. Review the account,
region, and generated diff before deployment. Deployment is a separate,
explicit action and is not part of `make check` or `make package`.

## Common failures

- If synthesis reports that `build/generic-processor` or `build/gitlab-user`
  does not exist, run `make package`.
- If Docker cannot connect to its daemon, start Docker and verify that the
  current user can access it.
- If packaging cannot find a compatible wheel, confirm the dependency publishes
  a Python 3.14 `linux/amd64` wheel. Packaging intentionally does not compile a
  source distribution.
- If `uv` reports that the lockfile is stale, run `uv lock`, review the changes,
  and run `make package` again.
