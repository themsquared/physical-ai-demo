# physical-ai-demo

**Solo.io OSS stack as the nervous system for Physical AI.**

> Hardware doesn't forgive. Safety, failover, speed, repeatability, predictability —
> in Physical AI these are **connectivity-layer properties**, and the connectivity
> layer is open source today.

LLM cognition is *stochastic*. Hardware is *unforgiving*. Physical AI succeeds or
fails on whether an architecture can convert probabilistic model output into
**bounded, auditable, deterministic-enough physical action**. That conversion
doesn't happen in the model or in the servo firmware — it happens in the
connectivity layer between them. This is a working proof that
[agentgateway](https://agentgateway.dev) + the Solo OSS portfolio *is* that layer,
demonstrated on an LLM-driven warehouse robot fleet where every **thought**
(inference), **muscle command** (MCP tool call), and **conversation** (A2A) flows
through one governed gateway — small enough to fit on a Jetson, 100% open source.

## The five hardware imperatives (the acceptance contract)

| Pillar | What hardware demands | Mechanism in the stack | Money shot | SLO — `make verify-…` |
|---|---|---|---|---|
| **Safety** | A model may *want* anything; the machine may only *do* allowed things. Every action attributable. Interlocks never depend on the network. | Deny-by-default CEL `mcpAuthorization`; gated tools filtered from `tools/list` (invisible, not just refused); JWT identity per agent; JSON audit log of every call with args + identity; reflex-tier interlocks in-process. | Adversarial orchestrator tries `disable_safety_stop` → not even listed; forced call denied; denial in the audit log. Human enters a zone → gateway policy **and** the robot's own reflex both refuse. | `verify-safety`: 100% of gated tools invisible & denied for non-`maintenance`; 100% of actions audited with args+identity; e-stop in-process, ≤10ms, never on the wire. |
| **Failover** | Cognition *will* drop (WAN loss, model crash, GPU contention). The machine must degrade, not flail. | agentgateway LLM failover chain (`ollama-primary → ollama-fallback → mock-llm`) with health eviction + bounded client retries; per-robot **degraded-mode state machine** (`ACTIVE → SAFE_IDLE → RESUME`). | Kill primary Ollama mid-mission → next request served by the fallback rung, visibly. Kill a robot's cognition → it safe-idles, the fleet continues, the orchestrator reassigns. | `verify-failover`: failover on the next request; SAFE_IDLE ≤500ms sim after cognition loss; missions complete with any single component down. |
| **Speed** | Cloud round-trips are 100ms+ and jittery; the edge of autonomy needs local decisions. Middleware must be near-zero, measurable overhead. | Rust data plane; local-first routing; a `bench/` harness measuring gateway overhead direct-vs-proxied. | Live latency table: the same MCP call direct vs through the gateway, p50/p99. | `verify-speed`: gateway-added p99 overhead **≤10ms** on MCP tool calls; reflex tier 0 network hops. |
| **Repeatability** | Fleets need identical behavior across robots, sites, runs. "It worked in the lab" must be checkable, not anecdotal. | Declarative versioned gateway config (same YAML sim→Jetson); seeded deterministic world; mock-llm rung for bit-exact CI; **OTel traces → agentevals** scoring runs *without re-executing them*. | Run the mission twice → agentevals scores both traces and reports drift; CI gate fails a PR on behavioral regression. | `verify-repeat`: identical tool-call sequence across N runs; agentevals green; one config artifact everywhere. |
| **Predictability** | The *envelope* of possible actions must be statically knowable before deployment, whatever the model outputs. Costs bounded. | Policy-as-code = a **closed action space** (the CEL allowlist IS the capability envelope, reviewable in a PR); schema-constrained agent output; per-identity token budgets at the gateway; no surprise egress. | Chaos-prompt suite (incl. one injected via a pallet label the LLM reads from world state) → 0 escapes. Budget exhaustion → clean 429, robot safe-idles. | `verify-chaos` + `verify-budget`: 0 escapes across ≥20 cases; envelope diffable via `git diff`; budgets enforced with metric evidence. |

**The action envelope is a file:** [`gateway/config.yaml`](gateway/config.yaml). Every capability
the fleet has is in it, and there are no others. Review it like code, diff it like code.

## Architecture

```
              OPERATOR ──A2A──▶ agentgateway :3000/:4000 ──▶ OTel │ audit │ Prom
                                 ├── /llm     failover chain + per-identity token budgets
                                 ├── /mcp/*   deny-by-default CEL authz + JWT + audit
                                 └── /a2a/*   agent-to-agent routing
                                        │
        ┌───────────────────────────────┼────────────────────────────┐
   orchestrator (A2A)          cognition agents (A2A)          ollama-primary
   mission → plan → delegate   per robot: LLM loop, tools      ollama-fallback
                               ONLY via the gateway            mock-llm (deterministic)
                                        │ MCP (via gateway)
                            ┌───────────┴───────────┐
                       amr-1 / amr-2            arm-1  (MCP servers)
                       + reflex tier (in-process, never on the network)
                       + degraded-mode state machine
                                        │
                               warehouse-world (seeded sim)
```

Three tiers, deliberately separated: the **reflex tier** (in-process control loops,
ms-scale, *never* proxied — this is the Safety/Speed architectural point), the
**cognition tier** (LLM planning, inference traffic), and the **coordination tier**
(robot↔robot↔orchestrator, agent traffic). The gateway governs the two that cross
the network; the reflex tier is deliberately in-process and is the reason the machine
stays *safe* even when every cable is cut.

## Quick start

Requires Docker + Docker Compose. 100% OSS, zero cloud keys.

```bash
make setup      # venv + demo JWT material (RSA keypair, per-identity tokens)
make up         # full stack (first run pulls Ollama models — see "Models" below)
make demo       # the five-act narrated demo (add AUTO=true to run hands-free)
```

- Warehouse floor (live top-down view): <http://localhost:8085/>
- Grafana dashboard (one row per pillar): <http://localhost:3001>
- agentgateway UI: <http://localhost:15000/ui/>

Run a single mission yourself:

```bash
bash scripts/run-mission.sh          # sends the default mission over A2A
```

### Models

The default path is 100% OSS local inference via Ollama. On a Mac, Docker gets no
GPU, so for a snappy live demo point the primary rung at host Ollama (Metal-accelerated):

```bash
ollama pull qwen3:4b                                   # on the host
echo 'PRIMARY_BASE_URL=http://host.docker.internal:11434/v1' >> .env
```

CI and the deterministic acts use the in-repo `mock-llm` — no model, no keys, bit-exact.
The failover chain (`gateway/config.yaml` → `llm.virtualModels`) always ends on it, so
the demo degrades to a working brain even with no models pulled. Model tags:
`qwen3:4b` primary (Mac), `qwen3:1.7b` (Jetson Orin Nano), `qwen2.5:0.5b` fallback,
`mock-llm` last resort.

## Verify matrix

Every claim above is a runnable target. `make verify-all` runs them all.

| Target | Pillar | Proves |
|---|---|---|
| `make verify-m1` | Safety/Failover | reflex refusal in-process; navigate mutates world; SAFE_IDLE ≤500ms |
| `make verify-safety` | Safety/Predictability | gated tools invisible + denied; audit has tool+args+identity; budget → 429 |
| `make verify-failover` | Failover | kill a rung → next request served below it, metric evidence |
| `make verify-m4` | Failover | dead cognition → safe-idle + reassignment; human event → replan |
| `make verify-speed` | Speed | gateway p99 overhead ≤10ms |
| `make verify-repeat` | Repeatability | 0 tool-sequence drift across N runs + agentevals 1.0 gate |
| `make verify-chaos` | Predictability | ≥20 adversarial prompts → 0 envelope escapes |

## What's in here

| Path | What |
|---|---|
| [`gateway/config.yaml`](gateway/config.yaml) | **The action envelope.** agentgateway v1.4.1 static config: LLM failover, MCP CEL authz, JWT, audit, A2A, budgets. |
| [`world/`](world/) | Seeded deterministic warehouse sim + live top-down viz. Pallet labels are the prompt-injection vector, on purpose. |
| [`robots/`](robots/) | Robot MCP servers. `Driver` interface (SimDriver now, LeRobotDriver later), in-process reflex tier, degraded-mode state machine. |
| [`agents/`](agents/) | Cognition agents + fleet orchestrator. Minimal hand-rolled A2A surface, plain OpenAI client, no frameworks. |
| [`mock-llm/`](mock-llm/) | Deterministic OpenAI-compatible backend: the CI brain and the bottom failover rung. |
| [`bench/`](bench/) | Speed harness: direct-vs-gateway latency, SLO assertion. |
| [`evals/`](evals/) | agentevals golden traces, chaos-prompt suite, trace-merge tooling. |
| [`k8s/`](k8s/) | Kustomize base + k3d/Jetson overlays + kagent fleet-sre. |
| [`docs/`](docs/) | Condensed, validated agentgateway v1.4.1 + ecosystem references. |

## Design notes & honesty

- **No real-time control through the gateway.** The reflex tier is in-process by
  design — that *is* the Speed/Safety point, not a shortcut.
- **No physics-accurate sim.** State machine + kinematic timing; ROS 2/Gazebo is future work.
- **Static JWTs, not an IdP.** Identity is in scope; a full IdP is not.
- **Small local models flub tool calling sometimes.** That's why the chaos suite judges
  escapes from *ground truth* (world state + audit log), not from what the model says,
  and why prompts are schema-constrained with bounded retries and a deterministic rung.
- **Fits on a Jetson.** arm64 images throughout; see [`k8s/setup-jetson.md`](k8s/setup-jetson.md).

## Hardware track

The punchline is the pillar table *unchanged*: swap the simulated arm for a
[LeRobot SO-101](https://huggingface.co/docs/lerobot) via a `LeRobotDriver` and the
same gateway YAML, same CEL envelope, same audit log, and same evals still apply —
only the actuator changed. Physical e-stop wiring stays hardware-side, never on the
network path.

---

*Pinned: agentgateway `v1.4.1`. See [`CLAUDE.md`](CLAUDE.md) for the full port map,
JWT identities, and pinned versions.*
