# k8s — the same demo on Kubernetes, plus the Ops-tier encore

The whole warehouse stack runs on Kubernetes from the **same images and the same
`gateway/config.yaml`** as `docker compose` — one config artifact across sim → k8s →
Jetson (Repeatability). On top of it, a **kagent `fleet-sre` agent** operates the
infrastructure that runs the robots: agents acting on real systems through a governed,
auditable tool surface — the thesis, one tier up.

## Layout

```
k8s/
├── base/              warehouse namespace: world, robots, brains, gateway,
│                      agents, otel-collector, fleet-mcp (+ scoped RBAC)
├── overlays/k3d/      Mac dev cluster        } same base, seams for
├── overlays/jetson/   Orin Nano (arm64)      } per-target pins
├── kagent/            ModelConfig + Agent(fleet-sre) + RemoteMCPServer
├── fleet-mcp/         k8s ops MCP server (pods/logs/events/restart)
└── setup-k3d.sh       one-command bring-up (cluster → images → stack → kagent → agent)
```

## Bring it up (k3d on a Mac)

```bash
bash k8s/setup-k3d.sh          # ~cluster, build/import images, apply stack, install kagent
kubectl -n warehouse get pods  # the fleet
kubectl -n kagent get agent    # fleet-sre
bash scripts/verify-kagent.sh  # the Ops encore (below)
```

`kubectl apply -k` needs `--load-restrictor LoadRestrictionsNone` here because the
gateway ConfigMap is generated from `../../gateway/config.yaml` on purpose — the k8s
deployment and the compose deployment read the **byte-identical envelope**.

## The Ops encore — `verify-kagent.sh`

1. Break `amr-2-cognition` (bad command → `CrashLoopBackOff`).
2. Ask the `fleet-sre` agent, over its A2A endpoint: *"amr-2-cognition is crashlooping,
   investigate and remediate."*
3. It calls `fleet-mcp` tools — `list_robot_pods` → `get_pod_events`/`get_pod_logs` →
   `restart_deployment` → `get_deployment_status` — diagnoses the crashloop and rolls
   the deployment.
4. The pod goes `Ready`. The agent reports what it found and did.

**The Ops-tier envelope is RBAC.** `fleet-mcp` runs under a ServiceAccount whose Role
(`k8s/base/fleet-mcp.yaml`) grants read on pods/logs/events and `patch` on deployments
in the `warehouse` namespace — nothing else, nowhere else. Same deny-by-default posture
as the robot gateway's CEL envelope, expressed in the platform's own policy language.

## Verification status (honest)

- **Statically validated in this repo:** `kubectl kustomize` renders all 20 core
  resources; every one passes `kubectl apply --dry-run=client` against a live k8s
  OpenAPI schema (RBAC, deployments, services, generated ConfigMap/Secret). kagent CRDs
  follow pinned **kagent 0.9.12 / `kagent.dev/v1alpha2`** shapes.
- **Exercised live on k3d (dev Mac):** cluster up; full warehouse stack (13 pods)
  Running; kagent 0.9.12 installed (controller + per-agent runtime); `fleet-mcp`
  deployed under its RBAC-scoped ServiceAccount; the `RemoteMCPServer` **discovered all
  5 ops tools**; the `fleet-sre` Agent reached Ready and **executed a governed tool
  against the live cluster** — `list_robot_pods` returned real pod health
  ("All robot pods healthy, phase=Running, ready=True, restarts=0"). The RBAC envelope,
  MCP tool wiring, and autonomous tool execution are proven live.
- **Model requirement (learned live):** the agent runtime only executes tools when the
  model returns **structured `tool_calls`**. Point `fleet-brain` at Ollama's OpenAI-compat
  `/v1` (not the native Ollama path, which returns tool calls as text). Verified on the
  dev host: `qwen3:4b` ✓ and `nemotron` ✓ emit structured calls; `qwen2.5-coder` and
  `qwen3:0.6b` emit text ✗. `qwen3:4b` (2.5GB, the PRD's intended primary) is the pick.
- **Environmental limit on the dev box:** the multi-step auto-remediation loop is
  memory-bound *on this specific machine* — a warm tool-calling model plus the k3d control
  plane plus two pre-existing k3d clusters exhausts the Docker VM, and cold model loads
  (~68s) exceed kagent's controller→agent timeout (warm tool calls are ~1s). On a host
  with real RAM/GPU headroom (or a Jetson with a dedicated model) the loop runs clean.
  `verify-kagent.sh` warms the model, induces a `CrashLoopBackOff`, and asks `fleet-sre`
  to remediate; it is **not** in the CI gate (CI stays on `docker compose` for speed and
  determinism). This mirrors the PRD's stance: assert on capable hardware, report elsewhere.

## Real inference on the cluster

The default brains are the deterministic `mock-edge → mock-llm` failover chain (works with
no models, no GPU). For real local inference, add an Ollama Deployment+PVC and point the
gateway's `PRIMARY_BASE_URL`/`FALLBACK_BASE_URL` (and the kagent `ModelConfig` host) at it;
on a Jetson Orin Nano use `qwen3:1.7b`. See [`setup-jetson.md`](setup-jetson.md).
