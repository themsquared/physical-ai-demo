#!/usr/bin/env bash
# Stand up the whole demo on k3d (Mac): warehouse stack + kagent fleet-sre.
# Same images, same gateway config, same CEL envelope as docker compose.
set -euo pipefail
cd "$(dirname "$0")/.."

CLUSTER=${CLUSTER:-physical-ai}
KAGENT_VERSION=${KAGENT_VERSION:-0.9.12}
FLEET_MODEL=${FLEET_MODEL:-qwen2.5-coder:14b}  # must support tool calling; served by host Ollama
LOADR="--load-restrictor LoadRestrictionsNone"  # gateway config lives outside k8s/

echo "== 1/6 JWT material =="
python scripts/gen-jwts.py gateway/jwt

echo "== 2/6 k3d cluster '$CLUSTER' =="
k3d cluster list "$CLUSTER" >/dev/null 2>&1 || k3d cluster create "$CLUSTER" \
  -p "3000:30000@loadbalancer" -p "4000:30001@loadbalancer" --wait
kubectl config use-context "k3d-$CLUSTER"

echo "== 3/6 build + import images =="
docker build -f world/Dockerfile     -t physical-ai-demo/world:local .     >/dev/null
docker build -f robots/Dockerfile    -t physical-ai-demo/robot:local .     >/dev/null
docker build -f agents/Dockerfile    -t physical-ai-demo/agent:local .     >/dev/null
docker build -f mock-llm/Dockerfile  -t physical-ai-demo/mock-llm:local .  >/dev/null
docker build -f k8s/fleet-mcp/Dockerfile -t physical-ai-demo/fleet-mcp:local . >/dev/null
# Pre-pull agentgateway so k3d imports it too (avoids in-cluster ImagePullBackOff).
docker pull ghcr.io/agentgateway/agentgateway:v1.4.1 >/dev/null
k3d image import -c "$CLUSTER" \
  physical-ai-demo/world:local physical-ai-demo/robot:local \
  physical-ai-demo/agent:local physical-ai-demo/mock-llm:local \
  physical-ai-demo/fleet-mcp:local \
  ghcr.io/agentgateway/agentgateway:v1.4.1

echo "== 4/6 warehouse stack =="
# `kubectl apply -k` doesn't take --load-restrictor; `kubectl kustomize` does.
kubectl kustomize $LOADR k8s/overlays/k3d | kubectl apply -f -
kubectl -n warehouse rollout status deploy/gateway --timeout=180s

echo "== 5/6 kagent (OCI Helm, pinned $KAGENT_VERSION, no default agents) =="
helm install kagent-crds oci://ghcr.io/kagent-dev/kagent/helm/kagent-crds \
  --namespace kagent --create-namespace --version "$KAGENT_VERSION" --wait
helm install kagent oci://ghcr.io/kagent-dev/kagent/helm/kagent \
  --namespace kagent --version "$KAGENT_VERSION" \
  --set providers.default=ollama \
  --set providers.ollama.model="$FLEET_MODEL" \
  --set providers.ollama.config.host=http://host.k3d.internal:11434 \
  $(for a in k8s kgateway istio promql observability argo-rollouts helm \
             cilium-policy cilium-manager cilium-debug; do \
      echo --set ${a}-agent.enabled=false; done) \
  --wait

echo "== 6/6 fleet-sre agent =="
kubectl apply -k k8s/kagent

echo "done. warehouse: kubectl -n warehouse get pods ; fleet-sre: kubectl -n kagent get agent"
