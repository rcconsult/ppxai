#!/usr/bin/env bash
# Deploy coder to MicroK8s cluster.
# Usage: ./deploy/microk8s/deploy.sh
#
# Prerequisites:
#   1. Create host directories:
#      sudo mkdir -p <REGISTRY_HOSTPATH>
#      sudo chown -R 1000:1000 <PV_HOSTPATH>
#
#   2. Create secrets (never stored in git):
#      cp deploy/microk8s/secrets.yaml.template deploy/microk8s/secrets.yaml
#      # Edit secrets.yaml with real API keys
#
#   3. Copy TLS secret:
#      microk8s kubectl get secret your-tls-secret -n openwebui -o yaml | \
#        sed 's/namespace: openwebui/namespace: coder/' | \
#        microk8s kubectl apply -f -
#
#   4. Build images first:
#      ./deploy/microk8s/build.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NAMESPACE="coder"

echo "==> Deploying coder to namespace '$NAMESPACE'..."

# 1. Namespace
echo "  [1/7] Namespace..."
microk8s kubectl apply -f "$SCRIPT_DIR/namespace.yaml"

# 2. RBAC
echo "  [2/7] RBAC..."
microk8s kubectl apply -f "$SCRIPT_DIR/rbac.yaml"

# 3. Storage
echo "  [3/7] Storage (PV + PVC)..."
microk8s kubectl apply -f "$SCRIPT_DIR/storage.yaml"

# 4. Secrets (only if file exists — never committed to git)
if [ -f "$SCRIPT_DIR/secrets.yaml" ]; then
  echo "  [4/7] Secrets..."
  microk8s kubectl apply -f "$SCRIPT_DIR/secrets.yaml"
else
  echo "  [4/7] Secrets — SKIPPED (no secrets.yaml found, create from secrets.yaml.template)"
fi

# 5. Server config
echo "  [5/7] Server config..."
microk8s kubectl apply -f "$SCRIPT_DIR/server-config.yaml"

# 6. Workloads
echo "  [6/7] Workloads (session-manager + login)..."
microk8s kubectl apply -f "$SCRIPT_DIR/session-manager-deployment.yaml"
microk8s kubectl apply -f "$SCRIPT_DIR/login-service.yaml"

# 7. Ingress
echo "  [7/7] Ingress..."
microk8s kubectl apply -f "$SCRIPT_DIR/ingress.yaml"

echo ""
echo "==> Deployment complete."
echo ""
echo "  Namespace:  $NAMESPACE"
echo "  Ingress:    https://coder.example.com"
echo "  Login:      https://coder.example.com/login"
echo "  API:        https://coder.example.com/api/sessions"
echo ""
echo "  Check status:"
echo "    microk8s kubectl get all -n $NAMESPACE"
echo "    microk8s kubectl get ingress -n $NAMESPACE"
