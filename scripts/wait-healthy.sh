#!/usr/bin/env bash
# Wait until the core stack answers: world, robots, gateway readiness, agents.
set -euo pipefail
cd "$(dirname "$0")/.."

wait_for() { # url, name, tries
  local url=$1 name=$2 tries=${3:-60}
  for _ in $(seq 1 "$tries"); do
    if curl -sf -m 2 "$url" >/dev/null 2>&1; then echo "  $name ready"; return 0; fi
    sleep 1
  done
  echo "TIMEOUT waiting for $name ($url)"; return 1
}

echo "waiting for stack..."
wait_for http://localhost:8085/healthz world
wait_for http://localhost:8101/healthz amr-1
wait_for http://localhost:8102/healthz amr-2
wait_for http://localhost:8103/healthz arm-1
wait_for http://localhost:8200/healthz mock-llm
wait_for http://localhost:15020/metrics gateway
wait_for http://localhost:9000/healthz orchestrator
wait_for http://localhost:9101/healthz amr-1-cognition
wait_for http://localhost:9102/healthz amr-2-cognition
wait_for http://localhost:9103/healthz arm-1-cognition
echo "stack healthy"
