# Running physical-ai-demo on a Jetson (Orin Nano 8GB, arm64)

The punchline: **the pillar table doesn't change.** Same gateway `config.yaml`, same
CEL envelope, same audit log, same evals — only the compute (and, at M10, the actuator)
is different. Everything here is arm64-native.

## Hardware

- **Jetson Orin Nano 8GB** (recommended). Runs the gateway + tiny local inference.
  The classic Nano runs the gateway + `mock-llm`/tiny models but not useful local inference.
- JetPack 6 (Ubuntu 22.04, arm64). Docker + NVIDIA container runtime preinstalled.

## Why the images just work

Every service image is pure Python (FastAPI, `mcp`, `openai`, `kubernetes`) on
`python:3.12-slim`, which is multi-arch. agentgateway ships an arm64 image
(`ghcr.io/agentgateway/agentgateway:v1.4.1`, `aarch64` — verified in the build info).
Nothing in the default path is architecture-specific.

Build arm64 images (from an amd64 laptop, or natively on the Jetson):

```bash
make images-arm64            # buildx cross-build for linux/arm64
# or natively on the Jetson, plain `docker build` produces arm64 images
```

## Option A — docker compose on the Jetson

```bash
git clone <repo> && cd physical-ai-demo
make setup
# real local inference on the Orin: qwen3:1.7b fits with headroom
ollama pull qwen3:1.7b
cat >> .env <<'EOF'
PRIMARY_MODEL=qwen3:1.7b
PRIMARY_BASE_URL=http://host.docker.internal:11434/v1
EOF
make up
make demo
```

The reflex tier and degraded-mode state machine are unchanged; on real hardware the
physical e-stop is wired **hardware-side and never on the network path** — say this out
loud in the demo.

## Option B — k3s on the Jetson

```bash
curl -sfL https://get.k3s.io | sh -    # single-node k3s, arm64
# import the arm64 images into k3s' containerd (or push to a registry the Jetson can reach)
kubectl apply -k k8s/overlays/jetson --load-restrictor LoadRestrictionsNone
```

The `jetson` overlay is intentionally identical to `base` today — the seam exists so you
can pin `nodeSelector: {kubernetes.io/arch: arm64}`, resource limits, and the smaller
model without touching the base. Add an Ollama Deployment+PVC serving `qwen3:1.7b` and
point the gateway's `PRIMARY_BASE_URL` at it.

## Models on the Jetson

| Slot | Model | Notes |
|---|---|---|
| Primary | `qwen3:1.7b` | fits Orin Nano 8GB with headroom, Apache-2.0, tool calling |
| Fallback | `qwen2.5:0.5b` | tiny rung |
| Last resort | `mock-llm` | deterministic, in-repo |

## SLOs on the Jetson

Per the PRD, pillar SLOs are **asserted** on the dev Mac + CI and **reported** (not
asserted) on the Jetson — the bench harness prints per-machine numbers:

```bash
make bench    # writes bench/results/speed.md with this board's numbers
```

The reflex tier stays 0 network hops and the gateway overhead stays small; inference
latency is the one number that moves with the hardware, which is exactly the point of
edge-first routing.
