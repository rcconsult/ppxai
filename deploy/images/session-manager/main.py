"""Session Manager — Kubernetes multi-user session lifecycle management.

Endpoints:
  POST   /sessions                    Create session (or return existing)
  DELETE /sessions/{username}         Tear down session
  POST   /sessions/{username}/heartbeat  Reset idle TTL
  GET    /sessions                    List active sessions
  GET    /health                      Health check

Registry: per-user JSON at /registry/<username>/meta.json (on PVC).
Resources per session: workspace PVC (Retain), temp PVC (Delete), Pod, Service, Ingress rule.

All k8s resource names are derived from APP_PREFIX (default "ppxai").
Set env vars to customize for different deployments (e.g. APP_PREFIX=coder).

Authentication:
  AUTH_MODE=stub   — accept any username, no password required (default, POC)
  AUTH_MODE=ldap   — validate username+password against Active Directory
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from kubernetes import client as k8s, config as k8s_config
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

NAMESPACE = os.getenv("NAMESPACE", "ppxai-system")
REGISTRY_DIR = Path(os.getenv("REGISTRY_DIR", "/registry"))
MAX_SESSIONS = int(os.getenv("MAX_SESSIONS", "3"))
TTL_MINUTES = int(os.getenv("TTL_MINUTES", "10"))
SERVER_IMAGE = os.getenv("SERVER_IMAGE", "registry.ppxai-system.svc:5000/ppxai-server:latest")
WORKSPACE_SIZE = os.getenv("WORKSPACE_SIZE", "5Gi")
TEMP_SIZE = os.getenv("TEMP_SIZE", "2Gi")
INGRESS_NAME = os.getenv("INGRESS_NAME", "ppxai-sessions-ingress")

# Naming & storage config — override these for different deployments
APP_PREFIX = os.getenv("APP_PREFIX", "ppxai")
WORKSPACE_SC = os.getenv("WORKSPACE_SC", "ppxai-workspace")
EPHEMERAL_SC = os.getenv("EPHEMERAL_SC", "ppxai-ephemeral")
CONFIG_CM = os.getenv("CONFIG_CM", f"{APP_PREFIX}-server-config")
SECRET_NAME = os.getenv("SECRET_NAME", f"{APP_PREFIX}-api-keys")

# Authentication: "stub" (no password) or "ldap" (AD bind)
AUTH_MODE = os.getenv("AUTH_MODE", "stub")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("session-manager")

# ---------------------------------------------------------------------------
# LDAP authenticator (lazy init — only when AUTH_MODE=ldap)
# ---------------------------------------------------------------------------

ldap_auth = None
if AUTH_MODE == "ldap":
    from ldap_auth import LDAPAuthenticator
    ldap_auth = LDAPAuthenticator()
    log.info("LDAP authentication enabled")

# ---------------------------------------------------------------------------
# Kubernetes clients
# ---------------------------------------------------------------------------

try:
    k8s_config.load_incluster_config()
except k8s_config.ConfigException:
    k8s_config.load_kube_config()

core = k8s.CoreV1Api()
net = k8s.NetworkingV1Api()

# ---------------------------------------------------------------------------
# Registry helpers
# ---------------------------------------------------------------------------


class SessionMeta:
    def __init__(
        self,
        username: str,
        pod_name: str,
        svc_name: str,
        workspace_pvc: str,
        temp_pvc: str,
        created_at: str,
        last_heartbeat: str,
        workspace_pv: str = "",
    ):
        self.username = username
        self.pod_name = pod_name
        self.svc_name = svc_name
        self.workspace_pvc = workspace_pvc
        self.temp_pvc = temp_pvc
        self.created_at = created_at
        self.last_heartbeat = last_heartbeat
        self.workspace_pv = workspace_pv

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, d: dict) -> "SessionMeta":
        # Backward compat: old meta.json files lack workspace_pv
        if "workspace_pv" not in d:
            d["workspace_pv"] = ""
        return cls(**d)


def _meta_path(username: str) -> Path:
    return REGISTRY_DIR / username / "meta.json"


def _load_meta(username: str) -> Optional[SessionMeta]:
    path = _meta_path(username)
    if not path.exists():
        return None
    try:
        return SessionMeta.from_dict(json.loads(path.read_text()))
    except Exception as e:
        log.warning(f"Corrupt meta for {username}: {e}")
        return None


def _save_meta(meta: SessionMeta) -> None:
    path = _meta_path(meta.username)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta.to_dict(), indent=2))


def _delete_meta(username: str) -> None:
    path = _meta_path(username)
    if path.exists():
        path.unlink()
    try:
        path.parent.rmdir()
    except OSError:
        pass


def _list_sessions() -> list[SessionMeta]:
    sessions = []
    if not REGISTRY_DIR.exists():
        return sessions
    for user_dir in REGISTRY_DIR.iterdir():
        if user_dir.is_dir():
            meta = _load_meta(user_dir.name)
            if meta:
                sessions.append(meta)
    return sessions


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(username: str) -> str:
    """Convert username to a k8s-safe DNS label (lowercase, hyphenated, max 32 chars)."""
    import re
    slug = re.sub(r"[^a-z0-9-]", "-", username.lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:32]


# ---------------------------------------------------------------------------
# Kubernetes resource helpers
# ---------------------------------------------------------------------------


def _create_workspace_pvc(username: str, volume_name: str = "") -> str:
    """Create or reuse the workspace PVC for a user.

    If *volume_name* is provided (from SessionMeta.workspace_pv), the PVC
    is created with an explicit ``volumeName`` so Kubernetes binds it to
    the exact same PV that held the user's data previously.  Before
    binding, any stale ``claimRef`` on the target PV is cleared so the
    Retain-policy PV accepts the new PVC.
    """
    slug = _slug(username)
    name = f"{APP_PREFIX}-ws-{slug}"
    try:
        core.read_namespaced_persistent_volume_claim(name, NAMESPACE)
        log.info(f"Workspace PVC {name} already exists — reusing")
        return name
    except k8s.ApiException as e:
        if e.status != 404:
            raise

    # If we know the exact PV, clear its stale claimRef so it can rebind
    if volume_name:
        try:
            pv = core.read_persistent_volume(volume_name)
            claim_ref = pv.spec.claim_ref
            if claim_ref and pv.status.phase == "Released":
                log.info(f"Clearing stale claimRef on PV {volume_name}")
                core.patch_persistent_volume(
                    volume_name,
                    {"spec": {"claimRef": None}},
                )
        except k8s.ApiException as e:
            log.warning(f"Could not prepare PV {volume_name}: {e.reason}")
            volume_name = ""  # fall back to dynamic binding

    pvc = k8s.V1PersistentVolumeClaim(
        metadata=k8s.V1ObjectMeta(name=name, namespace=NAMESPACE),
        spec=k8s.V1PersistentVolumeClaimSpec(
            access_modes=["ReadWriteOnce"],
            storage_class_name=WORKSPACE_SC,
            resources=k8s.V1ResourceRequirements(requests={"storage": WORKSPACE_SIZE}),
            volume_name=volume_name or None,
        ),
    )
    core.create_namespaced_persistent_volume_claim(NAMESPACE, pvc)
    log.info(f"Created workspace PVC {name}" + (f" → PV {volume_name}" if volume_name else ""))
    return name


def _create_temp_pvc(username: str) -> str:
    slug = _slug(username)
    name = f"{APP_PREFIX}-tmp-{slug}"
    # Delete stale temp PVC if present (session restart)
    try:
        core.delete_namespaced_persistent_volume_claim(name, NAMESPACE, body=k8s.V1DeleteOptions())
        log.info(f"Deleted stale temp PVC {name}")
    except k8s.ApiException:
        pass
    pvc = k8s.V1PersistentVolumeClaim(
        metadata=k8s.V1ObjectMeta(name=name, namespace=NAMESPACE),
        spec=k8s.V1PersistentVolumeClaimSpec(
            access_modes=["ReadWriteOnce"],
            storage_class_name=EPHEMERAL_SC,
            resources=k8s.V1ResourceRequirements(requests={"storage": TEMP_SIZE}),
        ),
    )
    core.create_namespaced_persistent_volume_claim(NAMESPACE, pvc)
    log.info(f"Created temp PVC {name}")
    return name


def _create_server_pod(username: str, workspace_pvc: str, temp_pvc: str) -> str:
    slug = _slug(username)
    name = f"{APP_PREFIX}-server-{slug}"
    # Remove stale pod if present
    try:
        core.delete_namespaced_pod(
            name, NAMESPACE, body=k8s.V1DeleteOptions(grace_period_seconds=0)
        )
        log.info(f"Deleted stale pod {name}")
    except k8s.ApiException:
        pass

    pod = k8s.V1Pod(
        metadata=k8s.V1ObjectMeta(
            name=name,
            namespace=NAMESPACE,
            labels={"app": f"{APP_PREFIX}-server", f"{APP_PREFIX}/user": slug},
        ),
        spec=k8s.V1PodSpec(
            restart_policy="Always",
            containers=[
                k8s.V1Container(
                    name="server",
                    image=SERVER_IMAGE,
                    image_pull_policy="Always",
                    working_dir="/workspace",
                    # v1.18.7: HOME=/workspace makes Path.home()/.ppxai
                    # resolve to the workspace PVC for user state
                    # (sessions, logs, usage). The image bundles
                    # ~/.ppxai/web/ + ~/.ppxai/AGENTS.md at /root/.ppxai/
                    # because BUILDER's HOME was /root — those are
                    # image-versioned static assets, not user state.
                    # We symlink them in on every container start so
                    # the server (which looks at Path.home()/.ppxai/web)
                    # finds them. Symlinks regenerate on each start, so
                    # an image upgrade transparently delivers a new web
                    # UI without touching the PVC. The symlink is
                    # idempotent: ln -sfn replaces an existing symlink
                    # but won't clobber a real directory if a user ever
                    # creates one at that path.
                    command=["bash", "-c"],
                    args=[
                        "set -e; "
                        "mkdir -p /workspace/.ppxai; "
                        "ln -sfn /root/.ppxai/web /workspace/.ppxai/web; "
                        "ln -sfn /root/.ppxai/AGENTS.md /workspace/.ppxai/AGENTS.md; "
                        "exec python -m ppxai.server.http --host 0.0.0.0 --port 54320"
                    ],
                    ports=[k8s.V1ContainerPort(container_port=54320)],
                    env=[
                        k8s.V1EnvVar(name="PPXAI_WORKING_DIR", value="/workspace"),
                        # v1.18.7: HOME=/workspace makes Path.home() / ".ppxai"
                        # resolve to /workspace/.ppxai, putting sessions / logs /
                        # usage / debug-log toggle on the workspace PVC. Without
                        # this, $HOME is /root and everything in ~/.ppxai lives in
                        # ephemeral container storage — kubelet's first SIGKILL
                        # (typically a liveness-probe timeout during a long LLM
                        # stream) wipes the user's chat history mid-session.
                        # The earlier PPXAI_DATA_DIR env was dead weight: ppxai's
                        # loader hardcodes Path.home(), and that's the right
                        # contract to use — we move the goal post via $HOME
                        # rather than carry a parallel env var.
                        k8s.V1EnvVar(name="HOME", value="/workspace"),
                        k8s.V1EnvVar(name="PPXAI_USERNAME", value=username),
                    ],
                    env_from=[
                        k8s.V1EnvFromSource(
                            secret_ref=k8s.V1SecretEnvSource(
                                name=SECRET_NAME, optional=True
                            )
                        ),
                    ],
                    volume_mounts=[
                        k8s.V1VolumeMount(name="workspace", mount_path="/workspace"),
                        k8s.V1VolumeMount(name="temp", mount_path="/tmp/session"),
                        # v1.18.7: mount lands on the workspace PVC because
                        # HOME=/workspace, so Path.home() / ".ppxai" =
                        # /workspace/.ppxai. Survives pod restarts.
                        k8s.V1VolumeMount(
                            name="server-config",
                            mount_path="/workspace/.ppxai/ppxai-config.json",
                            sub_path="ppxai-config.json",
                        ),
                    ],
                    resources=k8s.V1ResourceRequirements(
                        requests={"cpu": "1", "memory": "1Gi"},
                        limits={"cpu": "4", "memory": "4Gi"},
                    ),
                    liveness_probe=k8s.V1Probe(
                        http_get=k8s.V1HTTPGetAction(path="/health", port=54320),
                        initial_delay_seconds=30,
                        period_seconds=60,
                        # v1.18.7: bumped 10s→30s + threshold 5→10 after a
                        # MiniMax-M2.7 long-reasoning stall blocked the event
                        # loop for ~3 minutes and triggered SIGKILL mid-chat,
                        # wiping the user's session. New budget tolerates up to
                        # ~10 minutes of intermittent unresponsiveness before
                        # giving up on a truly dead pod (10 × 60s period).
                        timeout_seconds=30,
                        failure_threshold=10,
                    ),
                    readiness_probe=k8s.V1Probe(
                        # TCP probe — succeeds when uvicorn binds the socket.
                        # HTTP readiness was failing during LLM streaming because
                        # the single-worker event loop can't serve /health while
                        # streaming tokens. TCP avoids that — it only checks the
                        # socket is open, not that the app can process a request.
                        tcp_socket=k8s.V1TCPSocketAction(port=54320),
                        initial_delay_seconds=5,
                        period_seconds=10,
                        timeout_seconds=2,
                        failure_threshold=3,
                    ),
                )
            ],
            volumes=[
                k8s.V1Volume(
                    name="workspace",
                    persistent_volume_claim=k8s.V1PersistentVolumeClaimVolumeSource(
                        claim_name=workspace_pvc
                    ),
                ),
                k8s.V1Volume(
                    name="temp",
                    persistent_volume_claim=k8s.V1PersistentVolumeClaimVolumeSource(
                        claim_name=temp_pvc
                    ),
                ),
                k8s.V1Volume(
                    name="server-config",
                    config_map=k8s.V1ConfigMapVolumeSource(name=CONFIG_CM),
                ),
            ],
        ),
    )
    core.create_namespaced_pod(NAMESPACE, pod)
    log.info(f"Created pod {name}")
    return name


def _create_server_service(username: str) -> str:
    slug = _slug(username)
    name = f"{APP_PREFIX}-svc-{slug}"
    try:
        core.delete_namespaced_service(name, NAMESPACE)
    except k8s.ApiException:
        pass
    svc = k8s.V1Service(
        metadata=k8s.V1ObjectMeta(name=name, namespace=NAMESPACE),
        spec=k8s.V1ServiceSpec(
            selector={"app": f"{APP_PREFIX}-server", f"{APP_PREFIX}/user": slug},
            ports=[k8s.V1ServicePort(port=54320, target_port=54320)],
        ),
    )
    core.create_namespaced_service(NAMESPACE, svc)
    log.info(f"Created service {name}")
    return name


def _create_sessions_ingress(host: str, first_path: k8s.V1HTTPIngressPath) -> None:
    """Create the sessions Ingress with the first user path (k8s requires at least one path)."""
    ingress = k8s.V1Ingress(
        metadata=k8s.V1ObjectMeta(
            name=INGRESS_NAME,
            namespace=NAMESPACE,
            annotations={
                "nginx.ingress.kubernetes.io/rewrite-target": "/$2",
                "nginx.ingress.kubernetes.io/use-regex": "true",
                "nginx.ingress.kubernetes.io/proxy-read-timeout": "3600",
                "nginx.ingress.kubernetes.io/proxy-send-timeout": "3600",
                "nginx.ingress.kubernetes.io/proxy-buffering": "off",
                "nginx.ingress.kubernetes.io/proxy-http-version": "1.1",
            },
        ),
        spec=k8s.V1IngressSpec(
            ingress_class_name="nginx",
            rules=[
                k8s.V1IngressRule(
                    host=host,
                    http=k8s.V1HTTPIngressRuleValue(paths=[first_path]),
                )
            ],
        ),
    )
    net.create_namespaced_ingress(NAMESPACE, ingress)
    log.info(f"Created sessions Ingress {INGRESS_NAME}")


def _ingress_path_rule(slug: str, svc_name: str) -> k8s.V1HTTPIngressPath:
    return k8s.V1HTTPIngressPath(
        path=f"/s/{slug}(/|$)(.*)",
        path_type="ImplementationSpecific",
        backend=k8s.V1IngressBackend(
            service=k8s.V1IngressServiceBackend(
                name=svc_name,
                port=k8s.V1ServiceBackendPort(number=54320),
            )
        ),
    )


def _patch_ingress_add(username: str, svc_name: str) -> None:
    slug = _slug(username)
    path_rule = _ingress_path_rule(slug, svc_name)
    try:
        ingress = net.read_namespaced_ingress(INGRESS_NAME, NAMESPACE)
    except k8s.ApiException as e:
        if e.status == 404:
            # First session — create the sessions ingress with this path
            _create_sessions_ingress(INGRESS_HOST, path_rule)
            log.info(f"Ingress created with /s/{slug}")
            return
        raise
    paths = ingress.spec.rules[0].http.paths or []
    # Remove any existing rule for this user
    paths = [p for p in paths if slug not in (p.path or "")]
    # Insert user path at front (nginx matches in order; more specific first)
    paths.insert(0, path_rule)
    ingress.spec.rules[0].http.paths = paths
    net.replace_namespaced_ingress(INGRESS_NAME, NAMESPACE, ingress)
    log.info(f"Ingress patched: added /s/{slug}")


def _patch_ingress_remove(username: str) -> None:
    slug = _slug(username)
    try:
        ingress = net.read_namespaced_ingress(INGRESS_NAME, NAMESPACE)
    except k8s.ApiException as e:
        if e.status == 404:
            return
        raise
    paths = ingress.spec.rules[0].http.paths or []
    paths = [p for p in paths if slug not in (p.path or "")]
    if not paths:
        # Last session removed — delete the ingress rather than leaving empty paths
        net.delete_namespaced_ingress(INGRESS_NAME, NAMESPACE)
        log.info(f"Ingress deleted (no sessions remaining)")
        return
    ingress.spec.rules[0].http.paths = paths
    net.replace_namespaced_ingress(INGRESS_NAME, NAMESPACE, ingress)
    log.info(f"Ingress patched: removed /s/{slug}")


def _teardown_session(meta: SessionMeta) -> None:
    """Delete pod, service, temp PVC, ingress rule. Keep workspace PVC."""
    def _try_delete(fn, *args, **kwargs):
        try:
            fn(*args, **kwargs)
        except k8s.ApiException as e:
            if e.status != 404:
                log.warning(f"Error in {fn.__name__}: {e}")

    _try_delete(
        core.delete_namespaced_pod,
        meta.pod_name, NAMESPACE, body=k8s.V1DeleteOptions(grace_period_seconds=5),
    )
    log.info(f"Deleted pod {meta.pod_name}")

    _try_delete(core.delete_namespaced_service, meta.svc_name, NAMESPACE)
    log.info(f"Deleted service {meta.svc_name}")

    _try_delete(
        core.delete_namespaced_persistent_volume_claim,
        meta.temp_pvc, NAMESPACE, body=k8s.V1DeleteOptions(),
    )
    log.info(f"Deleted temp PVC {meta.temp_pvc}")

    _patch_ingress_remove(meta.username)
    _delete_meta(meta.username)
    log.info(f"Session {meta.username} torn down")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title=f"{APP_PREFIX} Session Manager")


class CreateSessionRequest(BaseModel):
    username: str
    password: Optional[str] = None


@app.post("/sessions", status_code=201)
def create_session(req: CreateSessionRequest):
    import re
    username = req.username.strip()
    if not username or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,31}", username):
        raise HTTPException(400, "Invalid username — use letters, digits, dots, hyphens, underscores")

    # Authenticate if LDAP is enabled
    if AUTH_MODE == "ldap":
        if not req.password:
            raise HTTPException(400, "Password is required")
        if not ldap_auth.authenticate(username, req.password):
            raise HTTPException(401, "Invalid credentials")

    # Return existing session if pod is actually running; otherwise rebuild
    existing = _load_meta(username)
    stored_pv = ""
    if existing:
        stored_pv = existing.workspace_pv or ""
        try:
            pod = core.read_namespaced_pod(name=existing.pod_name, namespace=NAMESPACE)
            if pod.status.phase in ("Running", "Pending"):
                existing.last_heartbeat = _now_iso()
                _save_meta(existing)
                # Re-add ingress rule in case it was lost (e.g., Helm recreated ingress)
                _patch_ingress_add(username, existing.svc_name)
                slug = _slug(username)
                return {"status": "existing", "username": username, "path": f"/s/{slug}/"}
        except k8s.ApiException as e:
            if e.status != 404:
                raise
        # Pod is gone — tear down stale resources and recreate below
        log.info(f"Stale session for {username} (pod missing) — recreating")
        _teardown_session(existing)

    active = _list_sessions()
    if len(active) >= MAX_SESSIONS:
        raise HTTPException(503, f"Max sessions ({MAX_SESSIONS}) reached — try again later")

    workspace_pvc = _create_workspace_pvc(username, volume_name=stored_pv)
    temp_pvc = _create_temp_pvc(username)
    pod_name = _create_server_pod(username, workspace_pvc, temp_pvc)
    svc_name = _create_server_service(username)
    _patch_ingress_add(username, svc_name)

    # Read back the actual PV name after binding and persist it
    bound_pv = ""
    try:
        pvc_obj = core.read_namespaced_persistent_volume_claim(workspace_pvc, NAMESPACE)
        bound_pv = pvc_obj.spec.volume_name or ""
    except k8s.ApiException:
        pass

    now = _now_iso()
    meta = SessionMeta(
        username=username,
        pod_name=pod_name,
        svc_name=svc_name,
        workspace_pvc=workspace_pvc,
        temp_pvc=temp_pvc,
        created_at=now,
        last_heartbeat=now,
        workspace_pv=bound_pv,
    )
    _save_meta(meta)
    log.info(f"Session created for {username}")
    slug = _slug(username)
    return {"status": "created", "username": username, "path": f"/s/{slug}/"}


@app.delete("/sessions/{username}", status_code=204)
def delete_session(username: str):
    meta = _load_meta(username)
    if not meta:
        raise HTTPException(404, "Session not found")
    _teardown_session(meta)
    return Response(status_code=204)


@app.post("/sessions/{username}/heartbeat")
def heartbeat(username: str):
    meta = _load_meta(username)
    if not meta:
        raise HTTPException(404, "Session not found")
    meta.last_heartbeat = _now_iso()
    _save_meta(meta)
    return {"ok": True}


@app.get("/sessions")
def list_sessions():
    sessions = _list_sessions()
    return {
        "count": len(sessions),
        "max": MAX_SESSIONS,
        "sessions": [s.to_dict() for s in sessions],
    }


@app.get("/health")
def health():
    result = {"ok": True, "auth_mode": AUTH_MODE}
    if ldap_auth:
        ldap_ok = ldap_auth.ping()
        result["ldap"] = "reachable" if ldap_ok else "unreachable"
        if not ldap_ok:
            result["ok"] = False
    return result


# ---------------------------------------------------------------------------
# TTL watchdog
# ---------------------------------------------------------------------------


def _check_ttl() -> None:
    ttl = timedelta(minutes=TTL_MINUTES)
    now = datetime.now(timezone.utc)
    for meta in _list_sessions():
        try:
            last = datetime.fromisoformat(meta.last_heartbeat)
            if (now - last) > ttl:
                log.info(f"Session {meta.username} idle for {now - last} — expiring")
                _teardown_session(meta)
        except Exception as e:
            log.error(f"TTL watchdog error for {meta.username}: {e}")


async def _ttl_watchdog() -> None:
    while True:
        await asyncio.sleep(60)
        try:
            _check_ttl()
        except Exception as e:
            log.error(f"TTL watchdog loop error: {e}")


INGRESS_HOST = os.getenv("INGRESS_HOST", "ppxai.local")


@app.on_event("startup")
async def startup() -> None:
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    _reconcile_ingress()
    asyncio.create_task(_ttl_watchdog())
    log.info(f"Session manager ready (max={MAX_SESSIONS}, ttl={TTL_MINUTES}m, auth={AUTH_MODE}, namespace={NAMESPACE})")


def _reconcile_ingress() -> None:
    """Re-add all registry sessions to the sessions Ingress (recovers from helm upgrades)."""
    sessions = _list_sessions()
    if not sessions:
        return
    for meta in sessions:
        try:
            _patch_ingress_add(meta.username, meta.svc_name)
        except Exception as e:
            log.warning(f"Reconcile ingress for {meta.username}: {e}")
