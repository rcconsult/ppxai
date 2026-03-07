# macOS Intel — Colima + Kubernetes Setup

Tested on macOS 12.x (Monterey) Intel, colima 0.10.0, k3s v1.35.0.

---

## Prerequisites

Install the required tools via Homebrew:

```bash
brew install colima
brew install kubectl
brew install helm
brew install socket_vmnet
```

Verify versions:

```bash
colima --version     # 0.10.0
limactl --version    # 2.0.3
kubectl version --client --short
helm version --short
```

---

## Step 1 — Install socket_vmnet

`socket_vmnet` enables colima's `--network-address` mode, which gives the VM a real routable
IP on your LAN instead of QEMU's NAT (which is unreachable from the host).

### 1a. Take root ownership of the Homebrew install

```bash
sudo brew services start socket_vmnet
```

This outputs:
```
Warning: Taking root:admin ownership of some socket_vmnet paths:
  /usr/local/Cellar/socket_vmnet/1.2.2/bin
  ...
==> Successfully started `socket_vmnet`
```

### 1b. Copy the binary to both paths

Lima and colima use **different binary paths** — both must exist with no symlinks
(security requirement: prevents privilege escalation via symlink replacement).

```bash
# Lima's expected path
sudo mkdir -p /opt/socket_vmnet/bin
sudo install -o root -m 755 \
    /usr/local/Cellar/socket_vmnet/1.2.2/bin/socket_vmnet \
    /opt/socket_vmnet/bin/socket_vmnet
sudo install -o root -m 755 \
    /usr/local/Cellar/socket_vmnet/1.2.2/bin/socket_vmnet_client \
    /opt/socket_vmnet/bin/socket_vmnet_client

# Colima's expected path (different from Lima's)
sudo mkdir -p /opt/colima/bin
sudo install -o root -m 755 \
    /usr/local/Cellar/socket_vmnet/1.2.2/bin/socket_vmnet \
    /opt/colima/bin/socket_vmnet
sudo install -o root -m 755 \
    /usr/local/Cellar/socket_vmnet/1.2.2/bin/socket_vmnet_client \
    /opt/colima/bin/socket_vmnet_client
```

> **Note:** Update `1.2.2` to the actual installed version (`brew list --versions socket_vmnet`).

### 1c. Install the Lima sudoers rule

Covers `limactl`-managed socket_vmnet operations (bridged/shared/host networks):

```bash
limactl sudoers | sudo tee /private/etc/sudoers.d/lima
```

### 1d. Install the Colima sudoers rule (eliminates interactive prompt)

Colima manages its own sudoers file at `/etc/sudoers.d/colima`. On startup with
`--network-address`, it writes that file and starts the socket_vmnet daemon — both require
sudo. Pre-authorising these commands removes the interactive terminal requirement:

```bash
sudo tee /private/etc/sudoers.d/colima-init << 'EOF'
# Pre-authorise colima network setup — eliminates interactive sudo prompt
# Allows colima to write its own sudoers file (/etc/sudoers.d/colima)
%staff ALL=(root:wheel) NOPASSWD:NOSETENV: /bin/sh -c cat > /etc/sudoers.d/colima
# Allows colima to start/stop the socket_vmnet daemon
%staff ALL=(root:wheel) NOPASSWD:NOSETENV: /opt/colima/bin/socket_vmnet *
%staff ALL=(root:wheel) NOPASSWD:NOSETENV: /usr/bin/pkill -F /private/var/run/lima/shared_socket_vmnet.pid
%staff ALL=(root:wheel) NOPASSWD:NOSETENV: /usr/bin/pkill -F /private/var/run/lima/bridged_socket_vmnet.pid
EOF
sudo chmod 440 /private/etc/sudoers.d/colima-init

# Validate syntax before applying
sudo visudo -c -f /private/etc/sudoers.d/colima-init
```

**How it works:** On first successful `colima start --network-address`, colima writes
`/etc/sudoers.d/colima` with its generated content. On all subsequent starts, colima
detects the content is unchanged and skips the write — so after the first run the
pre-auth rule above is no longer needed (but harmless to leave in place).

---

## Step 2 — Start Colima with Kubernetes

With the sudoers rules in place, colima can now start non-interactively:

```bash
colima start \
    --kubernetes \
    --cpu 4 \
    --memory 8 \
    --disk 60 \
    --network-address
```

Expected output (abbreviated):
```
starting colima
runtime: docker+k3s
preparing network ...
setting up reachable IP address
starting ... context=vm
...
provisioning ... context=kubernetes
starting ... context=kubernetes
done
```

No sudo password prompt should appear. If you still see
`"error setting up reachable IP address"`, check:
1. `/opt/colima/bin/socket_vmnet` exists and is owned by root
2. `/private/etc/sudoers.d/colima-init` is mode `440` and passes `visudo -c`
3. Your user is in the `staff` group: `id | grep staff`

---

## Step 3 — Get the VM IP

```bash
colima list
```

Output:
```
PROFILE    STATUS    ARCH     CPUS  MEMORY  DISK   RUNTIME      ADDRESS
default    Running   x86_64   4     8GiB    60GiB  docker+k3s   192.168.105.x
```

The `ADDRESS` column shows the routable VM IP. With QEMU NAT (fallback) it shows empty.
With `--network-address` it shows a real `192.168.105.x` IP.

---

## Step 4 — Update /etc/hosts

```bash
# Replace 192.168.105.x with the actual IP from `colima list`
echo "192.168.105.x    ppxai.local" | sudo tee -a /etc/hosts
```

Verify TCP reachability (ping uses ICMP which is blocked by QEMU NAT; use curl instead):

```bash
curl -s --connect-timeout 3 http://ppxai.local || echo "no service yet — host is reachable"
```

You should get `connection refused` (not `timeout`), confirming the host is reachable.

---

## Step 5 — Verify Kubernetes

```bash
kubectl get nodes -o wide
kubectl get pods -A
```

Expected:
```
NAME     STATUS   ROLES           AGE   VERSION        INTERNAL-IP      ADDRESS
colima   Ready    control-plane   ...   v1.35.0+k3s1   192.168.105.x   ...

NAMESPACE     NAME                                      READY   STATUS
kube-system   coredns-...                               1/1     Running
kube-system   local-path-provisioner-...                1/1     Running
kube-system   metrics-server-...                        1/1     Running
```

---

## Colima Lifecycle Commands

```bash
# Start (interactive terminal required for --network-address)
colima start --kubernetes --cpu 4 --memory 8 --disk 60 --network-address

# Stop (preserves all k8s state and PVCs on disk)
colima stop

# Status and IP
colima list
colima status

# SSH into the VM
colima ssh

# Delete VM entirely (destructive — loses all data)
colima delete
```

---

## Troubleshooting

### "error setting up reachable IP address" / VM falls back to NAT

- **Cause:** colima's sudo commands lack NOPASSWD rules, or `/opt/colima/bin/socket_vmnet` is missing
- **Fix checklist:**
  1. `/opt/colima/bin/socket_vmnet` exists, owned by root: `ls -la /opt/colima/bin/`
  2. `/private/etc/sudoers.d/colima-init` is mode 440: `ls -la /private/etc/sudoers.d/`
  3. Sudoers syntax is valid: `sudo visudo -c -f /private/etc/sudoers.d/colima-init`
  4. User is in `staff` group: `id | grep staff`
- **Fallback:** Run `colima start --network-address` once from an interactive terminal to bootstrap

### TCP connections to ppxai.local time out

- **Cause:** The VM has the QEMU NAT IP (`192.168.5.1`) instead of a real IP
- **Fix:** Stop colima, run `colima start --network-address` from an interactive terminal
- **Verify:** `colima list` — the ADDRESS column must show `192.168.105.x`, not empty

### ping ppxai.local fails but curl works

- ICMP (ping) is blocked through QEMU networking even in network-address mode
- Use `curl --connect-timeout 3 http://ppxai.local` to test TCP reachability

### limactl sudoers fails with "socket_vmnet has to be installed"

- Lima looks for the binary at `/opt/socket_vmnet/bin/socket_vmnet` (no symlinks allowed)
- Homebrew installs to `/usr/local/Cellar/...` which contains symlinks
- Fix: copy the binary directly (see Step 1b above)

### socket_vmnet version changes after brew upgrade

After `brew upgrade socket_vmnet`, repeat Step 1b with the new version number:

```bash
NEW_VER=$(brew list --versions socket_vmnet | awk '{print $2}')

# Lima's path
sudo install -o root -m 755 \
    /usr/local/Cellar/socket_vmnet/${NEW_VER}/bin/socket_vmnet \
    /opt/socket_vmnet/bin/socket_vmnet
sudo install -o root -m 755 \
    /usr/local/Cellar/socket_vmnet/${NEW_VER}/bin/socket_vmnet_client \
    /opt/socket_vmnet/bin/socket_vmnet_client

# Colima's path
sudo install -o root -m 755 \
    /usr/local/Cellar/socket_vmnet/${NEW_VER}/bin/socket_vmnet \
    /opt/colima/bin/socket_vmnet
sudo install -o root -m 755 \
    /usr/local/Cellar/socket_vmnet/${NEW_VER}/bin/socket_vmnet_client \
    /opt/colima/bin/socket_vmnet_client

limactl sudoers | sudo tee /private/etc/sudoers.d/lima
```

### kubectl context lost after colima restart

Colima updates your kubeconfig automatically. If the context is missing:

```bash
colima kubernetes reset
```

---

## Network Architecture (reference)

```
macOS host
  └── /etc/hosts: 192.168.105.x  ppxai.local
        │
        ▼ (vmnet shared network — routable)
  colima VM (192.168.105.x)
    ├── k3s control plane
    ├── containerd (not Docker — k3s uses containerd for pods)
    ├── Docker daemon (for `docker build` from host)
    └── flannel CNI (pod network: 10.42.0.0/24)
```

**Important:** k3s pods use containerd, not Docker. Images built with `docker build`
on the Mac go into Docker's image store inside the VM, but are **not** automatically
available to k3s pods. For k8s deployments, push images to a registry inside the cluster
(e.g., `registry:2` pod) and reference them with `imagePullPolicy: IfNotPresent`.
