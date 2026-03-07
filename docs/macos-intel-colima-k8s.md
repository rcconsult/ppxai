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

### 1b. Copy the binary to the path Lima expects

Lima requires the binary to be at `/opt/socket_vmnet/bin/socket_vmnet` with **no symlinks**
in the path (security requirement — prevents privilege escalation via symlink replacement).
Homebrew installs to `/usr/local/Cellar/...` which has symlinks in the path, so we copy:

```bash
sudo mkdir -p /opt/socket_vmnet/bin
sudo install -o root -m 755 \
    /usr/local/Cellar/socket_vmnet/1.2.2/bin/socket_vmnet \
    /opt/socket_vmnet/bin/socket_vmnet
sudo install -o root -m 755 \
    /usr/local/Cellar/socket_vmnet/1.2.2/bin/socket_vmnet_client \
    /opt/socket_vmnet/bin/socket_vmnet_client
```

> **Note:** Update `1.2.2` to the actual installed version (`brew list --versions socket_vmnet`).

### 1c. Install the Lima sudoers rule

This allows Lima/colima to start the socket_vmnet daemon without requiring a password
every time:

```bash
limactl sudoers | sudo tee /private/etc/sudoers.d/lima
```

Verify the file was created and contains the socket_vmnet commands:

```bash
cat /private/etc/sudoers.d/lima
```

---

## Step 2 — Start Colima with Kubernetes

**Important:** Run this command in an **interactive terminal** (not via a script or CI).
Colima needs to verify the sudoers setup with an interactive sudo prompt on the first run
with `--network-address`.

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
sudo password may be required
[sudo prompt — enter your password]
starting ... context=vm
...
provisioning ... context=kubernetes
starting ... context=kubernetes
done
```

> If you see `"error setting up reachable IP address"` and colima falls back to QEMU NAT,
> it means the sudo step failed. This always happens when running colima from a
> non-interactive shell (no TTY). Always start colima from your terminal directly.

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

- **Cause:** colima ran from a non-interactive shell (no TTY for sudo)
- **Fix:** Run `colima start` directly in your terminal, not via a script

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
sudo install -o root -m 755 \
    /usr/local/Cellar/socket_vmnet/${NEW_VER}/bin/socket_vmnet \
    /opt/socket_vmnet/bin/socket_vmnet
sudo install -o root -m 755 \
    /usr/local/Cellar/socket_vmnet/${NEW_VER}/bin/socket_vmnet_client \
    /opt/socket_vmnet/bin/socket_vmnet_client
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
