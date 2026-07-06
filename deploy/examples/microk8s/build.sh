#!/usr/bin/env bash
# Build coder container images via Kaniko on MicroK8s.
# Usage: ./deploy/microk8s/build.sh [server|session-manager|all]
set -euo pipefail

NAMESPACE="coder"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET="${1:-all}"

build_server() {
  echo "==> Building coder-server image..."
  microk8s kubectl delete job build-coder-server -n "$NAMESPACE" --ignore-not-found
  microk8s kubectl apply -f "$SCRIPT_DIR/kaniko-server-job.yaml"
  echo "==> Tailing build logs (Ctrl+C to detach)..."
  microk8s kubectl wait --for=condition=ready pod -l job-name=build-coder-server -n "$NAMESPACE" --timeout=120s 2>/dev/null || true
  microk8s kubectl logs -f job/build-coder-server -n "$NAMESPACE"
}

build_session_manager() {
  echo "==> Building coder-session-manager image..."
  microk8s kubectl delete job build-coder-session-manager -n "$NAMESPACE" --ignore-not-found
  microk8s kubectl apply -f "$SCRIPT_DIR/kaniko-session-manager-job.yaml"
  echo "==> Tailing build logs (Ctrl+C to detach)..."
  microk8s kubectl wait --for=condition=ready pod -l job-name=build-coder-session-manager -n "$NAMESPACE" --timeout=120s 2>/dev/null || true
  microk8s kubectl logs -f job/build-coder-session-manager -n "$NAMESPACE"
}

case "$TARGET" in
  server)
    build_server
    ;;
  session-manager)
    build_session_manager
    ;;
  all)
    build_server
    build_session_manager
    ;;
  *)
    echo "Usage: $0 [server|session-manager|all]"
    exit 1
    ;;
esac

echo "==> Done. Images pushed to <REGISTRY_HOST>:<REGISTRY_PORT>."
