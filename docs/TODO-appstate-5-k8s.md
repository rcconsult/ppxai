# TODO: AppState Phase 5 — k8s Web App

**Status:** Open
**Priority:** MEDIUM — lightest phase, same app as Phase 3 + runtime config
**Depends on:** Phase 3 (Web App — proven), Phase 0 (runtime schemas)
**Target:** v1.17.2

---

## Why Last

The k8s web app is the **same app** as Phase 3 (desktop web app). The only
difference is deployment packaging and runtime configuration injection. If Phase 3
works, this phase is primarily a verification exercise.

What this phase validates:
- `state.loadRuntime('ppxai-runtime-k8s')` injects session isolation settings
- The web app reads runtime settings via the same `state.get()` interface
- The glue code (session manager, nginx BFF, ingress) works with the new AppState
- No regressions in the k8s-specific code paths

## Current State

The k8s deployment consists of:
- **Same web app** — identical `app.js`, `app-state.js`, components
- **ppxai-server** — identical server binary, different startup config (`working_dir`)
- **Session Manager** — FastAPI sidecar that creates/destroys per-user pod pairs
- **Login Service** — nginx serving login HTML form
- **Nginx BFF** — per-user webapp pod proxying to per-user server pod

The web app currently detects k8s deployment implicitly (session headers from
the server, `/api/sessions` endpoints). With runtime schemas, it will explicitly
know its deployment context.

## Implementation Steps

### Step 1: Verify runtime schema loading

The runtime schema `ppxai-runtime-k8s.schema.yaml` defines:
```yaml
fields:
  sessionIsolation: { type: boolean, default: true }
  maxSessions:      { type: integer, default: 3 }
  ttlMinutes:       { type: integer, default: 10 }
  ldapEnabled:      { type: boolean, default: false }
  registryPath:     { type: string,  default: "/registry" }
```

In the k8s deployment, the web app loads this at startup:
```javascript
// Detect k8s deployment (e.g., env var, server config endpoint, or URL path)
if (isK8sDeployment()) {
    state.loadRuntime('ppxai-runtime-k8s');
    // Now state.get('sessionIsolation') returns true
    // state.get('maxSessions') returns 3
}
```

### Step 2: Replace implicit k8s detection

Currently the web app infers k8s deployment from:
- URL path prefix `/s/<user>/` (set by ingress)
- Session headers in HTTP responses

With runtime schema, make this explicit:
```javascript
// Before: implicit
const isK8s = window.location.pathname.startsWith('/s/');

// After: explicit
const isK8s = state.get('sessionIsolation') === true;
```

### Step 3: Verify session manager integration

The session manager sidecar (`deploy/images/session-manager/main.py`) creates
pod pairs and manages sessions. It doesn't use AppState — it's infrastructure.
But verify:
- Server pods start with correct config
- Web app in container loads runtime schema
- Session isolation headers flow correctly
- Heartbeat + TTL watchdog work as before

### Step 4: Test in colima cluster

```bash
# Build images
kubectl apply -f deploy/k8s/kaniko-server-job.yaml
kubectl apply -f deploy/k8s/kaniko-webapp-job.yaml

# Deploy
helm install ppxai deploy/k8s/helm/ppxai

# Test
# 1. Login → create session → verify web app loads
# 2. Verify state.get('sessionIsolation') returns true in browser console
# 3. Chat, switch provider, tools — all work as standalone
# 4. Second user → verify session isolation
# 5. Idle timeout → verify TTL watchdog cleans up
```

## Acceptance Criteria

- [ ] `loadRuntime('ppxai-runtime-k8s')` injects all k8s-specific settings
- [ ] Web app reads runtime settings via `state.get()` — no special code paths
- [ ] Session isolation works correctly (same as before)
- [ ] Login → session create → web app flow works end-to-end
- [ ] TTL watchdog cleans up idle sessions
- [ ] Heartbeat keeps active sessions alive
- [ ] `state.snapshot()` includes both app state and runtime fields

## What NOT to Do

- Don't change the session manager — it's infrastructure, not app state
- Don't restructure the web app for k8s — it's the same app
- Don't add k8s-specific fields to the app state schema — they go in runtime schema

## Estimated Effort

~2 hours (mostly verification, minimal code changes)

## Lessons Learned

*(To be filled during/after implementation)*

### From Phases 1–4
*(Copy relevant lessons)*

### Runtime Schema Integration Issues
- ...

### k8s-Specific Deployment Notes
- ...

### Final Architecture Assessment
- What worked across all 5 phases
- What should be redesigned
- Patterns to carry forward to v1.18.x
