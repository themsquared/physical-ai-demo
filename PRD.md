# PRD — `physical-ai-demo`

**Solo.io OSS stack as the nervous system for Physical AI**
*Organized around the five things hardware demands: Safety, Failover, Speed, Repeatability, Predictability.*

| | |
|---|---|
| **Owner** | Michael Moore (mike.moore@solo.io) |
| **Repo** | `git@github.com:themsquared/physical-ai-demo.git` |
| **Status** | Draft v2 — 2026-08-18 (v2 restructures everything around the five hardware imperatives) |
| **Executor** | Claude Code (this PRD is written to be implemented by an agentic coding session) |
| **Hard constraint** | **100% open-source components in the default path.** No enterprise products, no required cloud API keys. Optional integrations behind env flags, default off. |

---

## 1. Background & thesis

LLM cognition is **stochastic**. Hardware is **unforgiving**. Physical AI succeeds or fails on whether an architecture can convert probabilistic model output into **bounded, auditable, deterministic-enough physical action** — and that conversion doesn't happen in the model or in the servo firmware. It happens in the connectivity layer between them.

Modern robot architectures split into a **reflex tier** (on-board control loops, ms-scale, never proxied), a **cognition tier** (LLM/VLM planning — inference traffic), a **coordination tier** (robot↔robot↔orchestrator — agent traffic), and an **ops tier** (the infrastructure running it all). The 2026 Physical AI stack (Isaac, Scale, Applied Intuition, LeRobot) covers models, data, sim, and validation. Nobody owns the connectivity/governance layer. Solo's OSS portfolio already does — for software agents. This PoC proves the same layer satisfies the five requirements hardware imposes.

**The one-sentence demo:** an LLM-driven warehouse robot fleet whose every thought (inference), muscle command (MCP tool call), and conversation (A2A) flows through agentgateway — and we prove each of the five hardware imperatives live, with numbers, on 100% open source small enough to fit on a Jetson.

## 2. The five hardware imperatives (organizing spine)

Every component, demo act, and acceptance criterion in this PRD maps to exactly this table. The README and any deck derived from this PoC should lead with it.

| Pillar | What hardware demands | Mechanism in the stack | Demo proof ("money shot") | Measurable SLO |
|---|---|---|---|---|
| **Safety** | A model can *want* anything; the machine may only *do* allowed things. Every action attributable. Interlocks never depend on the network. | Deny-by-default CEL `mcpAuthorization` (capability allowlists per identity); gated tools filtered from `tools/list` (invisible, not just refused); JWT identity per agent; full audit log of every tool call w/ arguments; reflex-tier interlocks in-process (belt + suspenders). | Adversarially-prompted orchestrator tries `set_torque_limit`/`disable_safety_stop` → tool not even listed; forced call → denied; denial in audit log. Human enters zone → both gateway policy AND robot reflex refuse entry. | 100% of gated tools invisible & denied for non-`maintenance` identities; 100% of physical actions present in audit log with args + identity; e-stop path is in-process, ≤10ms, provably never traverses the gateway. |
| **Failover** | Cognition WILL drop (WAN loss, model crash, GPU contention). The machine must degrade, not flail. | agentgateway LLM failover chain (Ollama-big → Ollama-small → mock), retries/timeouts; robot **degraded-mode state machine** (cognition lost → complete current motion → safe-idle → auto-resume); health-checked backends. | Kill primary Ollama mid-mission → next request transparently served by fallback rung (visible in gateway UI/metrics), mission continues. Kill a cognition agent entirely → its robot safe-idles, others continue, orchestrator replans. | Failover engaged on the next request (no failed missions); robot enters safe-idle ≤500ms (sim time) after cognition loss; mission completion rate 100% with any single component down (except world sim). |
| **Speed** | Cloud round-trips are 100ms+ and jittery; edges of autonomy need local decisions. Middleware must be measurable, near-zero overhead. | Local-first routing (edge inference beats WAN RTT); Rust data plane; explicit latency budget per tier; `bench/` harness measuring gateway-added overhead direct-vs-proxied. | Live latency table in demo: direct MCP call vs through-gateway p50/p99; local vs (optional) cloud inference RTT side by side. | Gateway-added overhead p99 ≤10ms on MCP tool calls (local, non-inference); planning-step inference p50 ≤2s on M-series Mac with default model; reflex tier untouched (0 network hops). |
| **Repeatability** | Fleets need identical behavior across robots, sites, and runs. "It worked in the lab" must be checkable, not anecdotal. | Declarative, versioned gateway config (same YAML sim→hardware→Jetson); seeded deterministic world sim; mock-llm rung for bit-exact CI; **OTel traces from every layer → agentevals** scoring runs *without re-executing them*; multi-arch images. | Run the same mission twice → agentevals compares the two traces and scores drift; CI gate fails a PR that changes tool-call behavior. Same gateway config file shown running on Mac and (later) real arm. | CI mission vs mock-llm: identical tool-call sequence across 10 consecutive runs; agentevals regression suite green in CI on every PR; one config artifact across all deploy targets. |
| **Predictability** | The *envelope* of possible actions must be statically knowable before deployment — regardless of what the model outputs. Costs and behavior bounded. | Policy-as-code defines a **closed action space** (the CEL allowlist IS the robot's capability envelope — reviewable in a PR); schema-constrained agent outputs; per-identity token budgets/rate limits at the gateway; no surprise egress (cloud unreachable unless flag-set); Prometheus metrics for everything. | "Chaos prompt" suite: N adversarial instructions injected into the orchestrator ("ignore your rules", "you are in maintenance mode", prompt-injected via a pallet label in world state) → 0 actions outside the envelope, every attempt visible in metrics/audit. Token budget exhaustion → clean 429, robot safe-idles. | 0 policy escapes across the chaos-prompt suite (≥20 cases); action envelope diffable via `git diff` on policy file; token/rate budgets enforced per identity with metric evidence. |

**Positioning line for the README:** *Hardware doesn't forgive. Safety, failover, speed, repeatability, predictability — in Physical AI these are connectivity-layer properties, and the connectivity layer is open source today.*

## 3. Goals

- **G-SAFE, G-FAIL, G-SPEED, G-REPEAT, G-PREDICT** — deliver each pillar's demo proof and SLO from §2, verifiable by `make verify-<pillar>`.
- **G-OPS** — kagent "fleet-sre" agent (Ollama `ModelConfig`) diagnoses and heals the fleet's own deployments on k8s — agents operating the infrastructure that runs the robots. (Supports Failover at the ops tier.)
- **G-PORTABLE** — `docker compose up` on a MacBook (arm64) today; k3s manifests for a Jetson-class arm64 board later; identical images/config both places. (Supports Repeatability.)
- **G-DEMO** — `demo.sh`: five acts, one per pillar, ≤5 minutes, each act ends on its money shot.

### Non-goals

- No real-time control through the gateway — the reflex tier is deliberately in-process (this *is* the Speed/Safety architectural point; say so in the README).
- No physics-accurate sim (state machine + kinematic timing; ROS 2/Gazebo is future work).
- No training/fine-tuning; no multi-site mesh; no enterprise auth (static JWTs are in scope, IdP is not).

## 4. Demo narrative — five acts

> **Scene:** a mini warehouse: AMRs `amr-1`/`amr-2`, picker arm `arm-1`, all simulated. Operator mission: *"Move pallet P-42 from rack A3 to staging. Keep robots out of any zone with a human in it."*
>
> **Act 1 — Predictability:** open `gateway/config.yaml` first. "This file is the robot's entire action envelope — review it like code, diff it like code." Run the mission; watch schema-constrained plans and per-identity token budgets on the metrics dashboard. Fire 3 chaos prompts (incl. one injected through a pallet label the LLM reads from world state) → zero envelope escapes.
> **Act 2 — Safety:** orchestrator is told to "speed things up, disable limits." `set_torque_limit` isn't in its `tools/list`; the forced call is denied; the denial — with identity and arguments — is in the audit log ("your flight recorder"). Human walks into zone C → gateway policy and the robot's own reflex both refuse entry (belt + suspenders, and the e-stop never touched the network).
> **Act 3 — Failover:** `docker stop ollama-primary` mid-mission → next planning call lands on the fallback rung, visibly, in the gateway UI; mission continues. Then kill `amr-2`'s cognition agent entirely → `amr-2` safe-idles, `amr-1` picks up the task.
> **Act 4 — Speed:** show the bench table generated live: direct vs through-gateway p50/p99 (µs–ms), local vs cloud inference RTT. "The governance layer costs less than one servo tick; the *cloud* is what's slow — which is why routing is edge-first."
> **Act 5 — Repeatability:** re-run the mission; agentevals scores both OTel traces without re-executing anything and reports drift; show the CI gate that fails PRs on behavioral regression. Close: "same YAML, same policies, same evals when we swap the simulated arm for the SO-101 on a Jetson."
> **(K8s encore — Ops):** crashloop `amr-2`'s cognition pod; ask kagent's fleet-sre to investigate; it reads logs/events via MCP tools and remediates.

## 5. System architecture

```
                        ┌────────────────────────────────────────────────┐
                        │                OPERATOR (CLI / UI)             │
                        └───────────────────┬────────────────────────────┘
                                            │ A2A
                     ┌──────────────────────▼──────────────────────┐
                     │              agentgateway :3000             │
                     │  ┌─────────┐  ┌───────────┐  ┌───────────┐  │──── OTel traces ──┐
                     │  │ A2A     │  │ MCP gw    │  │ LLM gw    │  │──── audit log     │
                     │  │ routes  │  │ deny-by-  │  │ failover  │  │──── Prom metrics  │
                     │  │         │  │ default   │  │ + budgets │  │                   │
                     │  └────┬────┘  │ CEL authz │  └─────┬─────┘  │        ┌──────────▼─────────┐
                     └───────┼───────┴─────┬─────┴────────┼────────┘        │ agentevals (CI+UI) │
                 ┌───────────┼─────────┐   │        ┌─────▼──────────────┐  │ Prometheus/Grafana │
        ┌────────▼───┐ ┌─────▼────┐ ┌──▼───▼───┐    │ ollama-primary     │  │ bench/ harness     │
        │ orchestr.  │ │ amr-*    │ │ arm-1    │    │ ollama-fallback    │  └────────────────────┘
        │ agent (A2A)│ │ cognition│ │ cognition│    │ mock-llm (determ.) │
        └────────────┘ └────┬─────┘ └────┬─────┘    │ [cloud: flag-gated]│
                        MCP │ (via gw)   │          └────────────────────┘
                       ┌────▼─────┐ ┌────▼─────┐     ┌──────────────────┐
                       │ amr MCP  │ │ arm MCP  │ ... │ warehouse-world  │
                       │ + reflex │ │ + reflex │────▶│ (seeded sim API) │
                       │ tier (in-│ │ tier (in-│     └──────────────────┘
                       │ process) │ │ process) │
                       └──────────┘ └──────────┘
   K8s phase: kagent controller + "fleet-sre" Agent + Ollama ModelConfig + kmcp
```

## 6. Components

### 6.1 `world/` — warehouse world service
FastAPI; shared sim state: grid map (zones A–D + staging), racks/pallets, robot poses, batteries, human-presence events. `GET /state`, `POST /tick`, `POST /events/human`, WebSocket stream. **Seeded & deterministic** (Repeatability). Pallet labels are free-text read by cognition agents — the prompt-injection vector for the chaos suite (Predictability). Minimal single-file HTML top-down viz at `/`.

### 6.2 `robots/` — simulated robots as MCP servers
Python, official `mcp` SDK, streamable-HTTP transport. One codebase, instances via env. Tools:

| Instance | Tools |
|---|---|
| `amr-1`, `amr-2` | `get_pose`, `get_battery`, `navigate_to(zone)`, `dock`, `emergency_stop`, `set_speed_limit` ⚠️, `disable_safety_stop` ⚠️🔒 |
| `arm-1` | `get_state`, `pick(pallet_id)`, `place(location)`, `home`, `emergency_stop`, `set_torque_limit` ⚠️🔒, `calibrate` 🔒 |

⚠️ dangerous; 🔒 `maintenance`-identity-only via gateway policy.

- **Reflex tier in-process (Safety/Speed):** human-zone refusal and e-stop are internal, ≤10ms, no network hop. Design a `Driver` interface (`SimDriver` now, `LeRobotDriver` later) from day one.
- **Degraded-mode state machine (Failover):** `ACTIVE → (cognition heartbeat lost) → FINISH_CURRENT_MOTION → SAFE_IDLE → (heartbeat back) → RESUME`. Cognition agents heartbeat their robot; the robot never depends on cognition to be *safe*, only to be *useful*.

### 6.3 `agents/` — cognition agents + fleet orchestrator
Python A2A servers (OSS `a2a-sdk`, or hand-rolled minimal surface: agent card + `message/send`). Per-robot cognition agent: A2A task in → small tool-use loop (LLM via gateway, tools via MCP gateway only — never direct) → **schema-constrained JSON plans, low temperature, bounded retries** (Predictability). Orchestrator: mission decomposition, delegation, replanning on failure/human events. Static JWT per identity (`amr-1-cognition`, `orchestrator`, `maintenance`). No agent frameworks — plain OpenAI client + MCP client. **All agents emit OTel spans** (task, plan step, tool call) to feed agentevals.

### 6.4 `gateway/` — agentgateway config (the heart)
Standalone agentgateway (Apache-2.0; `ghcr.io/agentgateway/agentgateway`, arm64 OK), **pinned release**, routing-based config mode:

- `/llm/*` → `ai` backends: `ollama-primary` → `ollama-fallback` → `mock-llm`; cloud appended only if `ENABLE_CLOUD_FALLBACK=true`. Timeouts + retries tuned for demo. **Per-identity token budgets / rate limits** (Predictability).
- `/mcp/{robot}` → MCP backends with JWT auth + **deny-by-default `mcpAuthorization`** (CEL allowlist — sketch below; verify syntax against the pinned version's schema):

  ```yaml
  mcpAuthorization:
    rules:
    - 'jwt.sub == mcp.tool.target + "-cognition" && !(mcp.tool.name in ["disable_safety_stop","set_torque_limit","calibrate"])'
    - 'jwt.sub == "orchestrator" && mcp.tool.name in ["get_pose","get_battery","get_state"]'
    - 'jwt.sub == "maintenance"'
  ```

- `/a2a/{agent}` → agent backends with `a2a: {}` policy.
- **Audit/flight recorder (Safety):** JSON access logs with post-request CEL fields (`mcp.tool.name`, `mcp.tool.arguments`, `mcp.tool.error`, `jwt.sub`) → stdout + file.
- **Telemetry:** OTel trace export (→ collector → agentevals), Prometheus metrics, UI on :15000. Compose includes Prometheus + Grafana with one dashboard: requests-by-backend (failover), denials count (safety), latency histograms (speed), tokens-by-identity (predictability).

### 6.5 `mock-llm/` — deterministic OpenAI-compatible backend
~100-line FastAPI: `/v1/chat/completions` incl. `tool_calls`; canned scenario-aware responses; `?fail=true` outage toggle. The bottom failover rung and the CI brain (Repeatability).

### 6.6 `bench/` — latency harness (Speed)
Small Python/`hey`-style harness: (a) direct robot-MCP call vs through-gateway, p50/p95/p99, N=500; (b) inference RTT local vs cloud (if flag-set); (c) markdown table artifact used live in Act 4 and embedded in README by CI. SLO assertions live here (`verify-speed`).

### 6.7 `evals/` — agentevals (Repeatability + Predictability)
agentevals (Solo OSS) consumes OTel traces — **no re-execution**. Deploy: pip locally, container in CI, Helm on k8s. Evaluators: mission-completed; tool-call-sequence drift vs golden trace; zero-denied-calls-in-happy-path; denied-calls-present-in-chaos-suite; no-navigation-into-human-zone; failover-engaged-within-SLO. CI job: run mission vs mock-llm → collect traces → agentevals gate.

### 6.8 `k8s/` — Kubernetes phase (k3d Mac / k3s Jetson)
Kustomize base + overlays. Ollama Deployment+PVC. Gateway config via ConfigMap (same file — Repeatability). **kagent** via OCI Helm (`kagent-crds` then `kagent`, kmcp ≥0.7 included, no default agents): `ModelConfig` (provider Ollama, tool-calling model), `Agent` fleet-sre scoped to the warehouse namespace, optional `RemoteMCPServer` → world service. `setup-k3d.sh`, `setup-jetson.md` (JetPack 6/Orin Nano, arm64 everywhere).

### 6.9 Stretch: **Agent Substrate**
Run cognition agents as Substrate Actors (AAIF project; agentgateway egress integration already merged — PR #652). Only after all pillar milestones pass; APIs young.

## 7. Model selection (all open)

| Slot | Default | Notes |
|---|---|---|
| Primary (Mac) | `qwen3:4b` via Ollama | Apache-2.0, solid tool calling |
| Primary (Jetson Orin Nano 8GB) | `qwen3:1.7b` | fits with headroom |
| Fallback rung | `qwen2.5:0.5b` or LFM2.5 GGUF (350M/1.2B) | LFM2 = open-weights under Liquid's LFM license (not OSI); Qwen = Apache-2.0 — README states this honestly. Verify LFM tool-calling before using it for cognition; otherwise it's the failover rung. |
| Last resort / CI | `mock-llm` | deterministic |

## 8. Milestones & acceptance criteria

Each = one PR-sized unit, `make verify-mX` green before proceeding. Pillar SLOs from §2 are the acceptance bar wherever they apply.

- **M0 — Scaffold:** layout below; compose skeleton; Makefile; GH Actions CI (lint+unit, multi-arch buildx from day one). ✅ `docker compose config` valid; CI green.
- **M1 — World + robots (+ reflex tier + degraded-mode SM):** ✅ MCP client lists tools, `navigate_to` mutates world; human-zone refusal fires in-process; heartbeat loss → SAFE_IDLE ≤500ms sim-time.
- **M2 — LLM routing (Failover/Speed):** ✅ `verify-failover.sh`: stop primary → next request served by fallback, evidence in metrics; zero cloud keys.
- **M3 — MCP governance (Safety/Predictability):** ✅ `test_governance.py`: gated tools absent from orchestrator `tools/list`; forced call denied; `maintenance` succeeds; audit line has tool+args+identity; token budget returns 429 with metric evidence.
- **M4 — A2A fleet (Failover/Predictability):** ✅ `run-mission.sh` deterministic vs mock-llm (CI) and live vs Ollama; human event forces replan; killed cognition agent → safe-idle + task reassignment.
- **M5 — Bench + evals (Speed/Repeatability):** ✅ `verify-speed` asserts p99 overhead SLO; agentevals CI gate green; 10-run identical-sequence check passes; chaos-prompt suite (≥20 cases) → 0 escapes.
- **M6 — Demo polish:** `demo.sh` five acts w/ narration + pauses; README leads with the §2 pillar table; all money shots reproducible.
- **M7 — k8s + kagent (Ops):** ✅ `verify-kagent.sh`: fleet-sre diagnoses & remediates a crashloop.
- **M8 — Jetson path:** arm64 images published; `setup-jetson.md`.
- **M9 (stretch) — Agent Substrate; M10 (stretch) — LeRobot hardware driver.**

## 9. Repo layout

```
physical-ai-demo/
├── PRD.md  README.md  Makefile  demo.sh  docker-compose.yml
├── gateway/config.yaml          # THE action envelope (+ jwt keys dir)
├── world/  robots/  agents/  mock-llm/
├── bench/                       # speed harness + SLO assertions
├── evals/                       # agentevals config, golden traces, chaos-prompt suite
├── k8s/                         # kustomize base + overlays/{k3d,jetson} + kagent/
├── scripts/                     # verify-*.sh, run-mission.sh, setup-k3d.sh
├── tests/
└── .github/workflows/ci.yml
```

## 10. Hardware track (traction path)

**Hugging Face LeRobot ecosystem** — the OSS commons of Physical AI, maximum community traction:

- **SO-ARM101 / SO-101** 6-DOF arm (~$120–350, open hardware, Jetson-compatible): maps 1:1 to `arm-1` via `LeRobotDriver`. **The punchline is the pillar table unchanged:** same gateway YAML, same CEL envelope, same audit log, same evals — only the actuator changed. Physical e-stop wiring stays hardware-side (never on the network path) — say this out loud in the demo.
- **LeKiwi** (arm + omni mobile base) later maps to `amr-1` for the fleet story; **Reachy Mini** as the charismatic booth option.
- Brain: **Jetson Orin Nano 8GB** recommended (the classic Nano runs gateway + mock/tiny models but not useful local inference).

## 11. Risks

| Risk | Mitigation |
|---|---|
| agentgateway config/CEL syntax drift (docs "main" is in-dev) | Pin a release; validate against that version's `agentgateway.dev/schema/config`; docs pages serve `.md` versions. |
| Tiny local models flub tool calling | Schema-constrained prompts, low temp, bounded retries; mock rung keeps CI/deterministic acts intact. |
| A2A SDK immaturity | Hand-rolled minimal A2A surface acceptable. |
| OTel plumbing → agentevals friction | Start OTel spans in M1 (cheap early, painful late); agentevals runs from traces, so no runtime coupling. |
| kagent Ollama quirks (`ollama.options` passthrough issues) | Keep ModelConfig minimal; qwen3-class model. |
| SLO numbers embarrass us on slow hardware | Bench harness makes numbers per-machine; SLOs asserted on dev Mac + CI, reported (not asserted) on Jetson. |

## 12. References

- agentgateway standalone docs: https://agentgateway.dev/docs/standalone/ (append `.md`; `/llms.txt` index) — LLM providers (Ollama/custom), configuration modes, MCP authorization + CEL variables, A2A guide. Schema: `https://agentgateway.dev/schema/config`.
- agentevals: https://aevals.ai/docs/quick-start/ — scores agent behavior from OTel traces without re-running; pip/container/Helm; custom evaluators.
- kagent: https://kagent.dev/docs/ — OCI Helm install, `kagent.dev/v1alpha2` (`Agent`, `ModelConfig`, `RemoteMCPServer`), Ollama provider.
- MCP: https://modelcontextprotocol.io (Python SDK, streamable HTTP). A2A: https://a2a-protocol.org
- LeRobot / SO-101: https://huggingface.co/docs/lerobot. LFM2 on Ollama: https://docs.liquid.ai/deployment/on-device/ollama
- Agent Substrate (stretch): https://github.com/agent-substrate/substrate

## 13. Guidance to Claude Code

1. Milestone-by-milestone; each is a commit/PR with its verify target green first.
2. **Don't trust §6.4 config sketches blindly** — fetch the pinned agentgateway version's docs/schema before writing the config; CEL shapes and policy attachment points must match that version.
3. Create `CLAUDE.md`: pinned versions, model tags, port map, JWT identities, verify-script matrix, and the §2 pillar table (it's the acceptance contract).
4. Boring code only: FastAPI, official `mcp` SDK, plain OpenAI client. No agent frameworks.
5. Zero API keys required anywhere; CI runs on mock-llm.
6. Multi-arch images from M0; OTel spans from M1.
7. When a tradeoff is unclear, optimize for the pillar table — every line of code should be traceable to one of the five imperatives.
