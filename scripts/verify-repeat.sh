#!/usr/bin/env bash
# verify-repeat: Repeatability pillar acceptance (PRD M5).
#
# Runs the same mission N times against the deterministic brain, then proves:
#   1. every run's (agent, tool, args) sequence is IDENTICAL (drift = zero)
#   2. agentevals scores every run 1.0 against the golden trace —
#      from OTel traces alone, nothing re-executed.
#
# REPEAT_RUNS=10 by default (the PRD SLO); set lower for a quick check.
set -euo pipefail
cd "$(dirname "$0")/.."

RUNS=${REPEAT_RUNS:-10}
[ "${1:-}" = "--ci" ] && RUNS=${REPEAT_RUNS:-10}
PY=.venv/bin/python
[ -x "$PY" ] || PY=python3
AGENTEVALS=.venv/bin/agentevals
[ -x "$AGENTEVALS" ] || AGENTEVALS=agentevals

WORK=$(mktemp -d)
echo "=== verify-repeat ($RUNS runs) ==="

# Deterministic brain required: park the live model rungs on the mock.
docker compose stop ollama-primary ollama-fallback >/dev/null 2>&1 || true
docker compose restart gateway >/dev/null 2>&1
sleep 3

for i in $(seq 1 "$RUNS"); do
  rm -f evals/traces/traces.jsonl
  docker compose restart otel-collector >/dev/null 2>&1
  sleep 2
  bash scripts/run-mission.sh --verify >/dev/null
  sleep 6 # batch span flush
  $PY evals/merge_traces.py evals/traces/traces.jsonl "$WORK/run$i.json" \
    orchestrator amr-1-cognition amr-2-cognition arm-1-cognition >/dev/null
  $PY evals/extract_sequence.py "$WORK/run$i.json" > "$WORK/seq$i.txt"
  echo "run $i: $(wc -l < "$WORK/seq$i.txt" | tr -d ' ') tool calls"
done

echo "--- drift check: sequences must be identical across all runs ---"
for i in $(seq 2 "$RUNS"); do
  if ! diff -q "$WORK/seq1.txt" "$WORK/seq$i.txt" >/dev/null; then
    echo "FAIL: run $i drifted from run 1:"
    diff "$WORK/seq1.txt" "$WORK/seq$i.txt" || true
    exit 1
  fi
done
echo "0 drift across $RUNS runs. Sequence:"
sed 's/^/    /' "$WORK/seq1.txt"

echo "--- agentevals gate: score every run against the golden trace ---"
"$AGENTEVALS" run "$WORK"/run*.json \
  --eval-set evals/golden/mission-p42.eval.json \
  -m tool_trajectory_avg_score --trajectory-match-type in_order \
  --output json 2>/dev/null > "$WORK/scores.json"
$PY - "$WORK/scores.json" <<'EOF'
import json
import sys

d = json.load(open(sys.argv[1]))
scored = [t for t in d["traces"] if t["num_invocations"] > 0]
bad = [
    (t["trace_id"], m)
    for t in scored
    for m in t["metrics"]
    if m["score"] is None or m["score"] < 1.0
]
print(f"scored mission traces: {len(scored)}")
if not scored:
    print("FAIL: agentevals extracted no scorable traces")
    sys.exit(1)
if bad:
    print(f"FAIL: {len(bad)} runs scored below 1.0: {bad}")
    sys.exit(1)
print("all runs scored 1.0 against golden trace (no re-execution)")
EOF

echo "PASS: verify-repeat"
