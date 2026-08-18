#!/usr/bin/env bash
# verify-budget: Predictability pillar — token budget exhaustion -> clean 429.
#
# Shrinks the LLM token budget to 200 tokens, restarts the gateway (resets the
# bucket deterministically), fires an oversized request, and expects a clean
# 429 — not a hang, not a flail. Then restores the envelope. `tokenize: true`
# on every rung makes budgets bite at request time.
set -euo pipefail
cd "$(dirname "$0")/.."

CONFIG=gateway/config.yaml
GATEWAY=${GATEWAY:-http://localhost:4000}
METRICS=${METRICS:-http://localhost:15020/metrics}
TOKEN=$(python3 -c "import json;print(json.load(open('gateway/jwt/tokens.json'))['orchestrator'])")

restore() {
  git checkout -q -- "$CONFIG"
  docker compose restart gateway >/dev/null 2>&1 || true
}
trap restore EXIT

echo "=== verify-budget ==="
echo "shrinking LLM token budget to 200 tokens (the envelope is just YAML)..."
python3 - <<'EOF'
p = 'gateway/config.yaml'
s = open(p).read()
s = s.replace('maxTokens: 200000', 'maxTokens: 200').replace('tokensPerFill: 200000', 'tokensPerFill: 200')
open(p, 'w').write(s)
EOF
docker compose restart gateway >/dev/null 2>&1
sleep 3

LONG=$(python3 -c "print('describe the warehouse zones in detail. ' * 30)")
codes=()
for i in 1 2 3 4 5 6; do
  code=$(curl -s -o /dev/null -w "%{http_code}" -m 30 -X POST "$GATEWAY/v1/chat/completions" \
    -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d "{\"model\":\"robot-brain\",\"messages\":[{\"role\":\"user\",\"content\":\"$LONG\"}]}")
  codes+=("$code")
  [ "$code" = "429" ] && break
done
echo "status sequence: ${codes[*]}"

if printf '%s\n' "${codes[@]}" | grep -q '^429$'; then
  echo "PASS: budget exhaustion produced a clean 429 (robot safe-idles instead of flailing)"
else
  echo "FAIL: never saw a 429 (codes: ${codes[*]})"
  exit 1
fi
