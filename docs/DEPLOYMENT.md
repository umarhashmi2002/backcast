# Deployment

## Local (no cloud, no AWS credentials)
```bash
make bootstrap        # uv venv + dev deps
make db-up            # local CockroachDB (docker) + migration
uv run backcast demo   # offline embeddings; proves every mechanism
make test             # unit tests
make test-integration # live-DB integration tests
```

## Cloud: CockroachDB Cloud

1. Create a free cluster at <https://cockroachlabs.cloud> (no credit card required), or provision one
   with the ccloud CLI:
   ```bash
   ./scripts/bootstrap_cockroach.sh          # creates cluster + service account + `backcast` DB
   ```
2. Export the connection string and apply the schema:
   ```bash
   export BACKCAST_DATABASE_URL="postgresql://<user>:<pass>@<host>:26257/backcast?sslmode=verify-full"
   uv run python -m backcast.db.migrate
   ```
3. **Managed MCP server (optional, for agent introspection):** in the Cloud Console, select the
   cluster → copy the MCP config snippet → paste into Claude Code / Cursor. It is read-only by default.

## Cloud: AWS

Prerequisites:
- AWS CLI authenticated and **Docker running** (the Lambdas ship as container images).
- A recent CDK CLI: `npm i -g aws-cdk@latest` (>= 2.1134).
- **Bedrock model access enabled** in `us-east-1` for Anthropic Claude and Amazon Titan Text
  Embeddings v2 — enable once in the Bedrock console under *Model access*.

```bash
# 1. Deploy. CDK creates the S3 bucket, the Secrets Manager secret (placeholder value),
#    three container Lambdas, the EventBridge schedule, alarms, and a dashboard.
cd infra
uv sync
uv run cdk bootstrap        # first time per account/region only
uv run cdk deploy           # prints IngestUrl / CommanderUrl / DatabaseSecretName

# 2. Put the real CockroachDB DSN into the secret CDK created:
aws secretsmanager put-secret-value --secret-id backcast/database-url \
  --secret-string "{\"url\":\"$BACKCAST_DATABASE_URL\"}"

# 3. Smoke test (use the IngestUrl from the deploy output):
curl -sX POST "$INGEST_URL" -d '{"org_id":"demo","fingerprint":"am-1","service":"payments-api"}'
```

HTTP entry points are **Lambda Function URLs** (`IngestUrl`, `CommanderUrl`). Each Lambda gets
least-privilege IAM (scoped Bedrock model ARNs, the one bucket, the one secret). Everything is
serverless/pay-per-use — Bedrock per-token, Lambda per-invoke, S3 per-GB — keeping a demo
comfortably inside AWS free-tier credits.

## Configuration
All settings are environment variables (see [`.env.example`](../.env.example)); prefix `BACKCAST_`
except `AWS_REGION`. Key ones: `BACKCAST_DATABASE_URL`, `BACKCAST_BEDROCK_MODEL_ID`,
`BACKCAST_EMBEDDING_MODEL_ID` (`hash` for offline), `BACKCAST_ARTIFACT_BUCKET`.

## Teardown
```bash
cd infra && uv run cdk destroy --all      # AWS
ccloud cluster delete backcast-hackathon   # CockroachDB (if provisioned via ccloud)
make db-down                              # local
```
