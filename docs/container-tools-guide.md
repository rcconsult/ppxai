# Container & Kubernetes Tools User Guide

**Version:** v1.13.10
**Last Updated:** 2026-01-14

This guide covers ppxai's built-in tools for managing Docker, Podman, and Kubernetes resources through natural language commands.

---

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Configuration](#configuration)
4. [Docker/Podman Tools](#dockerpodman-tools)
5. [Kubernetes Tools](#kubernetes-tools)
6. [Security & Consent](#security--consent)
7. [Troubleshooting](#troubleshooting)
8. [Examples](#examples)

---

## Overview

Both **ppxai** (Rich TUI) and **ppxaide** (Textual TUI) provide 16 container management tools that allow AI models to inspect and manage containers and Kubernetes resources on your behalf. These tools:

- Use CLI wrappers (no external SDKs required)
- Work with Docker, Podman, and kubectl
- Require explicit user consent for destructive operations
- Auto-detect available runtimes

### Tool Summary

| Category | Tools | Count |
|----------|-------|-------|
| Docker/Podman | `container_list`, `container_logs`, `container_inspect`, `container_start`, `container_stop`, `container_restart`, `container_exec`, `image_list` | 8 |
| Kubernetes | `pod_list`, `pod_logs`, `pod_describe`, `pod_exec`, `deployment_list`, `service_list`, `kubectl_apply`, `namespace_list` | 8 |

---

## Prerequisites

### For Docker

1. **Install Docker Desktop** (macOS/Windows) or **Docker Engine** (Linux):
   ```bash
   # macOS (Homebrew)
   brew install --cask docker

   # Ubuntu/Debian
   sudo apt-get update
   sudo apt-get install docker-ce docker-ce-cli containerd.io

   # Windows (winget)
   winget install Docker.DockerDesktop
   ```

2. **Start Docker daemon:**
   - macOS/Windows: Start Docker Desktop
   - Linux: `sudo systemctl start docker`

3. **Verify installation:**
   ```bash
   docker version
   docker ps
   ```

4. **Linux permissions** (add user to docker group):
   ```bash
   sudo usermod -aG docker $USER
   # Log out and back in
   ```

### For Podman

1. **Install Podman:**
   ```bash
   # macOS
   brew install podman
   podman machine init
   podman machine start

   # Ubuntu/Debian
   sudo apt-get install podman

   # Fedora/RHEL
   sudo dnf install podman
   ```

2. **Verify installation:**
   ```bash
   podman version
   podman ps
   ```

### For Kubernetes

1. **Install kubectl:**
   ```bash
   # macOS
   brew install kubectl

   # Ubuntu/Debian
   sudo apt-get install kubectl

   # Windows
   winget install Kubernetes.kubectl
   ```

2. **Configure cluster access:**
   ```bash
   # Copy kubeconfig from your cluster
   mkdir -p ~/.kube
   cp /path/to/kubeconfig ~/.kube/config

   # Or use cloud provider CLI
   aws eks update-kubeconfig --name my-cluster     # AWS EKS
   gcloud container clusters get-credentials my-cluster  # GKE
   az aks get-credentials --name my-cluster        # AKS
   ```

3. **Verify access:**
   ```bash
   kubectl cluster-info
   kubectl get nodes
   kubectl auth can-i list pods
   ```

### Access Requirements Summary

| Runtime | Socket/Config | Permissions |
|---------|--------------|-------------|
| Docker | `/var/run/docker.sock` | User in `docker` group or root |
| Podman | User-level (rootless) | No special permissions |
| kubectl | `~/.kube/config` or `KUBECONFIG` | Valid cluster credentials |

---

## Configuration

### Container Tools Are Not Currently Configurable

Container tools are always enabled (registration is automatic when a runtime
is detected) and are **not** configurable via `ppxai-config.json` today:

- **Runtime selection** is always auto-detected: `detect_container_runtime()`
  (`ppxai/engine/tools/builtin/container.py`) checks for `docker` in PATH
  first, then falls back to `podman`. There is no way to force one or the
  other.
- **Timeouts are fixed per-tool** in code (e.g. 30s for list/inspect
  operations, 60s for logs) and cannot be overridden from config.
- **Consent is always required** for destructive operations (start, stop,
  restart, exec, `kubectl apply`, `pod_exec`) — it cannot be disabled.

`ppxai-config.json` does accept a `tools.container` block with `enabled`,
`require_consent`, `default_runtime`, and `timeout` keys, but these are
**reserved and not yet wired up** — `get_container_config()`
(`ppxai/config/tools.py`) parses them, but nothing in
`ppxai/engine/tools/builtin/container.py` reads the parsed result. Setting
any of these keys today has **zero effect**.

### Runtime Auto-Detection

1. Checks for `docker` in PATH first
2. Falls back to `podman` if Docker not found
3. Tools are not registered if neither is found

### Tool Description Overrides

Customize tool descriptions for specific models:

```json
{
  "tools": {
    "overrides": {
      "container_list": "List Docker containers"
    },
    "model_overrides": {
      "qwen2.5-coder:0.5b": {
        "container_list": "List containers"
      }
    }
  }
}
```

---

## Docker/Podman Tools

### container_list

List running or all containers.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `all` | boolean | No | Include stopped containers |
| `filter` | string | No | Filter expression |

**Filter Examples:**
- `name=web` - Containers with "web" in name
- `status=running` - Only running containers
- `status=exited` - Only stopped containers
- `ancestor=nginx` - Containers from nginx image

**Usage:**
```
User: Show me all my containers including stopped ones
AI: [Uses container_list with all=true]

User: List containers running the nginx image
AI: [Uses container_list with filter="ancestor=nginx"]
```

---

### container_logs

Retrieve logs from a container.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `container` | string | **Yes** | Container name or ID |
| `tail` | integer | No | Lines from end (default: 100) |
| `since` | string | No | Time filter (e.g., `10m`, `1h`, `2024-01-01`) |

**Usage:**
```
User: Show me the last 50 lines of logs from my web container
AI: [Uses container_logs with container="web", tail=50]

User: Get logs from the api container for the last hour
AI: [Uses container_logs with container="api", since="1h"]
```

---

### container_inspect

Get detailed container information.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `container` | string | **Yes** | Container name or ID |
| `format` | string | No | Go template for output |

**Format Examples:**
- `{{.NetworkSettings.IPAddress}}` - Container IP
- `{{.Config.Env}}` - Environment variables
- `{{.Mounts}}` - Volume mounts
- `{{.State.Status}}` - Container status

**Usage:**
```
User: What's the IP address of my database container?
AI: [Uses container_inspect with container="db", format="{{.NetworkSettings.IPAddress}}"]

User: Show me the environment variables in the api container
AI: [Uses container_inspect with container="api", format="{{.Config.Env}}"]
```

---

### container_start / container_stop / container_restart

Control container state. **Requires user consent.**

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `container` | string | **Yes** | Container name or ID |

**Usage:**
```
User: Start my web container
AI: [Requests consent] "Allow: docker start web"
User: [Approves]
AI: [Uses container_start with container="web"]
```

---

### container_exec

Execute a command inside a running container. **Requires user consent.**

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `container` | string | **Yes** | Container name or ID |
| `command` | string | **Yes** | Command to execute |
| `workdir` | string | No | Working directory inside container |

**Usage:**
```
User: List files in the /app directory of my web container
AI: [Requests consent] "Allow: docker exec web ls -la /app"
User: [Approves]
AI: [Uses container_exec with container="web", command="ls -la /app"]

User: Check the nginx config in my proxy container
AI: [Requests consent] "Allow: docker exec proxy cat /etc/nginx/nginx.conf"
```

---

### image_list

List container images.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `all` | boolean | No | Include intermediate images |
| `filter` | string | No | Filter by reference |

**Filter Examples:**
- `reference=nginx*` - Images starting with "nginx"
- `dangling=true` - Untagged images

**Usage:**
```
User: What images do I have locally?
AI: [Uses image_list]

User: Show me all nginx-related images
AI: [Uses image_list with filter="reference=nginx*"]
```

---

## Kubernetes Tools

### pod_list

List pods in a namespace or cluster-wide.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `namespace` | string | No | Target namespace |
| `all_namespaces` | boolean | No | List across all namespaces |
| `selector` | string | No | Label selector |

**Selector Examples:**
- `app=nginx` - Pods with label app=nginx
- `environment=production` - Production pods
- `app=web,tier=frontend` - Multiple labels

**Usage:**
```
User: List all pods in the production namespace
AI: [Uses pod_list with namespace="production"]

User: Show me all nginx pods across all namespaces
AI: [Uses pod_list with all_namespaces=true, selector="app=nginx"]
```

---

### pod_logs

Retrieve logs from a pod.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `pod` | string | **Yes** | Pod name |
| `namespace` | string | No | Namespace |
| `container` | string | No | Container (for multi-container pods) |
| `tail` | integer | No | Lines from end (default: 100) |
| `previous` | boolean | No | Logs from previous instance |

**Usage:**
```
User: Get logs from the api-deployment-xxx pod in staging
AI: [Uses pod_logs with pod="api-deployment-xxx", namespace="staging"]

User: Show me logs from the crashed instance of my web pod
AI: [Uses pod_logs with pod="web-xxx", previous=true]

User: Get logs from the sidecar container in my pod
AI: [Uses pod_logs with pod="my-pod", container="sidecar"]
```

---

### pod_describe

Get detailed pod information including events.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `pod` | string | **Yes** | Pod name |
| `namespace` | string | No | Namespace |

**Usage:**
```
User: Why is my api pod failing to start?
AI: [Uses pod_describe with pod="api-xxx", namespace="production"]
```

---

### pod_exec

Execute a command inside a pod. **Requires user consent.**

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `pod` | string | **Yes** | Pod name |
| `command` | string | **Yes** | Command to execute |
| `namespace` | string | No | Namespace |
| `container` | string | No | Container (for multi-container pods) |

**Usage:**
```
User: Check the environment variables in the api pod
AI: [Requests consent] "Allow: kubectl exec api-xxx -- env"
User: [Approves]
AI: [Uses pod_exec with pod="api-xxx", command="env"]
```

---

### deployment_list

List Kubernetes deployments.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `namespace` | string | No | Target namespace |
| `all_namespaces` | boolean | No | List across all namespaces |

**Usage:**
```
User: What deployments are running in production?
AI: [Uses deployment_list with namespace="production"]
```

---

### service_list

List Kubernetes services.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `namespace` | string | No | Target namespace |
| `all_namespaces` | boolean | No | List across all namespaces |

**Usage:**
```
User: Show me all services in the cluster
AI: [Uses service_list with all_namespaces=true]
```

---

### kubectl_apply

Apply a Kubernetes manifest. **Requires user consent.**

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `file` | string | **Yes** | Path to manifest file |
| `namespace` | string | No | Target namespace |
| `dry_run` | boolean | No | Validate without applying |

**Usage:**
```
User: Apply my deployment manifest
AI: [Requests consent] "Allow: kubectl apply -f deployment.yaml"
User: [Approves]
AI: [Uses kubectl_apply with file="deployment.yaml"]

User: Validate my config without applying it
AI: [Requests consent] "Allow: kubectl apply -f config.yaml --dry-run=client"
User: [Approves]
AI: [Uses kubectl_apply with file="config.yaml", dry_run=true]
```

---

### namespace_list

List all namespaces.

**Parameters:** None

**Usage:**
```
User: What namespaces exist in the cluster?
AI: [Uses namespace_list]
```

---

## Security & Consent

### Tools Requiring Consent

The following tools modify state and require explicit user approval:

| Tool | Action |
|------|--------|
| `container_start` | Start a stopped container |
| `container_stop` | Stop a running container |
| `container_restart` | Restart a container |
| `container_exec` | Execute command in container |
| `kubectl_apply` | Apply Kubernetes manifest |
| `pod_exec` | Execute command in pod |

### Consent Workflow

1. AI requests permission showing the exact command
2. User sees prompt: `Allow: docker exec web ls -la`
3. User can: **Allow**, **Deny**, **Always Allow**, or **Never Allow**
4. Session-level preferences are remembered

### Disabling Consent

Not currently possible. Consent for destructive operations
(`container_start`, `container_stop`, `container_restart`, `container_exec`,
`kubectl_apply`, `pod_exec`) is unconditional in code — the
`tools.container.require_consent` config key is reserved but not read by
`ppxai/engine/tools/builtin/container.py`. See [Configuration](#configuration).

---

## Troubleshooting

### "Error: No container runtime found"

**Cause:** Neither Docker nor Podman is installed or in PATH.

**Solution:**
```bash
# Check if docker/podman is in PATH
which docker
which podman

# If installed but not in PATH, add to ~/.bashrc or ~/.zshrc
export PATH="$PATH:/usr/local/bin"
```

### "Error: kubectl not found"

**Cause:** kubectl is not installed or in PATH.

**Solution:**
```bash
# Install kubectl
brew install kubectl  # macOS
sudo apt install kubectl  # Ubuntu

# Verify
kubectl version --client
```

### "permission denied while trying to connect to Docker daemon"

**Cause:** User not in docker group (Linux).

**Solution:**
```bash
sudo usermod -aG docker $USER
# Log out and back in
```

### "Unable to connect to the server"

**Cause:** Invalid kubeconfig or cluster unreachable.

**Solution:**
```bash
# Check current context
kubectl config current-context

# List available contexts
kubectl config get-contexts

# Switch context
kubectl config use-context my-cluster

# Test connectivity
kubectl cluster-info
```

### Tools Not Appearing

**Cause:** Container tools not enabled or runtime not detected.

**Solution:**
1. Enable tools in ppxai: `/tools on`
2. Check if tools registered: `/tools list`
3. Verify runtime: `docker version` or `kubectl version`

### Timeout Errors

**Cause:** Command taking longer than the fixed per-tool timeout (e.g. 30s
for list/inspect, 60s for logs — see [Configuration](#configuration)).

**Solution:** Timeouts are not currently configurable. Reduce the scope of
the command (e.g. `tail` fewer log lines) or run it directly via the shell
CLI wrapper instead.

---

## Examples

### Debug a Crashing Pod

```
User: My api pod keeps crashing. Help me debug it.

AI: Let me check the pod status and recent events.
[Uses pod_describe with pod="api-xxx", namespace="production"]

The pod is in CrashLoopBackOff. Let me check the logs from the crashed instance.
[Uses pod_logs with pod="api-xxx", namespace="production", previous=true]

I can see the error: "FATAL: database connection refused".
Let me verify the database service is running.
[Uses service_list with namespace="production"]
```

### Monitor Container Health

```
User: Show me the status of all my containers and their resource usage.

AI: [Uses container_list with all=true]

Here are your containers:
- web (running) - Up 2 days
- api (running) - Up 2 days
- db (running) - Up 5 days
- cache (exited) - Exited (137) 3 hours ago

The cache container has stopped. Would you like me to check its logs?
```

### Deploy to Kubernetes

```
User: Deploy my new configuration to the staging namespace.

AI: Let me first validate the manifest.
[Requests consent] "Allow: kubectl apply -f app.yaml --dry-run=client"
User: [Approves]
[Uses kubectl_apply with file="app.yaml", namespace="staging", dry_run=true]

Validation passed. Ready to apply. Shall I proceed with the actual deployment?

User: Yes, go ahead.

AI: [Requests consent] "Allow: kubectl apply -f app.yaml -n staging"
User: [Approves]
[Uses kubectl_apply with file="app.yaml", namespace="staging"]

Deployment successful. Let me verify the pods are starting.
[Uses pod_list with namespace="staging", selector="app=myapp"]
```

---

## What's Not Supported

The following operations are **not** available through ppxai tools:

- **Image build** (`docker build`)
- **Image push/pull** (`docker push`, `docker pull`)
- **Registry authentication** (`docker login`)
- **Container creation** (`docker run`, `docker create`)
- **Volume management** (`docker volume`)
- **Network management** (`docker network`)
- **Kubernetes scaling** (`kubectl scale`)
- **Kubernetes rollout** (`kubectl rollout`)

These require direct CLI access or custom tools.

---

## Related Documentation

- [TECHNICAL_DEBT.md](archive/v1.15.1-completed/TECHNICAL_DEBT.md) - Known issues and refactoring plans
- [RELEASE-NOTES-v1.13.8.md](archive/release-notes/RELEASE-NOTES-v1.13.8.md) - Initial container tools release
- [README.md](README.md) - Tool reference table
