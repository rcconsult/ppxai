# ppxai Helm Chart

Unified chart for deploying the ppxai multi-user AI assistant on Kubernetes.

## Environments

| Environment | Auth | TLS | Registry | Values file |
|-------------|------|-----|----------|-------------|
| **colima** (macOS dev) | stub | no | in-chart | `values-colima.yaml` |
| **microk8s** (corporate) | LDAP | yes | external addon | `values-microk8s.yaml` |

## Quick Start

```bash
# Dev (colima)
helm upgrade --install ppxai . -f values-colima.yaml

# Corporate (microk8s)
cp values-microk8s.yaml.example values-microk8s.yaml
# Edit values-microk8s.yaml with real IPs/hostnames/LDAP details
helm upgrade --install coder . -f values-microk8s.yaml -n coder

# Or use the wrapper scripts:
./deploy.sh -f values-microk8s.yaml
./build.sh all -f values-microk8s.yaml
```

## Building Images

```bash
# Build both images
./build.sh all -f values-microk8s.yaml

# Build only server
./build.sh server -f values-microk8s.yaml

# Build only session-manager
./build.sh session-manager -f values-microk8s.yaml

# MicroK8s
./build.sh all -f values-microk8s.yaml --kubectl "microk8s kubectl"
```

## Feature Gates

| Gate | Default | Effect |
|------|---------|--------|
| `auth.mode` | stub | `ldap` enables password field + LDAP env vars |
| `registry.external` | false | `true` skips in-chart registry deployment |
| `ingress.tls.enabled` | false | `true` adds TLS + force-ssl-redirect |
| `storageClass.create` | true | `false` reuses pre-existing StorageClasses |
| `storage.staticPv.enabled` | false | `true` creates static PV for registry |
| `resources.enabled` | false | `true` adds CPU/memory requests+limits |
| `monitoring.enabled` | false | `true` adds Prometheus scrape annotations |

## Secrets

API keys are managed via the `apiKeys` values section. Override on the command line:

```bash
helm upgrade --install coder . -f values-microk8s.yaml \
  --set apiKeys.keys.VLLM_API_KEY=your-real-key
```

Or use an existing secret:

```yaml
apiKeys:
  create: false
  existingSecret: my-api-keys
```
