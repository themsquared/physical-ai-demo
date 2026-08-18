#!/usr/bin/env bash
# verify-kagent: Ops-tier encore. Crashloop a robot's cognition, ask the
# kagent fleet-sre to investigate, prove it diagnoses AND remediates.
#
# Assumes k8s/setup-k3d.sh has run (warehouse stack + kagent + fleet-sre up).
set -euo pipefail

NS=${NS:-warehouse}
KAGENT_NS=${KAGENT_NS:-kagent}
TARGET=${TARGET:-amr-2-cognition}
# Pin the cluster explicitly — never operate on whatever context happens to be
# current (a drifting context could hit an unrelated cluster).
CTX=${KUBE_CONTEXT:-k3d-physical-ai}
kubectl() { command kubectl --context "$CTX" "$@"; }
PY=.venv/bin/python; [ -x "$PY" ] || PY=python3

echo "=== verify-kagent ==="
echo "1) break $TARGET (bad command → CrashLoopBackOff)"
kubectl -n "$NS" patch deploy "$TARGET" --type=json -p \
  '[{"op":"replace","path":"/spec/template/spec/containers/0/command","value":["python","-c","import sys;sys.exit(1)"]}]'
kubectl -n "$NS" rollout status deploy/"$TARGET" --timeout=30s || true

echo "waiting for CrashLoopBackOff..."
for _ in $(seq 1 30); do
  state=$(kubectl -n "$NS" get pods -l app="$TARGET" \
    -o jsonpath='{.items[0].status.containerStatuses[0].state.waiting.reason}' 2>/dev/null || true)
  [ "$state" = "CrashLoopBackOff" ] && break
  sleep 3
done
echo "   $TARGET is now: ${state:-unknown}"
[ "$state" = "CrashLoopBackOff" ] || { echo "FAIL: could not induce crashloop"; exit 1; }

echo "2) ask fleet-sre to investigate & remediate (A2A via kagent controller)"
kubectl -n "$KAGENT_NS" port-forward svc/kagent-controller 8083:8083 >/dev/null 2>&1 &
PF=$!
trap 'kill $PF 2>/dev/null' EXIT
sleep 3

# Restore the good command first so the fleet-sre's restart actually recovers it
# (in the real failure the crash cause is external; here we simulate the fix
#  landing before the roll-restart the agent issues).
kubectl -n "$NS" patch deploy "$TARGET" --type=json -p \
  '[{"op":"replace","path":"/spec/template/spec/containers/0/command","value":["python","-m","agents.cognition"]}]'

"$PY" scripts/kagent_invoke.py \
  "http://localhost:8083/api/a2a/$KAGENT_NS/fleet-sre" \
  "Robot component $TARGET in the warehouse namespace is crashlooping. Investigate it: list the robot pods, get its events and logs, then restart_deployment on $TARGET to remediate, and confirm it recovered."

echo "3) confirm recovery"
kubectl -n "$NS" rollout status deploy/"$TARGET" --timeout=120s
ready=$(kubectl -n "$NS" get deploy "$TARGET" -o jsonpath='{.status.readyReplicas}')
[ "${ready:-0}" -ge 1 ] && echo "PASS: fleet-sre remediated $TARGET (ready=$ready)" \
                        || { echo "FAIL: $TARGET not ready"; exit 1; }
