#!/usr/bin/env bash

set -euo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly REPOSITORY_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
readonly BUILD_IMAGE="public.ecr.aws/sam/build-python3.14"

case "${1:-}" in
    generic-processor)
        readonly ASSET_NAME="generic-processor"
        readonly REQUIREMENTS_FILE="generic-processor.txt"
        readonly HANDLER_IMPORT="foundry_onboarding.handlers.generic_processor.handler"
        ;;
    gitlab-user)
        readonly ASSET_NAME="gitlab-user"
        readonly REQUIREMENTS_FILE="gitlab-user.txt"
        readonly HANDLER_IMPORT="foundry_onboarding.handlers.gitlab_user.handler"
        ;;
    *)
        echo "Usage: $0 {generic-processor|gitlab-user}" >&2
        exit 2
        ;;
esac

readonly ASSET_DIRECTORY="${REPOSITORY_ROOT}/build/${ASSET_NAME}"

case "${ASSET_DIRECTORY}" in
    "${REPOSITORY_ROOT}/build/generic-processor" | "${REPOSITORY_ROOT}/build/gitlab-user") ;;
    *)
        echo "Refusing to clean unexpected asset directory: ${ASSET_DIRECTORY}" >&2
        exit 1
        ;;
esac

rm -rf -- "${ASSET_DIRECTORY}"
mkdir -p -- "${ASSET_DIRECTORY}"

docker run --rm \
    --platform linux/amd64 \
    --user "$(id -u):$(id -g)" \
    --env HOME=/tmp \
    --env "REQUIREMENTS_PATH=/asset-input/requirements/${REQUIREMENTS_FILE}" \
    --volume "${REPOSITORY_ROOT}:/asset-input:ro" \
    --volume "${ASSET_DIRECTORY}:/asset-output" \
    --entrypoint /bin/sh \
    "${BUILD_IMAGE}" \
    -ec '
        python -m pip install \
            --require-hashes \
            --only-binary=:all: \
            --no-compile \
            --target /asset-output \
            --requirement "${REQUIREMENTS_PATH}"
        cp -R /asset-input/src/foundry_onboarding /asset-output/foundry_onboarding
        find /asset-output/foundry_onboarding -type d -name __pycache__ -prune -exec rm -rf -- {} +
        find /asset-output/foundry_onboarding -type f \( -name "*.pyc" -o -name "*.pyo" \) -delete
    '

test -d "${ASSET_DIRECTORY}/foundry_onboarding"
test -d "${ASSET_DIRECTORY}/pydantic"
test -d "${ASSET_DIRECTORY}/pydantic_core"

if ! find "${ASSET_DIRECTORY}/pydantic_core" -maxdepth 1 -type f -name '*.so' -print -quit \
    | grep -q .; then
    echo "The packaged pydantic_core native extension is missing." >&2
    exit 1
fi

docker run --rm \
    --platform linux/amd64 \
    --user "$(id -u):$(id -g)" \
    --env HOME=/tmp \
    --env "HANDLER_IMPORT=${HANDLER_IMPORT}" \
    --env PYTHONDONTWRITEBYTECODE=1 \
    --env PYTHONPATH=/asset-output \
    --volume "${ASSET_DIRECTORY}:/asset-output:ro" \
    --entrypoint python \
    "${BUILD_IMAGE}" \
    -c 'import importlib, os; module, name = os.environ["HANDLER_IMPORT"].rsplit(".", 1); assert callable(getattr(importlib.import_module(module), name))'

echo "Built and verified ${ASSET_DIRECTORY}"
