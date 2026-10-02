# Foundry Onboarding

A production-oriented AWS serverless application built with Python, AWS Lambda,
AWS Step Functions, and AWS CDK.

## Development

Install the development dependencies, export the locked Lambda requirements,
and build the deployment asset with Docker:

```bash
make install
make package
```

The package command uses the AWS SAM Python 3.14 build image for `linux/amd64`
and writes separate deployable artifacts to `build/generic-processor` and
`build/gitlab-user`. Docker must be running. The generated `build/` directory
is ignored by Git.

See the [development and packaging workflow](docs/development-workflow.md) for
dependency changes, routine development, validation, and deployment preparation.

Run the complete local quality gate:

```bash
make check ENV=dev
```

## Workflow contract

The initial generic workflow contract is documented in
[docs/generic-workflow-contract.md](docs/generic-workflow-contract.md).
The independently deployable GitLab user Lambda is documented in
[docs/gitlab-user-lambda.md](docs/gitlab-user-lambda.md). It is not connected
to the Step Functions workflow yet.

Representative workflow-start events are under `events/workflows/`. Lambda
invocation and expected-output fixtures are under `events/functions/`.
