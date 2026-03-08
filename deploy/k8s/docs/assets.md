# ppxai Kubernetes Assets

Every resource deployed by the ppxai k8s POC and what it does.

---

## Storage

**`storageclass-workspace.yaml`** — `ppxai-workspace` StorageClass
Backed by `local-path` provisioner, `reclaimPolicy: Retain`. Used for per-user `/workspace` PVCs. Files survive session teardown — the next time the same user logs in, their workspace is reattached.

**`storageclass-ephemeral.yaml`** — `ppxai-ephemeral` StorageClass
Same provisioner, `reclaimPolicy: Delete`. Used for per-user `/tmp/session` PVCs. Wiped automatically when the session ends.

**`session-manager-pvc.yaml`** — `ppxai-registry` PVC (5Gi, Retain)
Mounted at `/registry` in the session manager pod. Stores per-user metadata files (`/registry/<username>/meta.json`) — the source of truth for active sessions. Survives session manager restarts.

---

## Image Registry

**`registry-deployment.yaml`** — Docker Registry v2 pod
Runs `registry:2` inside the cluster. Kaniko pushes built images here; session manager pods pull from it. No auth (internal-only).

**`registry-service.yaml`** — ClusterIP `:5000` named `registry`
Makes the registry reachable as `registry.ppxai-system.svc:5000` from within the cluster (Kaniko jobs use this). Docker on the colima VM reaches it via pod IP (ClusterIP is not routable from the Docker daemon network namespace).

---

## Build Jobs (one-shot)

**`kaniko-server-job.yaml`** — Builds `ppxai-server:latest`
Kaniko reads the repo from a host-path volume (the git checkout mounted into the VM), runs `Dockerfile.server`, and pushes to the in-cluster registry. Has an init container that waits for the registry to be reachable before starting.

**`kaniko-session-manager-job.yaml`** — Builds `ppxai-session-manager:latest`
Same pattern. Builds `deploy/k8s/session-manager/Dockerfile` — a minimal FastAPI app image.

---

## Session Manager

**`session-manager-rbac.yaml`** — ServiceAccount + ClusterRole + ClusterRoleBinding
Grants the session manager pod permission to: get/list/create/delete pods, services, PVCs; get/list/create/update/patch/delete ingresses; get/list configmaps and secrets.

**`session-manager-deployment.yaml`** — 1-replica Deployment
Runs the FastAPI session manager. Mounts the registry PVC. Env vars: `NAMESPACE`, `MAX_SESSIONS`, `TTL_MINUTES`, `SERVER_IMAGE`, `INGRESS_HOST`, etc.

**`session-manager-service.yaml`** — ClusterIP `:8080` named `session-manager`
Exposes the session manager API internally and to the nginx ingress (for `/api/*` routes).

---

## Server Config

**`server-config.yaml`** — two resources:

- **ConfigMap `ppxai-server-config`**: Contains `ppxai-config.json` with provider definitions (perplexity, gemini, openai) using `api_key_env` references. Mounted read-only into every server pod at `/root/.ppxai/ppxai-config.json`.
- **Secret `ppxai-api-keys`**: Holds `PERPLEXITY_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `CUSTOM_API_KEY`, `CUSTOM_BASE_URL`. Injected as env vars into every server pod via `secretKeyRef`.

---

## Login Service

**`login-service.yaml`** — three resources:

- **ConfigMap `login-page`**: The full `index.html` — a self-contained HTML/CSS/JS login form with no external dependencies. JS posts `{username}` to `POST /api/sessions`, then redirects to `data.path` on 201 or shows an error on 503/400.
- **Deployment `login`**: nginx:1.27-alpine serving the ConfigMap HTML via a tmpfs volume.
- **Service `login`**: ClusterIP `:80`, targeted by the `/login` ingress rule.

---

## Ingress

**`base-ingress.yaml`** — `ppxai-ingress` (Helm-managed, static)
nginx ingress with two permanent rules:
- `/api(/|$)(.*)` → `session-manager:8080`
- `/login(/|$)(.*)` → `login:80`

Annotations: `rewrite-target=/$2`, `proxy-buffering=off` (SSE), `proxy-read-timeout=3600`.

**`ppxai-sessions-ingress`** (runtime, owned by session manager — not a Helm template)
Created lazily by the session manager when the first session starts. Deleted when the last session ends. Contains one rule per active user: `/s/<username>(/|$)(.*)` → `ppxai-svc-<username>:54320`. Patched (not replaced) on every session create/delete.

---

## Per-Session Resources (created at runtime by session manager)

These are not Helm templates — the session manager creates them dynamically via the k8s API:

| Resource | Name pattern | Purpose |
|----------|--------------|---------|
| PVC | `ppxai-ws-<user>` | `/workspace` — persistent, Retain |
| PVC | `ppxai-tmp-<user>` | `/tmp/session` — ephemeral, Delete |
| Pod | `ppxai-server-<user>` | ppxai HTTP server, port 54320 |
| Service | `ppxai-svc-<user>` | ClusterIP targeting the server pod |
| Ingress rule | `/s/<user>` | Added to `ppxai-sessions-ingress` |

---

## Docker Images

**`deploy/k8s/docker/Dockerfile.server`**
Two-stage build: builder installs `ppxai[server,search]` into a venv, runtime copies the venv + web UI files + AGENTS.md (baked at `/root/.ppxai/AGENTS.md`). Runs as root (required for local-path PVC permission compatibility).

**`deploy/k8s/session-manager/Dockerfile`**
python:3.12-slim, installs `requirements.txt` (fastapi, uvicorn, kubernetes, pydantic), runs `uvicorn main:app` on `:8080`.

---

## Namespace

All resources live in `ppxai-system`. The namespace and its Helm annotations are managed by the chart (`namespace.yaml`).
