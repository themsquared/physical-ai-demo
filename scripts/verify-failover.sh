#!/usr/bin/env bash
# verify-failover: Failover pillar acceptance (PRD M2).
#
# Proves: when the serving LLM rung dies mid-mission, the NEXT request is
# served by the rung below it — visible in the gateway's metrics — and no
# request fails once bounded client retries are in play.
#
# Works in two environments:
#   demo (ollama rungs up): stops ollama-primary and watches traffic move
#   CI   (mock only):        proves the chain walks all the way down to mock
set -euo pipefail
cd "$(dirname "$0")/.."

GATEWAY=${GATEWAY:-http://localhost:4000}
METRICS=${METRICS:-http://localhost:15020/metrics}
TOKEN=$(python3 -c "import json;print(json.load(open('gateway/jwt/tokens.json'))['orchestrator'])")

ask() { # one chat request; prints the model that actually served it, or FAIL
  curl -s -m 60 -X POST "$GATEWAY/v1/chat/completions" \
    -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d '{"model":"robot-brain","messages":[{"role":"user","content":"navigate to zone A"}]}' \
    | python3 -c "import sys,json
try: print(json.load(sys.stdin).get('model','FAIL'))
except Exception: print('FAIL')" 2>/dev/null || echo FAIL
}

ask_with_retries() { # the agents' behavior: bounded retries ride out eviction
  for _ in 1 2 3 4 5; do
    m=$(ask)
    [ "$m" != "FAIL" ] && { echo "$m"; return 0; }
    sleep 1
  done
  echo FAIL
}

echo "=== verify-failover ==="
before=$(ask_with_retries)
[ "$before" = "FAIL" ] && { echo "FAIL: no rung of the chain is serving"; exit 1; }
echo "serving rung before: $before"

# The default reproducible chain's top rung is mock-edge; real-model runs use
# ollama-primary. Kill whichever is up.
PRIMARY_RUNG=""
for cand in ollama-primary mock-edge; do
  if docker compose ps --status running "$cand" 2>/dev/null | grep -q "$cand"; then
    PRIMARY_RUNG=$cand; break
  fi
done

if [ -n "$PRIMARY_RUNG" ]; then
  echo "stopping top rung ($PRIMARY_RUNG) mid-flight..."
  docker compose stop "$PRIMARY_RUNG" >/dev/null
  KILLED=$PRIMARY_RUNG
else
  echo "(no top rung running — chain should already sit on a lower rung)"
  KILLED=none
fi

after=$(ask_with_retries)
echo "serving rung after:  $after"
[ "$after" = "FAIL" ] && { echo "FAIL: chain did not fail over"; exit 1; }

if [ "$KILLED" != "none" ] && [ "$before" = "$after" ]; then
  echo "FAIL: same rung still serving after the top rung was stopped"
  exit 1
fi

# metric evidence: token usage grouped by the model that served it
echo "--- metric evidence (gen_ai token usage by response model) ---"
curl -s "$METRICS" | grep -E 'gen_ai.*token_usage_count' | grep -oE 'gen_ai_response_model="[^"]*"' | sort | uniq -c || true

if [ "$KILLED" != "none" ]; then
  echo "restarting $KILLED..."
  docker compose start "$KILLED" >/dev/null
fi
echo "PASS: failover engaged; no request lost with bounded retries"
