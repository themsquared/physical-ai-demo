#!/usr/bin/env bash
# Stand up the whole demo on k3d (Mac): warehouse stack + kagent fleet-sre.
# Same images, same gateway config, same CEL envelope as docker compose.
set -euo pipefail
cd "$(dirname "$0")/.."

CLUSTER=${CLUSTER:-physical-ai}
KAGENT_VERSION=${KAGENT_VERSION:-0.9.12}
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
k3d image import -c "$CLUSTER" \
  physical-ai-demo/world:local physical-ai-demo/robot:local \
  physical-ai-demo/agent:local physical-ai-demo/mock-llm:local \
  physical-ai-demo/fleet-mcp:local

echo "== 4/6 warehouse stack =="
kubectl apply -k $LOADR k8s/overlays/k3d
kubectl -n warehouse rollout status deploy/gateway --timeout=180s

echo "== 5/6 kagent (OCI Helm, pinned $KAGENT_VERSION, no default agents) =="
helm install kagent-crds oci://ghcr.io/kagent-dev/kagent/helm/kagent-crds \
  --namespace kagent --create-namespace --version "$KAGENT_VERSION" --wait
helm install kagent oci://ghcr.io/kagent-dev/kagent/helm/kagent \
  --namespace kagent --version "$KAGENT_VERSION" \
  --set providers.default=ollama \
  --set providers.ollama.model=robot-brain \
  --set providers.ollama.config.host=http://gateway.warehouse.svc.cluster.local:4000 \
  $(for a in k8s kgateway istio promql observability argo-rollouts helm \
             cilium-policy cilium-manager cilium-debug; do \
      echo --set ${a}-agent.enabled=false; done) \
  --wait

echo "== 6/6 fleet-sre agent =="
kubectl apply -k k8s/kagent

echo "done. warehouse: kubectl -n warehouse get pods ; fleet-sre: kubectl -n kagent get agent"
