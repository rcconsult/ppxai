# TODO: v1.17.0 Backlog

---

## ~~ppxaide Key Bindings Cleanup~~ ✅ Done

**Implementation plan:** [`docs/TODO-keybindings-cleanup.md`](TODO-keybindings-cleanup.md)

### Problem

Key binding management in ppxaide is inconsistent and fragile:

- App-level bindings defined in `BINDINGS` in `ppxai/tui/app.py`
- Widget-level overrides scattered in `on_key()` across `ChatTextArea`, `InputBox`, `FileTree`
- Some keys consumed at widget level before reaching app bindings (discovered: `ctrl+tab`,
  `ctrl+enter` — fixed with guards, but the pattern is error-prone)
- Terminal-specific workarounds (`ctrl+enter=text:\x1b[13;5u`, `ctrl+tab=text:\x1b[9;5u`)
  leak into user's ghostty config because Textual can't negotiate Kitty protocol reliably
- No single place to see all effective bindings or reason about key routing

### Desired State

- Centralized key routing: one place decides which widget handles what, explicit pass-through
  for the rest — avoid mixing `_on_key` (priority) and `on_key` (normal) inconsistently
- `ChatTextArea` and `InputBox` should only consume keys they explicitly own; all others
  bubble up to the app unconditionally
- Ghost keys (ctrl+enter, ctrl+tab) should be handled via Textual's Kitty protocol
  negotiation (`\x1b[>1u`) rather than per-user terminal config workarounds
- Single source of truth for key bindings, ideally with a `/keys` command that shows
  the effective binding table at runtime

### Scope

- `ppxai/tui/widgets/input_box.py` — audit all `event.stop()` / `event.prevent_default()` calls
- `ppxai/tui/widgets/chat_text_area.py` — same audit
- `ppxai/tui/widgets/file_tree.py` — same audit
- `ppxai/tui/app.py` — consolidate `BINDINGS`, remove redundant widget-level overrides
- `docs/linux-terminal-setup.md` — update if ghostty keybind workaround becomes unnecessary

### Priority

Low — current state works, just messy. Address in v1.17.0 polish pass.

---

## ~~Web App: Right Panel View Framework (`RightPanelFrame`)~~

**Completed in v1.16.2** — see `docs/TODO-v1.16.2.md` Feature 11. All 5 phases done.

---

## Kubernetes Deployment POC

### Overview

Deploy ppxai as a multi-user Kubernetes application with session isolation, persistent user
workspaces, and a login-gated web app. Each user session gets a matched pod pair (webapp +
server) with dedicated PVCs. Designed to extend naturally to LDAP auth in a future release.

**Target cluster:** colima single-node k8s (k3s v1.35.0)
**Ingress host:** `ppxai.local` (add to `/etc/hosts` pointing to colima IP)

### Architecture

```
Browser
  |
  v
Nginx Ingress  (ppxai.local)
  |-- /login        --> Login Service       (shared, always running)
  |-- /api/         --> Session Manager     (shared, always running)
  |-- /s/alice/     --> ppxai-webapp-alice  (nginx BFF per user)
  |                       +-- proxies /api/, /stream/ --> ppxai-server-alice:54320
  +-- /s/bob/       --> ppxai-webapp-bob
                          +-- proxies /api/, /stream/ --> ppxai-server-bob:54320
```

### Session Lifecycle

```
1. User hits ppxai.local/login  -->  username form
2. POST /api/sessions {username}
   Session Manager:
     - active sessions >= 3?       --> 503 "Max sessions reached"
     - ppxai-ws-<user> PVC exists? --> reuse (returning user)
     - first login?                --> create ppxai-ws-<user> PVC (Retain)
   Creates:
     - ppxai-temp-<user> PVC              (Delete, every session)
     - ppxai-server-<user> Pod + Service
     - ppxai-webapp-<user> Pod + Service  (nginx, SERVER_URL injected via env)
     - Patches Ingress: /s/<user>/ --> ppxai-webapp-<user>
     - Writes /registry/<user>/meta.json
   Returns: { redirect: "/s/<user>/" }
3. Browser redirected to /s/<user>/  (username stored in cookie)
4. Webapp pod serves static ppxai web files + proxies API/SSE to server pod
5. Inactivity watchdog: 10-min TTL, deletes pod pair + temp PVC on expiry
   Workspace PVC (Retain) is never deleted automatically
```

### Pod Inventory (2 active users)

```
Always-on pods:
  login-service
  session-manager
  registry              (local image registry for Kaniko builds, registry:2)

Per-user pods (max 3 pairs = 6 ephemeral pods):
  ppxai-webapp-<user>   nginx BFF: serves web app files + proxies to server pod
  ppxai-server-<user>   ppxai-server binary, port 54320

PVCs:
  ppxai-registry        Retain, RWO  -- session-manager only, /registry/<user>/meta.json
  ppxai-ws-<user>       Retain, RWO  -- /workspace in server pod, survives session end
  ppxai-temp-<user>     Delete, RWO  -- /tmp/session in server pod, auto-deleted
```

### Storage

Two StorageClasses (both backed by local-path provisioner):

| Class | Reclaim Policy | PVC naming |
|-------|---------------|------------|
| `ppxai-ephemeral` | Delete | `ppxai-temp-<user>` |
| `ppxai-workspace` | Retain | `ppxai-ws-<user>` |

Session manager is the sole writer to the registry PVC (avoids ReadWriteMany limitation of
local-path provisioner). All session state is queried via REST from the session manager.

### Image Build (Kaniko)

- **Source:** hostPath mount of `/Users/rado/git/utils/ppxai` (colima mounts macOS home at
  same path inside VM — no copy needed)
- **Registry:** `registry:2` pod + ClusterIP service (`registry.ppxai-system.svc:5000`),
  HTTP only, Kaniko uses `--insecure` flag

| Image | Base | Contents |
|-------|------|----------|
| `ppxai-server:latest` | `python:3.12-slim` | ppxai package + server entry point |
| `ppxai-webapp:latest` | `nginx:alpine` | ppxai/web/ files + nginx.conf template + envsubst entrypoint |

Dockerfiles live in `deploy/k8s/docker/`.

### Configuration

| Resource | Mounts to | Contents |
|----------|-----------|----------|
| ConfigMap `ppxai-server-config` | ppxai-server pods | `ppxai-config.json` |
| ConfigMap `ppxai-session-manager-config` | session-manager | max_sessions, registry_path, workspace_size, temp_size, ttl_minutes |
| ConfigMap `ppxai-webapp-nginx` | ppxai-webapp pods | `nginx.conf.tmpl` (envsubst on `$PPXAI_SERVER_URL`) |
| ConfigMap `ppxai-login-config` | login-service | session_manager_url, app_title, max_sessions |
| Secret `ppxai-api-keys` | ppxai-server pods | `.env` (provider API keys) |

Pod-level env vars injected by session manager at creation time:

```
ppxai-server-<user>:  PPXAI_WORKING_DIR=/workspace  PPXAI_DATA_DIR=/tmp/session  PPXAI_USERNAME=<user>
ppxai-webapp-<user>:  PPXAI_SERVER_URL=http://ppxai-server-<user>.ppxai-system.svc:54320
```

### Session Manager API

FastAPI service with in-cluster k8s SDK. RBAC grants rights to create/delete pods, services,
PVCs and patch ingresses.

```
POST   /api/sessions            {username}  -> create session pair, return redirect URL
DELETE /api/sessions/{user}                 -> destroy pod pair + temp PVC (keep workspace)
GET    /api/sessions                        -> list active sessions + metadata
GET    /api/sessions/{user}                 -> session status + last_seen
POST   /api/sessions/{user}/heartbeat       -> update last_seen (called by webapp on SSE activity)
```

Inactivity watchdog: asyncio background task, 60-second tick, TTL = 10 minutes.

### Login Service

Standalone nginx pod serving a simple HTML username form. On submit:
1. JS sends `POST /api/sessions {username}`
2. On success (201): redirect to `redirect` URL from response
3. On 503 (max sessions): show "Server is at capacity, try again later"

### Future LDAP Path (design preserved)

| POC (v1.17.0) | LDAP (future) |
|---------------|---------------|
| Username form on login page | Nginx `auth_request` to LDAP auth proxy sidecar |
| Username from form input | `uid` claim from validated LDAP token |
| Session manager trusts submitted username | Session manager receives username from verified identity |
| Workspace PVC `ppxai-ws-<user>` | Same PVC, re-bound by same `uid` — workspace survives auth migration |

LDAP adds only an auth layer at Nginx. Everything downstream (pod pairs, PVC binding, registry)
is unchanged.

### Helm Chart Layout

```
deploy/k8s/
  helm/ppxai/
    Chart.yaml
    values.yaml                        # max_sessions, storage sizes, ingress host, TTL
    templates/
      namespace.yaml
      storageclass-ephemeral.yaml
      storageclass-workspace.yaml
      registry-deployment.yaml
      registry-service.yaml
      kaniko-server-job.yaml
      kaniko-webapp-job.yaml
      session-manager-deployment.yaml
      session-manager-service.yaml
      session-manager-configmap.yaml
      session-manager-rbac.yaml
      session-manager-pvc.yaml
      login-service-deployment.yaml
      login-service-service.yaml
      login-service-configmap.yaml
      ingress.yaml
      api-keys-secret.yaml             # values only, never checked in
      server-configmap.yaml
      webapp-nginx-configmap.yaml
  docker/
    Dockerfile.server
    Dockerfile.webapp
  session-manager/
    main.py                            # FastAPI app + k8s SDK + watchdog
    requirements.txt
```

### Implementation Checklist

#### Phase 1 — Cluster Foundations
- [ ] Add `ppxai.local` to `/etc/hosts` pointing to colima IP
- [ ] Create `ppxai-system` namespace
- [ ] Deploy `registry:2` pod + ClusterIP service
- [ ] Create StorageClass `ppxai-ephemeral` (Delete, local-path)
- [ ] Create StorageClass `ppxai-workspace` (Retain, local-path)
- [ ] Create `ppxai-registry` PVC (Retain, RWO, for session manager)

#### Phase 2 — Build Images
- [ ] Write `deploy/k8s/docker/Dockerfile.server`
- [ ] Write `deploy/k8s/docker/Dockerfile.webapp` (nginx + web files + envsubst)
- [ ] Write Kaniko Job YAML for server image (hostPath source)
- [ ] Write Kaniko Job YAML for webapp image (hostPath source)
- [ ] Run Kaniko jobs, verify images in local registry

#### Phase 3 — Session Manager
- [ ] Write session manager FastAPI app (`deploy/k8s/session-manager/main.py`)
- [ ] RBAC: ServiceAccount + ClusterRole + ClusterRoleBinding
- [ ] ConfigMap `ppxai-session-manager-config`
- [ ] Deployment + Service YAML
- [ ] Inactivity watchdog (10-min TTL, 60-second tick)
- [ ] Heartbeat endpoint

#### Phase 4 — Login Service
- [ ] Login HTML form (username input, no-auth for POC)
- [ ] JS: POST to session manager, redirect on success, error message on 503
- [ ] nginx container serving login page
- [ ] ConfigMap + Deployment + Service YAML

#### Phase 5 — Nginx Ingress
- [ ] Install nginx-ingress-controller in colima cluster
- [ ] Base Ingress resource with `/login` and `/api/` routes
- [ ] Session manager patches Ingress dynamically on session create/delete

#### Phase 6 — ConfigMaps and Secrets
- [ ] `ppxai-server-config` ConfigMap (`ppxai-config.json`)
- [ ] `ppxai-api-keys` Secret (`.env`)
- [ ] `ppxai-webapp-nginx` ConfigMap (`nginx.conf.tmpl`)

#### Phase 7 — Helm Chart
- [ ] Wrap all manifests in Helm chart under `deploy/k8s/helm/ppxai/`
- [ ] `values.yaml` with: max_sessions=3, ttl_minutes=10, storage sizes, ingress_host=ppxai.local
- [ ] README for chart installation

#### Phase 8 — Integration Test
- [ ] Deploy: `helm install ppxai deploy/k8s/helm/ppxai`
- [ ] Test login → session creation → web app usage
- [ ] Test 3 concurrent sessions
- [ ] Test 4th session rejected with clear error message
- [ ] Test idle timeout: session auto-destroyed after 10 min
- [ ] Test workspace PVC persists across logout/login
- [ ] Verify temp PVC deleted after session ends
