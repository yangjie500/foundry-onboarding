ENV ?= dev

.PHONY: install requirements package format lint typecheck test synth check diff deploy

install:
	npm ci
	uv sync --locked

requirements:
	uv export --locked --only-group lambda-generic --no-emit-project --format requirements.txt --output-file requirements/generic-processor.txt
	uv export --locked --only-group lambda-gitlab --no-emit-project --format requirements.txt --output-file requirements/gitlab-user.txt
	uv export --locked --only-group lambda-sqs-ingress --no-emit-project --format requirements.txt --output-file requirements/sqs-workflow-ingress.txt

package: requirements
	./scripts/build-lambda-asset.sh generic-processor
	./scripts/build-lambda-asset.sh gitlab-user
	./scripts/build-lambda-asset.sh sqs-workflow-ingress

format:
	uv run ruff format .
	uv run ruff check --fix .

lint:
	uv run ruff format --check .
	uv run ruff check .

typecheck:
	uv run mypy app.py infrastructure src tests

test:
	uv run pytest --cov --cov-report=term-missing

synth:
	npx cdk synth -c env=$(ENV)

check: lint typecheck test synth

diff:
	npx cdk diff -c env=$(ENV)

deploy:
	npx cdk deploy -c env=$(ENV)
