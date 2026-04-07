#!/usr/bin/env bash
# Deploy ppxai via Helm.
# Usage: ./deploy.sh [-f VALUES_FILE] [--kubectl CMD] [--release NAME]
#
# Handles:
#   - Namespace pre-creation (decoupled from Helm lifecycle)
#   - Reflector-synced secrets (LDAP, TLS) with retry
#   - Manually-managed API key secret (copied from vllm namespace)
#   - Helm install/upgrade with --force to avoid field-manager conflicts
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

# Resolve namespace labels from values file
NS_LABELS=""
if [ -n "$VALUES_FILE" ]; then
  ENV_LABEL=$(python3 -c "
import yaml, sys
with open('$SCRIPT_DIR/$VALUES_FILE') as f:
    v = yaml.safe_load(f)
labels = v.get('namespaceLabels', {})
for k, val in labels.items():
    print(f'{k}={val}')
" 2>/dev/null || echo "")
  [ -n "$ENV_LABEL" ] && NS_LABELS="$ENV_LABEL"
fi

# =========================================================================
# Step 1: Ensure namespace exists (decoupled from Helm lifecycle)
# =========================================================================
echo "==> Ensuring namespace '$NAMESPACE' exists..."
if $KUBECTL get namespace "$NAMESPACE" &>/dev/null; then
  echo "    Namespace exists, ensuring Helm labels..."
else
  echo "    Creating namespace..."
  $KUBECTL create namespace "$NAMESPACE"
fi

# Always ensure Helm ownership labels (required for helm install to adopt it)
$KUBECTL label namespace "$NAMESPACE" \
  app.kubernetes.io/managed-by=Helm \
  --overwrite &>/dev/null
$KUBECTL annotate namespace "$NAMESPACE" \
  meta.helm.sh/release-name="$RELEASE_NAME" \
  meta.helm.sh/release-namespace="$NAMESPACE" \
  --overwrite &>/dev/null

# Apply extra labels from values
if [ -n "$NS_LABELS" ]; then
  while IFS= read -r label; do
    [ -n "$label" ] && $KUBECTL label namespace "$NAMESPACE" "$label" --overwrite &>/dev/null
  done <<< "$NS_LABELS"
fi

# =========================================================================
# Step 2: Ensure external secrets exist (Reflector + manual)
# =========================================================================
echo "==> Checking external secrets..."

# --- Reflector-synced secrets ---
wait_for_secret() {
  local secret_name="$1"
  local source_ns="${2:-openwebui}"
  local max_wait=30

  if $KUBECTL get secret "$secret_name" -n "$NAMESPACE" &>/dev/null; then
    echo "    ✓ $secret_name (exists)"
    return 0
  fi

  echo "    ⏳ $secret_name — waiting for Reflector sync..."

  # Toggle the annotation to trigger re-sync
  local current_ns
  current_ns=$($KUBECTL get secret "$secret_name" -n "$source_ns" \
    -o jsonpath='{.metadata.annotations.reflector\.v1\.k8s\.emberstack\.com/reflection-auto-namespaces}' 2>/dev/null || echo "")
  if [ -n "$current_ns" ]; then
    # Remove target namespace, wait, re-add — forces Reflector to notice
    local without_ns
    without_ns=$(echo "$current_ns" | sed "s/,${NAMESPACE}//;s/${NAMESPACE},//;s/${NAMESPACE}//")
    $KUBECTL annotate secret "$secret_name" -n "$source_ns" \
      reflector.v1.k8s.emberstack.com/reflection-auto-namespaces="$without_ns" --overwrite &>/dev/null || true
    sleep 2
    $KUBECTL annotate secret "$secret_name" -n "$source_ns" \
      reflector.v1.k8s.emberstack.com/reflection-auto-namespaces="$current_ns" --overwrite &>/dev/null || true
  fi

  for i in $(seq 1 "$max_wait"); do
    if $KUBECTL get secret "$secret_name" -n "$NAMESPACE" &>/dev/null; then
      echo "    ✓ $secret_name (synced after ${i}s)"
      return 0
    fi
    sleep 1
  done

  echo "    ✗ $secret_name — NOT synced after ${max_wait}s (pods may fail until it appears)"
  return 1
}

# --- API key secret (copied from vllm namespace) ---
ensure_api_keys() {
  local secret_name="$1"
  local source_ns="${2:-vllm}"
  local source_secret="${3:-vllm-api-key}"
  local source_key="${4:-api-key}"

  if $KUBECTL get secret "$secret_name" -n "$NAMESPACE" &>/dev/null; then
    echo "    ✓ $secret_name (exists)"
    return 0
  fi

  echo "    ⏳ $secret_name — creating from $source_ns/$source_secret..."
  local api_key
  api_key=$($KUBECTL get secret "$source_secret" -n "$source_ns" \
    -o jsonpath="{.data.${source_key}}" 2>/dev/null | base64 -d)

  if [ -z "$api_key" ]; then
    echo "    ✗ $secret_name — source secret $source_ns/$source_secret not found"
    return 1
  fi

  $KUBECTL create secret generic "$secret_name" -n "$NAMESPACE" \
    --from-literal=VLLM_API_KEY="$api_key"
  echo "    ✓ $secret_name (created from $source_ns/$source_secret)"
}

# Resolve secret names and Reflector config from values file
API_KEY_SECRET=""
REFLECTOR_SECRETS=""
if [ -n "$VALUES_FILE" ]; then
  eval "$(python3 -c "
import yaml
with open('$SCRIPT_DIR/$VALUES_FILE') as f:
    v = yaml.safe_load(f)
ak = v.get('apiKeys', {})
if not ak.get('create', True):
    print(f'API_KEY_SECRET={ak.get(\"existingSecret\", \"\")}')
# Reflector secrets: LDAP + TLS (read from values, not hardcoded)
auth = v.get('auth', {})
ldap = auth.get('ldap', {})
ldap_secret = ldap.get('existingSecret', '')
if ldap_secret:
    print(f'LDAP_SECRET={ldap_secret}')
ingress = v.get('ingress', {}).get('tls', {})
tls_secret = ingress.get('secretName', '')
if tls_secret:
    print(f'TLS_SECRET={tls_secret}')
" 2>/dev/null || echo "")"
fi

# Wait for Reflector-synced secrets (best-effort — don't block deploy on these)
[ -n "${LDAP_SECRET:-}" ] && wait_for_secret "$LDAP_SECRET" "openwebui" || true
[ -n "${TLS_SECRET:-}" ] && wait_for_secret "$TLS_SECRET" "openwebui" || true

# Ensure API key secret (copied from source namespace)
if [ -n "${API_KEY_SECRET:-}" ]; then
  ensure_api_keys "$API_KEY_SECRET" "vllm" "vllm-api-key" "api-key" || true
fi

# =========================================================================
# Step 3: Helm install/upgrade
# =========================================================================
echo ""
echo "==> Deploying ppxai to namespace '$NAMESPACE' (release: $RELEASE_NAME)..."

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
