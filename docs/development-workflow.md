# Development and packaging workflow

This document describes how to install the project, change application code or
dependencies, build the Lambda artifact, and validate the result locally.

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

Build the Lambda deployment artifact and run the complete local quality gate:

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
| `dev` | Local quality and test tools | pytest, Ruff, mypy |

The groups are declared in `pyproject.toml`. A normal `uv sync --locked`
installs all three groups for local development.

### Adding or changing a Lambda dependency

Add the dependency to the `lambda-generic` group in `pyproject.toml`. If the
infrastructure code imports the same dependency, add it to `infra` as well.
Then update and validate the generated files:

```bash
uv lock
make package
make check ENV=dev
```

Commit `pyproject.toml`, `uv.lock`, and
`requirements/generic-processor.txt` together. Do not edit the requirements
file by hand; `make package` regenerates it from the lockfile.

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

After changing files under `src/foundry_onboarding`, rebuild the artifact before
synthesis, diff, or deployment:

```bash
make package
make check ENV=dev
```

The package step copies the current source, so an existing artifact does not
update automatically when source files change.

## How packaging works

`make requirements` exports only the `lambda-generic` dependency group from
`uv.lock` to `requirements/generic-processor.txt`. The export contains exact
versions and package hashes.

`make package` first refreshes that requirements file and then runs
`scripts/build-lambda-asset.sh`. The script:

1. Recreates only `build/generic-processor`.
2. Runs `public.ecr.aws/sam/build-python3.14` for `linux/amd64`.
3. Installs hashed dependencies using binary wheels only.
4. Copies `src/foundry_onboarding` into the artifact.
5. Removes Python cache files from the copied source.
6. Confirms that the source, Pydantic, and the native `pydantic-core` extension
   are present.
7. Imports `foundry_onboarding.handlers.generic_processor.handler` inside the
   Python 3.14 container.

The resulting directory is the root of the Lambda zip asset:

```text
build/generic-processor/
├── foundry_onboarding/
├── pydantic/
├── pydantic_core/
└── other Pydantic runtime dependencies
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
not need Docker or a pre-existing package. Normal application synthesis uses
`build/generic-processor`, so package before running the complete quality gate.

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

For this project, `make package` creates `build/generic-processor` locally. CDK
then packages that directory and uploads it to the bootstrap S3 bucket before
CloudFormation creates or updates the Lambda function.

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

## Make targets

| Command | Action |
| --- | --- |
| `make install` | Install locked Node.js and Python development dependencies |
| `make requirements` | Export hashed Lambda requirements from `uv.lock` |
| `make package` | Export requirements, build the artifact, and verify its imports |
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

- If synthesis reports that `build/generic-processor` does not exist, run
  `make package`.
- If Docker cannot connect to its daemon, start Docker and verify that the
  current user can access it.
- If packaging cannot find a compatible wheel, confirm the dependency publishes
  a Python 3.14 `linux/amd64` wheel. Packaging intentionally does not compile a
  source distribution.
- If `uv` reports that the lockfile is stale, run `uv lock`, review the changes,
  and run `make package` again.
