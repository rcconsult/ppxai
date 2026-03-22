#!/usr/bin/env bash
# Build ppxai container images via Kaniko.
# Usage: ./build.sh [server|session-manager|all] [-f VALUES_FILE] [--kubectl CMD]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET="${1:-all}"
VALUES_FILE=""
KUBECTL="kubectl"

# Parse optional flags (skip first positional arg)
shift || true
while [[ $# -gt 0 ]]; do
  case "$1" in
    -f) VALUES_FILE="$2"; shift 2 ;;
    --kubectl) KUBECTL="$2"; shift 2 ;;
    *) echo "Unknown flag: $1"; exit 1 ;;
  esac
done

# Resolve namespace from values file
NAMESPACE="ppxai-system"
if [ -n "$VALUES_FILE" ]; then
  NS=$(grep '^namespace:' "$SCRIPT_DIR/$VALUES_FILE" 2>/dev/null | awk '{print $2}' || echo "")
  [ -n "$NS" ] && NAMESPACE="$NS"
fi

# Resolve app prefix from values file
APP_PREFIX="ppxai"
if [ -n "$VALUES_FILE" ]; then
  AP=$(grep '^appPrefix:' "$SCRIPT_DIR/$VALUES_FILE" 2>/dev/null | awk '{print $2}' || echo "")
  [ -n "$AP" ] && APP_PREFIX="$AP"
fi

build_image() {
  local component="$1"
  local job_name="build-${APP_PREFIX}-${component}"

  echo "==> Building ${APP_PREFIX}-${component} image..."
  $KUBECTL delete job "$job_name" -n "$NAMESPACE" --ignore-not-found

  # Render just this job template via helm and apply
  helm template "$APP_PREFIX" "$SCRIPT_DIR" \
    ${VALUES_FILE:+-f "$SCRIPT_DIR/$VALUES_FILE"} \
    --show-only "templates/kaniko-${component}-job.yaml" \
    | $KUBECTL apply -f -

  echo "==> Tailing build logs (Ctrl+C to detach)..."
  $KUBECTL wait --for=condition=ready pod -l "job-name=$job_name" \
    -n "$NAMESPACE" --timeout=120s 2>/dev/null || true
  $KUBECTL logs -f "job/$job_name" -n "$NAMESPACE"
}

case "$TARGET" in
  server)            build_image server ;;
  session-manager)   build_image session-manager ;;
  all)               build_image server; build_image session-manager ;;
  *)                 echo "Usage: $0 [server|session-manager|all] [-f values-file.yaml] [--kubectl CMD]"; exit 1 ;;
esac

echo "==> Done. Images pushed to registry."
