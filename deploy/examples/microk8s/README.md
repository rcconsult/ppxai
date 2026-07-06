# ppxai on microk8s — multi-tenant coder reference deployment

Generic, **example** Kubernetes manifests for running ppxai as a shared,
multi-user coding assistant behind an ingress, with per-user pods and workspaces.
This is the raw-manifest form of the same deployment the Helm chart
(`deploy/helm/ppxai/`) parameterizes — use whichever fits your workflow. If you
want a single templated install, prefer the Helm chart; use these manifests when
you want to read/adapt the pieces directly.

> **These are examples, not a turnkey install.** Every value written as
> `<PLACEHOLDER>` or under an `*.example.com` / `*.internal.example` hostname is a
> stand-in you MUST replace with your own before applying. Nothing here contains
> real secrets — API keys, the LDAP bind password, and the session-signing key are
> all created out-of-band (see `secrets.yaml.template`).

## What it deploys

| File | Role |
|---|---|
| `namespace.yaml` | the `coder` namespace |
| `storage.yaml` | StorageClasses + PVs for per-user workspaces (hostPath example) |
| `rbac.yaml` | ServiceAccount + Role the session-manager needs (namespaced) |
| `secrets.yaml.template` | **template** for the api-keys, LDAP-bind, and session-signing secrets — create these yourself |
| `server-config.yaml` | ConfigMap: the `ppxai-config.json` served into each per-user pod (providers, tools, agent config) |
| `session-manager-deployment.yaml` | the controller that authenticates users (LDAP) and spawns per-user server pods + ingress routes |
| `login-service.yaml` | the login page served at `/` and `/login` |
| `ingress.yaml` | the UNAUTH ingress (`/api`, `/login`, catch-all). Per-user `/s/<slug>` routes are added at runtime by the session-manager on a SEPARATE auth ingress |
| `networkpolicy.yaml` | per-user pod isolation: egress-deny-by-default + ingress restricted to the ingress controller + node probes |
| `kaniko-server-job.yaml` / `kaniko-session-manager-job.yaml` | in-cluster image builds (Kaniko) |
| `build.sh` / `deploy.sh` | convenience wrappers |

## Placeholders to replace

Search the tree for `<`, `example.com`, and `internal.example` and substitute:

- **Hostnames** — `coder.example.com` (your ingress host), `dc.example.com`
  (your LDAP/AD server), `dgx-cluster.internal.example` /
  `dgx-spark.internal.example` (your inference endpoints).
- **LDAP** (`session-manager-deployment.yaml`) — `LDAP_URL`, `LDAP_BASE_DN`,
  `LDAP_BIND_DN` (`dc=example,dc=com`, `CN=svc-ldap-bind,OU=ServiceAccounts,...`),
  and the `ldap-bind-secret` you create.
- **`<...CIDR>` / `<...IP>`** — `<NODE_SUBNET_CIDR>` (the subnet your worker nodes
  sit in — **required** for the NetworkPolicy, see below), `<CORPORATE_CIDR>` +
  `<PROVIDER_CIDR_*>` (egress allowlist for your external inference/API hosts,
  resolved to IPs with `dig +short`).
- **`<REGISTRY_HOST>:<REGISTRY_PORT>`** — your image registry (microk8s ships a
  built-in one; see the microk8s registry add-on docs for its local address).
- **hostPath paths** — `/path/to/ppxai` (repo checkout mounted into Kaniko),
  `<PV_HOSTPATH>` / `<REGISTRY_HOSTPATH>` (node-local storage for the example PVs;
  replace with your StorageClass of choice for a real cluster).

## Requirements & gotchas

- **A policy-enforcing CNI (Calico / Cilium)** is required or `networkpolicy.yaml`
  is inert. The file's header comments document two Calico traps worth reading:
  DNS must be allowed by *namespace selector* (not the kube-dns Service VIP), and
  in-cluster services must be allowed by namespace (the CNI sees the backing-pod
  port, not the Service port).
- **The NetworkPolicy ingress rule needs your node subnet.** kubelet
  liveness/readiness probes originate from the **node IP**, not a pod — so
  `<NODE_SUBNET_CIDR>` must cover your nodes. Omit it and readiness fails → the
  Service gets no endpoints → traffic 503s. (This is the load-bearing detail; the
  comment in the file explains it.)
- **Ingress split is deliberate.** ingress-nginx auth annotations apply to every
  path in an Ingress, so `/login` + `/api` MUST stay on the unauthenticated
  `ingress.yaml`; the per-user `/s/<slug>` routes (which carry the `auth_request`
  cookie gate) are added at runtime on a separate ingress by the session-manager.
- **Secrets are never in these files.** Create them from `secrets.yaml.template`:
  the api-keys secret (provider bearers), `ldap-bind-secret`, and the
  session-signing secret (`openssl rand -hex 32` — the session-manager fails
  closed without it).

## Apply order

```
kubectl apply -f namespace.yaml
kubectl apply -f storage.yaml
kubectl apply -f rbac.yaml
# create the secrets (see secrets.yaml.template) — do NOT commit real values
kubectl apply -f server-config.yaml
kubectl apply -f networkpolicy.yaml      # requires Calico/Cilium
kubectl apply -f login-service.yaml
kubectl apply -f ingress.yaml
kubectl apply -f session-manager-deployment.yaml
```

Build the images first with the Kaniko jobs (or your own pipeline) so
`<REGISTRY_HOST>:<REGISTRY_PORT>/coder-server` and the session-manager image
exist.
