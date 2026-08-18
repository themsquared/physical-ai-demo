#!/usr/bin/env bash
# Build all service images. Default: local single-arch. --arm64 / --multiarch
# cross-build for the Jetson path; set PUSH=1 REGISTRY=... to push a manifest list.
set -euo pipefail
cd "$(dirname "$0")/.."

PLATFORM=""
case "${1:-local}" in
  --arm64)     PLATFORM="--platform linux/arm64" ;;
  --multiarch) PLATFORM="--platform linux/amd64,linux/arm64" ;;
  local|"")    PLATFORM="" ;;
  *) echo "usage: build-images.sh [local|--arm64|--multiarch]"; exit 1 ;;
esac

REGISTRY=${REGISTRY:-physical-ai-demo}
TAG=${TAG:-local}
OUT="--load"; [ "${PUSH:-0}" = "1" ] && OUT="--push"
[ -n "$PLATFORM" ] && BUILD="docker buildx build $PLATFORM $OUT" || BUILD="docker build"

declare -A images=(
  [world]=world/Dockerfile
  [robot]=robots/Dockerfile
  [agent]=agents/Dockerfile
  [mock-llm]=mock-llm/Dockerfile
  [fleet-mcp]=k8s/fleet-mcp/Dockerfile
)
for name in "${!images[@]}"; do
  echo "== building $REGISTRY/$name:$TAG (${PLATFORM:-native}) =="
  $BUILD -f "${images[$name]}" -t "$REGISTRY/$name:$TAG" .
done
echo "done."
