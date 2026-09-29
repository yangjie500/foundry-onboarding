# Development and packaging workflow

This document describes how to install the project, change application code or
dependencies, build the Lambda artifact, and validate the result locally.

## Prerequisites

Install these tools before working with the repository:

- Docker with the daemon running
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
