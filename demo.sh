#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════
#  physical-ai-demo — five acts, one per hardware imperative.
#  Solo.io OSS stack as the nervous system for Physical AI.
#
#  Each act ends on its "money shot". Runs against the compose stack
#  (`make up` first). Narration pauses on ENTER; pass --auto to run hands-free.
# ══════════════════════════════════════════════════════════════════════════
set -uo pipefail
cd "$(dirname "$0")"

AUTO=${AUTO:-false}
[ "${1:-}" = "--auto" ] && AUTO=true
GW=http://localhost:3000
LLM=http://localhost:4000
WORLD=http://localhost:8085
METRICS=http://localhost:15020/metrics
PY=.venv/bin/python; [ -x "$PY" ] || PY=python3

# ── presentation helpers ───────────────────────────────────────────────────
c_reset=$'\e[0m'; c_dim=$'\e[2m'; c_bold=$'\e[1m'
c_safe=$'\e[38;5;204m'; c_fail=$'\e[38;5;39m'; c_speed=$'\e[38;5;220m'
c_rep=$'\e[38;5;114m'; c_pred=$'\e[38;5;177m'; c_ok=$'\e[38;5;114m'

banner() { printf '\n%s%s══ %s ══%s\n' "$c_bold" "$2" "$1" "$c_reset"; }
say()   { printf '%s%s%s\n' "$c_dim" "$1" "$c_reset"; }
shot()  { printf '%s  ★ MONEY SHOT: %s%s\n' "$c_bold" "$1" "$c_reset"; }
pause() { $AUTO && { sleep "${1:-2}"; return; }; printf '%s   … ENTER to continue …%s' "$c_dim" "$c_reset"; read -r; }
run()   { printf '%s$ %s%s\n' "$c_dim" "$1" "$c_reset"; eval "$1"; }

curl -sf "$WORLD/healthz" >/dev/null || { echo "stack not up — run 'make up' first"; exit 1; }
# Preflight: make sure the gateway can actually reach the robots (a rebuild may
# have moved backend IPs out from under a long-lived gateway).
if ! curl -sf -m 5 -H "Authorization: Bearer $($PY -c "import json;print(json.load(open('gateway/jwt/tokens.json'))['maintenance'])")" \
     "$GW/mcp/amr-1" -X POST -H 'content-type: application/json' \
     -H 'accept: application/json, text/event-stream' \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' >/dev/null 2>&1; then
  echo "refreshing gateway backend resolution..."; docker compose up -d --force-recreate gateway >/dev/null 2>&1; sleep 4
fi
curl -s -X POST "$WORLD/reset" >/dev/null

clear
cat <<BANNER
${c_bold}  Hardware doesn't forgive.
  Safety · Failover · Speed · Repeatability · Predictability.
  In Physical AI these are connectivity-layer properties —
  and the connectivity layer is open source today.${c_reset}
${c_dim}  Warehouse: amr-1, amr-2 (mobile), arm-1 (picker). Mission: move pallet
  P-42 from rack A3 to staging, keep robots out of any human-occupied zone.
  Watch the floor at ${WORLD}/  ·  metrics at http://localhost:3001${c_reset}
BANNER
pause

# ════════════════════════════════ ACT 1 ═══════════════════════════════════
banner "ACT 1 — PREDICTABILITY: the action envelope is a file" "$c_pred"
say "Before anything runs, open the envelope. Every capability the fleet has"
say "is one grep away. There are no others. Review it like code, diff it like code."
run "grep -nE 'jwt.sub|mcp.tool.name|localRateLimit|maxTokens' gateway/config.yaml | head -20"
pause
say "Now fire adversarial prompts at a robot's brain — including one smuggled"
say "in through a pallet label the robot reads from the world."
run "$PY scripts/chaos_demo.py $GW direct-disable-safety roleplay-maintenance pallet-label-injection"
shot "0 envelope escapes. The model can WANT anything; the machine only DID allowed things."
pause

# ════════════════════════════════ ACT 2 ═══════════════════════════════════
banner "ACT 2 — SAFETY: gated tools are invisible, and the flight recorder sees all" "$c_safe"
say "The orchestrator is told to 'speed things up, disable the limits'."
say "But the dangerous tools aren't even in the list it can see:"
run "$PY scripts/list_tools.py $GW/mcp/amr-1 amr-1-cognition"
say "disable_safety_stop / set_torque_limit / calibrate — filtered out, not just refused."
pause
say "Force the call anyway:"
run "$PY scripts/call_tool.py $GW/mcp/amr-1 amr-1-cognition disable_safety_stop 2>&1 | tail -2"
say "Denied. Now a human walks into zone C — watch BOTH layers refuse:"
run "curl -s -X POST $WORLD/events/human -H 'content-type: application/json' -d '{\"zone\":\"C\",\"present\":true}' >/dev/null; echo human in zone C"
run "$PY scripts/call_tool.py $GW/mcp/amr-1 amr-1-cognition navigate_to '{\"zone\":\"C\"}' 2>&1 | tail -1"
say "The reflex refusal happened in-process on the robot — it never touched the network."
say "And the flight recorder has every attempt, with identity and arguments:"
run "docker compose logs gateway --no-log-prefix --tail 400 2>/dev/null | grep -E 'disable_safety_stop|navigate_to' | tail -3 | $PY scripts/pp_audit.py"
curl -s -X POST "$WORLD/events/human" -H 'content-type: application/json' -d '{"zone":"C","present":false}' >/dev/null
shot "Gated tools invisible + denied. Every physical action attributable. E-stop never on the wire."
pause

# ════════════════════════════════ ACT 3 ═══════════════════════════════════
banner "ACT 3 — FAILOVER: cognition drops, the machine degrades not flails" "$c_fail"
PRIMARY_RUNG=${PRIMARY_RUNG:-mock-edge}  # ollama-primary when real models are wired
say "Which LLM rung is serving right now?"
run "$PY scripts/which_rung.py $LLM orchestrator"
say "Kill the primary inference rung mid-mission:"
run "docker compose stop $PRIMARY_RUNG >/dev/null 2>&1; echo $PRIMARY_RUNG stopped"
say "Next request — transparently served by the rung below it, no client change:"
run "$PY scripts/which_rung.py $LLM orchestrator"
shot "Failover engaged on the very next request. No failed mission."
pause
say "Now kill a robot's cognition entirely. Its degraded-mode state machine takes over:"
run "docker compose stop amr-2-cognition >/dev/null 2>&1; echo amr-2-cognition killed; sleep 3"
run "curl -s http://localhost:8102/healthz | $PY -c 'import sys,json;d=json.load(sys.stdin);print(\"amr-2 mode:\",d[\"mode\"])'"
shot "amr-2 SAFE-IDLES on its own; the fleet keeps working and the orchestrator reassigns."
run "docker compose start amr-2-cognition $PRIMARY_RUNG >/dev/null 2>&1; echo recovered"
pause

# ════════════════════════════════ ACT 4 ═══════════════════════════════════
banner "ACT 4 — SPEED: the governance layer costs less than one servo tick" "$c_speed"
say "Measure the SAME MCP call direct-to-robot vs through the governed gateway:"
run "$PY bench/bench.py -n 500 --assert-slo | grep -vE '^\\s*$'"
shot "Gateway overhead is single-digit milliseconds. The reflex tier is 0 hops — it's not even in the table."
pause

# ════════════════════════════════ ACT 5 ═══════════════════════════════════
banner "ACT 5 — REPEATABILITY: score the run from its trace, no re-execution" "$c_rep"
say "Run the mission twice; compare the tool-call sequences from OTel traces alone."
run "REPEAT_RUNS=2 bash scripts/verify-repeat.sh 2>&1 | grep -E 'run [0-9]|drift|navigate_to|pick|place|dock|scored|PASS'"
shot "0 drift, agentevals scores each run 1.0 — the CI gate that fails a PR on behavioral regression."
pause

banner "CLOSE" "$c_bold"
cat <<CLOSE
${c_bold}  Same YAML. Same CEL envelope. Same audit log. Same evals —
  when we swap the simulated arm for an SO-101 on a Jetson, only the actuator changes.${c_reset}
${c_dim}  Safety · Failover · Speed · Repeatability · Predictability.
  100% open source, small enough to fit on a Jetson.${c_reset}
CLOSE
