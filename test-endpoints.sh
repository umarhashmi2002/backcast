#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Backcast — automated E2E smoke test against the LIVE AWS deployment.
#
#   ./test-endpoints.sh          # run all checks, exit non-zero on any failure
#   CI=1 ./test-endpoints.sh     # same (quiet); intended for CI / pre-submission
#
# Endpoints are overridable via env var (defaults = the live BackcastStack).
# Requires: bash, curl, python3. The two signed-request checks additionally need the
# shared webhook secret — via BACKCAST_WEBHOOK_SECRET, or an authenticated `aws` CLI.
# Without it those checks are skipped, not failed, so this still runs for a reader
# who has only cloned the repo.
# ---------------------------------------------------------------------------
set -uo pipefail

WEBAPP_URL="${WEBAPP_URL:-https://2beyv24r657kdthgabtbvg74n40pyolu.lambda-url.us-east-1.on.aws}"
COMMANDER_URL="${COMMANDER_URL:-https://u754vo546smuamntvsvicdngfe0otxdc.lambda-url.us-east-1.on.aws/}"
INGEST_URL="${INGEST_URL:-https://sanik5tdc2qb2uy5hxchobelsa0qagzj.lambda-url.us-east-1.on.aws/}"
INGRESS_URL="${INGRESS_URL:-https://1a1x8v25m9.execute-api.us-east-1.amazonaws.com/prod/incidents}"
WEBHOOK_SECRET_ID="${WEBHOOK_SECRET_ID:-backcast/webhook-secret}"

if [[ -t 1 ]]; then G=$'\033[32m'; R=$'\033[31m'; DIM=$'\033[2m'; X=$'\033[0m'; else G=""; R=""; DIM=""; X=""; fi

for bin in curl python3; do
  command -v "$bin" >/dev/null 2>&1 || { echo "${R}missing dependency: $bin${X}" >&2; exit 2; }
done

PASS=0; FAIL=0; SKIP=0
check() { # <name> <condition-result 0/1> <detail>
  if [[ "$2" == "0" ]]; then PASS=$((PASS+1)); echo "  ${G}✓${X} $1 ${DIM}$3${X}"
  else FAIL=$((FAIL+1)); echo "  ${R}✗ $1 — $3${X}"; fi
}
skip() { SKIP=$((SKIP+1)); echo "  ${DIM}– $1 — skipped: $2${X}"; }

# curl → RESP_CODE / RESP_BODY
call() {
  local method="$1" url="$2"; shift 2
  local out; out="$(curl -sS -m 150 -X "$method" -w $'\n%{http_code}' "$url" "$@" 2>/dev/null)"
  RESP_CODE="${out##*$'\n'}"; RESP_BODY="${out%$'\n'*}"
}
sign() { # <secret> <body> → "<sig>\t<ts>"
  python3 - "$1" "$2" <<'PY'
import hashlib, hmac, sys, time
secret, body = sys.argv[1].encode(), sys.argv[2].encode()
ts = int(time.time())
print(f"sha256={hmac.new(secret, f'{ts}.'.encode()+body, hashlib.sha256).hexdigest()}\t{ts}")
PY
}
has() { printf '%s' "$1" | python3 -c "import sys,json;d=json.load(sys.stdin);sys.exit(0 if ($2) else 1)" 2>/dev/null; }

echo "${DIM}Backcast E2E — live endpoints${X}"

# The HMAC checks need the shared webhook secret, which only the deployer can read.
# Everything else hits open endpoints, so a reader who clones the repo should still
# get a useful run instead of `exit 2` on line one. Set BACKCAST_WEBHOOK_SECRET to
# supply it directly without the AWS CLI.
SECRET="${BACKCAST_WEBHOOK_SECRET:-}"
if [[ -z "$SECRET" ]] && command -v aws >/dev/null 2>&1; then
  SECRET="$(aws secretsmanager get-secret-value --secret-id "$WEBHOOK_SECRET_ID" \
    --query SecretString --output text 2>/dev/null || true)"
fi
if [[ -z "$SECRET" ]]; then
  echo "  ${DIM}note: no webhook secret available — the signed-request checks will be skipped."
  echo "        set BACKCAST_WEBHOOK_SECRET, or authenticate the AWS CLI for secret" \
       "'$WEBHOOK_SECRET_ID'.${X}"
fi

# 1. health
call GET "$WEBAPP_URL/health"
check "health 200" "$([[ "$RESP_CODE" == "200" ]] && echo 0 || echo 1)" "($RESP_CODE)"

# 2. unsigned ingest → 401
call POST "$INGEST_URL" -H 'content-type: application/json' --data-raw '{"org_id":"demo","fingerprint":"e2e-unsigned"}'
check "unsigned ingest 401" "$([[ "$RESP_CODE" == "401" ]] && echo 0 || echo 1)" "($RESP_CODE)"

# 3. signed ingest → 201
INCIDENT_ID=""
if [[ -n "$SECRET" ]]; then
  BODY='{"org_id":"demo","fingerprint":"e2e-'"$(date +%s)"'","title":"E2E","service":"checkout","severity":"sev1"}'
  IFS=$'\t' read -r SIG TS <<<"$(sign "$SECRET" "$BODY")"
  call POST "$INGEST_URL" -H 'content-type: application/json' -H "x-backcast-signature: $SIG" -H "x-backcast-timestamp: $TS" --data-raw "$BODY"
  check "signed ingest 201" "$([[ "$RESP_CODE" == "201" ]] && echo 0 || echo 1)" "($RESP_CODE)"
  INCIDENT_ID="$(printf '%s' "$RESP_BODY" | python3 -c "import sys,json;print(json.load(sys.stdin).get('incident_id',''))" 2>/dev/null)"
else
  skip "signed ingest 201" "needs the webhook secret"
fi

# 4. API Gateway ingress (signed) → 201
if [[ -n "$SECRET" ]]; then
  BODY4='{"org_id":"demo","fingerprint":"e2e-apigw-'"$(date +%s)"'","title":"E2E gw","service":"payments","severity":"sev2"}'
  IFS=$'\t' read -r SIG4 TS4 <<<"$(sign "$SECRET" "$BODY4")"
  call POST "$INGRESS_URL" -H 'content-type: application/json' -H "x-backcast-signature: $SIG4" -H "x-backcast-timestamp: $TS4" --data-raw "$BODY4"
  check "api-gateway ingress 201" "$([[ "$RESP_CODE" == "201" ]] && echo 0 || echo 1)" "($RESP_CODE)"
else
  skip "api-gateway ingress 201" "needs the webhook secret"
fi

# 5. commander turn → 200 with non-empty summary
if [[ -n "$INCIDENT_ID" ]]; then
  call POST "$COMMANDER_URL" -H 'content-type: application/json' \
    --data-raw '{"org_id":"demo","incident_id":"'"$INCIDENT_ID"'","signal":"Checkout 5xx after deploy d-8842; what do we do?"}'
  ok200=$([[ "$RESP_CODE" == "200" ]] && has "$RESP_BODY" "bool(d.get('summary'))" && echo 0 || echo 1)
  check "commander 200 + summary" "$ok200" "($RESP_CODE)"
else
  skip "commander 200 + summary" "needs an incident from the signed-ingest step"
fi

# 6. counterfactual → 200 with decision_regret present
call POST "$WEBAPP_URL/api/counterfactual?org=demo"
ok6=$([[ "$RESP_CODE" == "200" ]] && has "$RESP_BODY" "'decision_regret' in d" && echo 0 || echo 1)
check "counterfactual 200 + regret" "$ok6" "($RESP_CODE)"

# 7. incident → 200 with no_leak true
call POST "$WEBAPP_URL/api/incident?org=demo"
ok7=$([[ "$RESP_CODE" == "200" ]] && has "$RESP_BODY" "d.get('no_leak') is True" && echo 0 || echo 1)
check "incident 200 + no_leak" "$ok7" "($RESP_CODE)"

# 8. race → 200 with exactly one winner
call POST "$WEBAPP_URL/api/race?org=demo&workers=20"
ok8=$([[ "$RESP_CODE" == "200" ]] && has "$RESP_BODY" "d.get('winners')==1" && echo 0 || echo 1)
check "race 200 + single winner" "$ok8" "($RESP_CODE)"

TOTAL=$((PASS+FAIL))
SUFFIX=""; [[ $SKIP -gt 0 ]] && SUFFIX=" (${SKIP} skipped — no webhook secret)"
echo
if [[ $FAIL -eq 0 ]]; then echo "${G}PASS ${PASS}/${TOTAL}${X}${SUFFIX}"; exit 0
else echo "${R}FAIL — ${PASS}/${TOTAL} passed, ${FAIL} failed${X}${SUFFIX}"; exit 1; fi
