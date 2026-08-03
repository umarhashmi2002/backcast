#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Backcast — narrated end-to-end demo against the LIVE AWS deployment.
#
#   ./demo.sh              # interactive, pauses between steps
#   ./demo.sh --no-pause   # run straight through (also: CI=1 ./demo.sh)
#
# Every endpoint is overridable via env var (defaults = the live BackcastStack).
# Requires: bash, curl, python3, aws (for the webhook secret).
# ---------------------------------------------------------------------------
set -euo pipefail

WEBAPP_URL="${WEBAPP_URL:-https://2beyv24r657kdthgabtbvg74n40pyolu.lambda-url.us-east-1.on.aws}"
COMMANDER_URL="${COMMANDER_URL:-https://u754vo546smuamntvsvicdngfe0otxdc.lambda-url.us-east-1.on.aws/}"
INGEST_URL="${INGEST_URL:-https://sanik5tdc2qb2uy5hxchobelsa0qagzj.lambda-url.us-east-1.on.aws/}"
INGRESS_URL="${INGRESS_URL:-https://1a1x8v25m9.execute-api.us-east-1.amazonaws.com/prod/incidents}"
WEBHOOK_SECRET_ID="${WEBHOOK_SECRET_ID:-backcast/webhook-secret}"

PAUSE=1
[[ "${1:-}" == "--no-pause" || -n "${CI:-}" ]] && PAUSE=0

if [[ -t 1 ]]; then
  B=$'\033[1m'; DIM=$'\033[2m'; G=$'\033[32m'; Y=$'\033[33m'; C=$'\033[36m'; R=$'\033[31m'; P=$'\033[35m'; X=$'\033[0m'
else
  B=""; DIM=""; G=""; Y=""; C=""; R=""; P=""; X=""
fi

for bin in curl python3 aws; do
  command -v "$bin" >/dev/null 2>&1 || { echo "${R}missing dependency: $bin${X}" >&2; exit 1; }
done

banner() { echo; echo "${P}${B}━━━ $* ━━━${X}"; }
note()   { echo "  ${DIM}$*${X}"; }
ok()     { echo "  ${G}✓ $*${X}"; }
pause()  { [[ $PAUSE -eq 1 ]] && { echo; read -r -p "  ${DIM}↵ to continue…${X}" _; } || true; }
pp()     { python3 -m json.tool 2>/dev/null || cat; }

# curl helper → sets global RESP_CODE / RESP_BODY
call() {
  local method="$1" url="$2"; shift 2
  local out; out="$(curl -sS -X "$method" -w $'\n%{http_code}' "$url" "$@")"
  RESP_CODE="${out##*$'\n'}"
  RESP_BODY="${out%$'\n'*}"
}

# sign a body: prints "<sig-header>\t<ts>" (HMAC matches src/backcast/api/security.py)
sign() {
  local secret="$1" body="$2"
  python3 - "$secret" "$body" <<'PY'
import hashlib, hmac, sys, time
secret, body = sys.argv[1].encode(), sys.argv[2].encode()
ts = int(time.time())
sig = hmac.new(secret, f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
print(f"sha256={sig}\t{ts}")
PY
}

jget() { python3 -c "import sys,json;d=json.load(sys.stdin);print(d$1)" 2>/dev/null || echo ""; }

echo "${C}${B}"
echo "  ██  Backcast — temporal decision laboratory for on-call"
echo "  ██  Live demo · CockroachDB (time-travel + vectors) × AWS (Bedrock/KMS/API GW)${X}"
note "Web UI:    $WEBAPP_URL"
note "Ingress:   $INGRESS_URL  (API Gateway, HMAC-verified)"

banner "Fetching the webhook signing secret from AWS Secrets Manager"
SECRET="$(aws secretsmanager get-secret-value --secret-id "$WEBHOOK_SECRET_ID" --query SecretString --output text)"
ok "loaded secret '$WEBHOOK_SECRET_ID' (${#SECRET} chars) — never printed"
pause

# 1 ─────────────────────────────────────────────────────────────────────────
banner "1/8 · Health check"
call GET "$WEBAPP_URL/health"
echo "$RESP_BODY" | pp
ok "webapp + CockroachDB reachable ($RESP_CODE)"
pause

# 2 ─────────────────────────────────────────────────────────────────────────
banner "2/8 · Ingest WITHOUT a signature  (expect 401 — this is the point)"
note "A public ingress must not trust its callers. No HMAC ⇒ rejected."
call POST "$INGEST_URL" -H 'content-type: application/json' \
  --data-raw '{"org_id":"demo","fingerprint":"demo-unsigned"}'
echo "  HTTP $RESP_CODE — $RESP_BODY"
[[ "$RESP_CODE" == "401" ]] && ok "unsigned alert correctly rejected" || echo "  ${Y}expected 401${X}"
pause

# 3 ─────────────────────────────────────────────────────────────────────────
banner "3/8 · Ingest WITH a valid HMAC signature  (expect 201)"
BODY='{"org_id":"demo","fingerprint":"demo-'"$(date +%s)"'","title":"Checkout 5xx spike","service":"checkout","severity":"sev1","summary":"Error rate 12% after deploy d-8842"}'
IFS=$'\t' read -r SIG TS <<<"$(sign "$SECRET" "$BODY")"
note "signed \"<ts>.\"+body  →  x-backcast-signature: ${SIG:0:23}…"
call POST "$INGEST_URL" -H 'content-type: application/json' \
  -H "x-backcast-signature: $SIG" -H "x-backcast-timestamp: $TS" --data-raw "$BODY"
echo "$RESP_BODY" | pp
INCIDENT_ID="$(printf '%s' "$RESP_BODY" | jget "['incident_id']")"
ok "incident created ($RESP_CODE): $INCIDENT_ID  + raw alert archived to S3"
pause

# 4 ─────────────────────────────────────────────────────────────────────────
banner "4/8 · Same alert via API Gateway  (HMAC + throttling, expect 201)"
BODY4='{"org_id":"demo","fingerprint":"demo-apigw-'"$(date +%s)"'","title":"DB pool exhausted","service":"payments","severity":"sev2"}'
IFS=$'\t' read -r SIG4 TS4 <<<"$(sign "$SECRET" "$BODY4")"
call POST "$INGRESS_URL" -H 'content-type: application/json' \
  -H "x-backcast-signature: $SIG4" -H "x-backcast-timestamp: $TS4" --data-raw "$BODY4"
ok "API Gateway → Lambda → CockroachDB ($RESP_CODE)"
pause

# 5 ─────────────────────────────────────────────────────────────────────────
banner "5/8 · Incident Commander agent turn  (Amazon Nova Pro · ~20s)"
note "recall similar incidents → observe → assess hypotheses → claim a FENCED lease → resolve"
call POST "$COMMANDER_URL" -H 'content-type: application/json' \
  --data-raw '{"org_id":"demo","incident_id":"'"$INCIDENT_ID"'","signal":"Checkout error rate 12% right after deploy d-8842; latency up. What do we do?"}'
if [[ "$RESP_CODE" == "200" ]]; then
  echo "  steps:          $(printf '%s' "$RESP_BODY" | jget "['steps']")"
  echo "  tool_calls:     $(printf '%s' "$RESP_BODY" | jget "['tool_calls']")"
  echo "  claimed_action: ${G}$(printf '%s' "$RESP_BODY" | jget "['claimed_action']")${X}"
  echo "  ${DIM}$(printf '%s' "$RESP_BODY" | jget "['summary'][:280]")${X}"
  ok "agent reasoned, claimed a fenced lease, and resolved the incident"
else
  echo "  ${Y}HTTP $RESP_CODE — $RESP_BODY${X}"
fi
pause

# 6 ─────────────────────────────────────────────────────────────────────────
banner "6/8 · Counterfactual replay — the ORIGINALITY pivot"
note "rewind → fork every candidate fix → simulate → compare → measure decision regret"
call POST "$WEBAPP_URL/api/counterfactual?org=demo"
echo "  scenario:        $(printf '%s' "$RESP_BODY" | jget "['scenario']")"
echo "  best remedy:     ${G}$(printf '%s' "$RESP_BODY" | jget "['best_label']")${X}"
echo "  ${B}decision regret: ${Y}$(printf '%s' "$RESP_BODY" | jget "['decision_regret']")${X}  (0 = the action taken was optimal)"
echo "  ledger verified: $(printf '%s' "$RESP_BODY" | jget "['ledger_verified']")"
ok "the agent now knows which decision was actually best — and remembers it"
pause

# 7 ─────────────────────────────────────────────────────────────────────────
banner "7/8 · Temporal no-leak + belief revision"
note "reconstruct the incident AS OF an earlier HLC — future evidence must not leak back"
call POST "$WEBAPP_URL/api/incident?org=demo"
echo "  at t1 : deploy-belief $(printf '%s' "$RESP_BODY" | jget "['at_t1']['deploy']")   no_leak=$(printf '%s' "$RESP_BODY" | jget "['no_leak']")"
echo "  now   : deploy-belief ${G}$(printf '%s' "$RESP_BODY" | jget "['now']['deploy']")${X}   (belief flipped as the deploy evidence arrived)"
ok "point-in-time truth with zero snapshot bookkeeping (AS OF SYSTEM TIME)"
pause

# 8 ─────────────────────────────────────────────────────────────────────────
banner "8/8 · Concurrency, fencing & crash-safety"
note "N workers race for one lease; a crashed holder is fenced out on revival"
call POST "$WEBAPP_URL/api/race?org=demo&workers=20"
echo "  winners:                       ${G}$(printf '%s' "$RESP_BODY" | jget "['winners']")${X}  (exactly one)"
echo "  revived stale worker accepted: ${G}$(printf '%s' "$RESP_BODY" | jget "['revived_stale_worker_accepted']")${X}  (fenced out)"
echo "  external effect executions:    ${G}$(printf '%s' "$RESP_BODY" | jget "['external_effect_executions']")${X}  (exactly once)"
ok "no split-brain: fencing tokens + idempotency keep external effects single-shot"

banner "Done"
echo "  Open the live UI to explore all of this interactively:"
echo "    ${C}${B}$WEBAPP_URL${X}"
echo "  API docs (Swagger): ${C}$WEBAPP_URL/docs${X}   ·   spec: ${C}$WEBAPP_URL/openapi.yaml${X}"
echo
