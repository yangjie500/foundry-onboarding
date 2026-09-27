# Foundry Onboarding

A production-oriented AWS serverless application built with Python, AWS Lambda,
AWS Step Functions, and AWS CDK.

## Development

Run the complete local quality gate:

```bash
make check ENV=dev
```

## Workflow contract

The initial generic workflow contract is documented in
[docs/generic-workflow-contract.md](docs/generic-workflow-contract.md).

Representative workflow-start events are under `events/workflows/`. Lambda
invocation and expected-output fixtures are under `events/functions/`.
