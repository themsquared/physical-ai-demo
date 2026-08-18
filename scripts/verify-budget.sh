#!/usr/bin/env bash
# verify-budget: Predictability pillar — token budget exhaustion -> clean 429.
#
# Uses agentgateway's config hot-reload: shrink the LLM token budget live,
# prove requests get a clean 429 (not a hang, not a flail), then restore.
# The same trick is the Act 1 money shot ("edit the envelope, watch it bite").
set -euo pipefail
cd "$(dirname "$0")/.."

CONFIG=gateway/config.yaml
GATEWAY=${GATEWAY:-http://localhost:4000}
METRICS=${METRICS:-http://localhost:15020/metrics}
TOKEN=$(python3 -c "import json;print(json.load(open('gateway/jwt/tokens.json'))['orchestrator'])")

restore() { git checkout -q -- "$CONFIG"; }
trap restore EXIT

echo "=== verify-budget ==="
echo "shrinking LLM token budget to 300 tokens/hour (config hot-reload)..."
sed -i '' -e 's/maxTokens: 200000/maxTokens: 300/' -e 's/tokensPerFill: 200000/tokensPerFill: 300/' "$CONFIG" 2>/dev/null \
  || sed -i -e 's/maxTokens: 200000/maxTokens: 300/' -e 's/tokensPerFill: 200000/tokensPerFill: 300/' "$CONFIG"
sleep 2

status_codes=()
for i in $(seq 1 12); do
  code=$(curl -s -o /dev/null -w "%{http_code}" -m 60 -X POST "$GATEWAY/v1/chat/completions" \
    -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d '{"model":"robot-brain","messages":[{"role":"user","content":"navigate to zone A and report your pose in detail"}]}')
  status_codes+=("$code")
  [ "$code" = "429" ] && break
done
echo "status sequence: ${status_codes[*]}"

if printf '%s\n' "${status_codes[@]}" | grep -q '^429$'; then
  echo "--- metric evidence ---"
  curl -s "$METRICS" | grep -E 'requests_total.*(429|rate)' | head -5 || true
  echo "PASS: budget exhaustion produced a clean 429"
else
  echo "FAIL: never saw a 429 (codes: ${status_codes[*]})"
  exit 1
fi
