#!/usr/bin/env bash
#
# Provision a CockroachDB Cloud cluster for Retrace using the ccloud CLI.
#
# The ccloud CLI is agent-friendly: every command supports `-o json`, so this
# script drives the control plane programmatically and parses results with jq.
#
# Prerequisites:
#   - ccloud CLI installed:  https://www.cockroachlabs.com/docs/cockroachcloud/ccloud-get-started
#   - jq installed
#   - Authenticated:         ccloud auth login   (or a service-account key)
#
# Usage:
#   ./scripts/bootstrap_cockroach.sh [cluster_name] [cloud] [region]
#
set -euo pipefail

CLUSTER_NAME="${1:-retrace-hackathon}"
CLOUD="${2:-aws}"
REGION="${3:-us-east-1}"
DB_NAME="retrace"

command -v ccloud >/dev/null || { echo "error: ccloud CLI not found" >&2; exit 1; }
command -v jq >/dev/null || { echo "error: jq not found" >&2; exit 1; }

echo "==> Ensuring authentication"
ccloud auth whoami >/dev/null 2>&1 || {
  echo "Not authenticated. Run: ccloud auth login" >&2
  exit 1
}

echo "==> Creating CockroachDB Basic cluster '${CLUSTER_NAME}' on ${CLOUD}/${REGION}"
if ccloud cluster list -o json | jq -e --arg n "$CLUSTER_NAME" '.[] | select(.name == $n)' >/dev/null; then
  echo "    Cluster already exists; skipping create."
else
  ccloud cluster create basic "$CLUSTER_NAME" --cloud "$CLOUD" --region "$REGION" -o json | jq '.'
fi

echo "==> Waiting for cluster to become ready"
for _ in $(seq 1 60); do
  STATE=$(ccloud cluster list -o json | jq -r --arg n "$CLUSTER_NAME" '.[] | select(.name == $n) | .state')
  echo "    state=${STATE:-unknown}"
  [[ "$STATE" == "CREATED" ]] && break
  sleep 5
done

CLUSTER_ID=$(ccloud cluster list -o json | jq -r --arg n "$CLUSTER_NAME" '.[] | select(.name == $n) | .id')
echo "==> Cluster id: ${CLUSTER_ID}"

echo "==> Creating database '${DB_NAME}'"
ccloud cluster sql "$CLUSTER_NAME" --sql "CREATE DATABASE IF NOT EXISTS ${DB_NAME};" 2>/dev/null \
  || echo "    (create the '${DB_NAME}' database via the SQL console if the above is unsupported by your ccloud version)"

cat <<EOF

==> Next steps
  1. Retrieve the connection string (Cloud Console → Connect, or):
       ccloud cluster sql "${CLUSTER_NAME}" --connection-url
  2. Export it and apply the schema:
       export RETRACE_DATABASE_URL="postgresql://<user>:<pass>@<host>:26257/${DB_NAME}?sslmode=verify-full"
       uv run python -m retrace.db.migrate
  3. Store it for the Lambdas:
       aws secretsmanager create-secret --name retrace/database-url --secret-string "\$RETRACE_DATABASE_URL"

  Tip: for CI/agents, create a scoped service account and use its key instead of interactive auth:
       ccloud service-account create retrace-ci --description "Retrace CI" -o json
EOF
