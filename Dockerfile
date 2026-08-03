# Container image for the Backcast Lambda functions.
# One image, three functions — the handler is selected per-function via CMD (set by CDK).
FROM public.ecr.aws/lambda/python:3.13

WORKDIR ${LAMBDA_TASK_ROOT}

# Install the backcast package and its runtime dependencies into the image.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[web]"

# Bundle the OpenAPI spec so the webapp can serve GET /openapi.yaml at runtime.
COPY docs/openapi.yaml ./docs/openapi.yaml

# Default handler; CDK overrides this per function (ingest / commander / consolidate).
CMD ["backcast.api.ingest.handler"]
