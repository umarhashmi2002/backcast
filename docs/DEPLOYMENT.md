# Deployment

## Local (no cloud, no AWS credentials)
```bash
make bootstrap        # uv venv + dev deps
make db-up            # local CockroachDB (docker) + migration
uv run retrace demo   # offline embeddings; proves every mechanism
make test             # unit tests
make test-integration # live-DB integration tests
```

## Cloud: CockroachDB Cloud

1. Create a free cluster at <https://cockroachlabs.cloud> (no credit card required), or provision one
   with the ccloud CLI:
   ```bash
   ./scripts/bootstrap_cockroach.sh          # creates cluster + service account + `retrace` DB
   ```
2. Export the connection string and apply the schema:
   ```bash
   export RETRACE_DATABASE_URL="postgresql://<user>:<pass>@<host>:26257/retrace?sslmode=verify-full"
   uv run python -m retrace.db.migrate
   ```
3. **Managed MCP server (optional, for agent introspection):** in the Cloud Console, select the
   cluster → copy the MCP config snippet → paste into Claude Code / Cursor. It is read-only by default.

## Cloud: AWS

Prerequisites: AWS CLI authenticated, and **Bedrock model access enabled** in the target region
(`us-east-1`) for Anthropic Claude and Amazon Titan Text Embeddings v2 — enable these once in the
Bedrock console under *Model access*.

```bash
# 1. Store the CockroachDB DSN in Secrets Manager
aws secretsmanager create-secret --name retrace/database-url \
  --secret-string "$RETRACE_DATABASE_URL"

# 2. Deploy the stacks (S3, Lambda, API Gateway, EventBridge, IAM, CloudWatch)
cd infra
uv run cdk bootstrap        # first time only
uv run cdk deploy --all
```

The CDK app wires each Lambda with least-privilege IAM (specific Bedrock model ARNs, one S3 prefix,
one secret). Cost note: everything is serverless/pay-per-use — Bedrock per-token, Lambda per-invoke,
S3 per-GB — which keeps a demo comfortably inside AWS free-tier credits.

## Configuration
All settings are environment variables (see [`.env.example`](../.env.example)); prefix `RETRACE_`
except `AWS_REGION`. Key ones: `RETRACE_DATABASE_URL`, `RETRACE_BEDROCK_MODEL_ID`,
`RETRACE_EMBEDDING_MODEL_ID` (`hash` for offline), `RETRACE_ARTIFACT_BUCKET`.

## Teardown
```bash
cd infra && uv run cdk destroy --all      # AWS
ccloud cluster delete retrace-hackathon   # CockroachDB (if provisioned via ccloud)
make db-down                              # local
```
