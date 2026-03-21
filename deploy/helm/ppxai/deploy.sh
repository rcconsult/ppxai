#!/usr/bin/env bash
# Deploy ppxai via Helm.
# Usage: ./deploy.sh [-f VALUES_FILE] [--kubectl CMD] [--release NAME]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VALUES_FILE=""
KUBECTL="kubectl"
RELEASE_NAME=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    -f) VALUES_FILE="$2"; shift 2 ;;
    --kubectl) KUBECTL="$2"; shift 2 ;;
    --release) RELEASE_NAME="$2"; shift 2 ;;
    *) echo "Unknown flag: $1"; exit 1 ;;
  esac
done

# Resolve namespace from values file
NAMESPACE="ppxai-system"
if [ -n "$VALUES_FILE" ]; then
  NS=$(grep '^namespace:' "$SCRIPT_DIR/$VALUES_FILE" 2>/dev/null | awk '{print $2}' || echo "")
  [ -n "$NS" ] && NAMESPACE="$NS"
fi

# Default release name from appPrefix or namespace
if [ -z "$RELEASE_NAME" ]; then
  if [ -n "$VALUES_FILE" ]; then
    AP=$(grep '^appPrefix:' "$SCRIPT_DIR/$VALUES_FILE" 2>/dev/null | awk '{print $2}' || echo "")
    [ -n "$AP" ] && RELEASE_NAME="$AP"
  fi
  [ -z "$RELEASE_NAME" ] && RELEASE_NAME="ppxai"
fi

echo "==> Deploying ppxai to namespace '$NAMESPACE' (release: $RELEASE_NAME)..."

# Ensure namespace exists
$KUBECTL create namespace "$NAMESPACE" --dry-run=client -o yaml | $KUBECTL apply -f -

helm upgrade --install "$RELEASE_NAME" "$SCRIPT_DIR" \
  ${VALUES_FILE:+-f "$SCRIPT_DIR/$VALUES_FILE"} \
  --namespace "$NAMESPACE"

echo ""
echo "==> Deployment complete."
echo "  Namespace:  $NAMESPACE"
echo "  Release:    $RELEASE_NAME"
echo ""
echo "  Check status:"
echo "    $KUBECTL get all -n $NAMESPACE"
echo "    $KUBECTL get ingress -n $NAMESPACE"
