# TODO: v1.18.6 — Rebuild coder image with latest code + utility tools

**Status:** Not started.
**Target:** v1.18.6 (or first release that ships `deploy/images/server/Dockerfile` changes).
**Branch:** `bugfix/v1.18.6` (already carries the context-indicator fixes; image rebuild lives here too).

## Two changes in one image rebuild

### 1. Pick up the latest code

The current `localhost:32000/coder-server:latest` (`sha256:de680b6d`) was built on **2026-05-06** from the previous `bugfix/v1.18.4` branch with the four context-indicator commits (`a4002844`, `1507e5ca`, `f5c84b7e`, `70a0457f`). Master has since released v1.18.4 and v1.18.5 (master tip = `f1e0579f`). The current `bugfix/v1.18.6` branch is v1.18.5 + the same four cherry-picked fixes (`a4002844`, `1507e5ca`, `f5c84b7e`, `70a0457f`) + two benchmark commits (`68624251`, `c7a35b01`).

**Action:** rerun `deploy/microk8s/build.sh server` from `bugfix/v1.18.6`. Kaniko mounts `/home/itadmin/tools/ppxai` directly, so no further setup needed.

### 2. Add utility tools to the runtime stage

Coder pods are general-purpose developer sandboxes — users run `ppxai-server` AND the AI agents inside execute shell commands on their behalf. Right now the runtime image (Stage 2 in `deploy/images/server/Dockerfile`) only has `poppler-utils` + `libreoffice-nogui` baked in. Common tools agents reach for are missing, which forces the agent into awkward workarounds (e.g. `python3 -c "import json; ..."` instead of `jq`).

**Action:** extend the Stage-2 `RUN apt-get install` to add these:

| Tool | Apt package | Size | Why |
|---|---|---:|---|
| `git` | `git` | ~50 MB | Essential for any `git status`/`git log`/`git diff` agent action. Coder pods do version-control work all day. |
| `jq` | `jq` | ~1 MB | JSON parsing in `Bash` tool calls. Used constantly when agents inspect API responses. |
| `yq` | (install via curl, NOT apt — apt's `yq` is the Python wrapper, slow) | ~5 MB | YAML parsing. K8s manifests, GitHub Actions, Docker Compose files. |
| `curl` | `curl` | ~5 MB | Likely already pulled in by other deps, but pin it explicitly. |
| `wget` | `wget` | ~3 MB | Sometimes scripts pipe `\| sh`; `curl` is fine but `wget` is the more idiomatic GET-to-file. |
| `ripgrep` | `ripgrep` | ~5 MB | **High-impact** — orders of magnitude faster than `grep -r` for code search. Most coding agents reach for `rg` reflexively. |
| `fd` (fd-find) | `fd-find` (binary is `fdfind`; symlink to `fd`) | ~3 MB | Fast `find` replacement. Common agent companion to `rg`. |
| `tree` | `tree` | ~100 KB | Directory visualization. Useful for "show me the repo layout" prompts. |
| `unzip` / `zip` | `unzip` `zip` | ~1 MB | Archive handling. Comes up in build/asset workflows. |
| `less` | `less` | ~500 KB | Paging. Agents pipe long output to `less`-friendly format checks. |
| `vim-tiny` | `vim-tiny` | ~2 MB | Minimal vim for `:%s/foo/bar/g`-style edits. NOT full vim (~50 MB) — agents use apply_patch, not interactive vim. |
| `nano` | `nano` | ~1 MB | Beginner-friendly editor — covers the few cases where vim's modal model trips an agent up. |

**Total estimated size delta:** ~80 MB (mostly `git`).

## What's NOT in the list (and why)

- **`gh` (GitHub CLI, ~30 MB)** — initially proposed, removed by maintainer. Agents that need PR/issue/release work via `gh` can install it on-demand inside the session:
  ```bash
  curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | sudo tee /usr/share/keyrings/githubcli-archive-keyring.gpg > /dev/null
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    | sudo tee /etc/apt/sources.list.d/github-cli.list
  sudo apt update && sudo apt install gh
  ```
  (The runtime pod runs as root per the Dockerfile, so `sudo` is a no-op.)

- **`pwsh` (PowerShell v7.6.1, ~180 MB installed)** — `.deb` is 56 MB compressed, installed footprint ~150 MB plus `libicu72` (~30 MB dep). That's **more than the entire rest of the list combined.** Deferred for two reasons:
  1. Bash is the lingua franca on Linux coder pods; pwsh usage is niche (Azure-heavy workflows, ports from Windows-heritage scripts).
  2. Users who genuinely need pwsh can install it on-demand in their session:
     ```bash
     curl -fsSL -o /tmp/pwsh.deb \
       https://github.com/PowerShell/PowerShell/releases/download/v7.6.1/powershell_7.6.1-1.deb_amd64.deb
     apt update && apt install -y /tmp/pwsh.deb && rm /tmp/pwsh.deb
     ```
  Revisit if more than a handful of users hit the "I need pwsh" wall.

- **`kubectl` (~50 MB)** — useful for in-cluster inspection from inside the pod, but might encourage agents to make changes to the cluster they shouldn't. Skip.

- **`make`, `build-essential` (~250 MB)** — large; only useful for projects that compile native code in the workspace. Add if a project demands it.

- **`node` + `npm` (~150 MB)** — for JS work. Likely worth adding given how common JS tooling is, but defer until requested to keep the image lean.

- **Language runtimes (Go, Rust, Ruby)** — defer until requested.

## Suggested Dockerfile patch (Stage-2 only)

```dockerfile
# Runtime system deps:
#   poppler-utils    — pdf2image (GetPdfPageImageTool)
#   libreoffice-nogui — PPTX/DOCX slide rasterization
#   git              — version control (essential for any coding workflow)
#   curl, wget       — HTTP fetch
#   jq               — JSON wrangling in shell
#   ripgrep, fd-find — fast code search (fd binary is named fdfind; we symlink)
#   tree, less, unzip, zip — common shell utilities
#   vim-tiny, nano   — minimal editors (vim-tiny for sed-style; nano for non-vim agents)
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    libreoffice-nogui \
    git \
    curl \
    wget \
    jq \
    ripgrep \
    fd-find \
    tree \
    less \
    unzip \
    zip \
    vim-tiny \
    nano \
    ca-certificates \
    && ln -sf /usr/bin/fdfind /usr/local/bin/fd \
    && rm -rf /var/lib/apt/lists/*

# yq (Go binary — apt's yq is the slow Python wrapper)
RUN curl -fsSL -o /usr/local/bin/yq \
    https://github.com/mikefarah/yq/releases/latest/download/yq_linux_amd64 \
    && chmod +x /usr/local/bin/yq
```

## Verify after the rebuild

```bash
# Once Kaniko has pushed :latest, spawn a fresh pod and shell in:
microk8s kubectl exec -n coder coder-server-<user> -- which git jq yq rg fd tree nano vim.tiny
# Expect 8 paths, no "not found".

# Quick sanity on tool versions:
microk8s kubectl exec -n coder coder-server-<user> -- bash -c \
  'git --version; jq --version; yq --version; rg --version | head -1; nano --version | head -1'
```

## Effort

~30 min total:
- 5 min: Dockerfile edit + commit on `bugfix/v1.18.6`
- 5 min: Kaniko rebuild (depends on cache state — first rebuild after Stage-2 change is ~2-3 min)
- 5 min: spawn a fresh pod, run the verify commands above
- ~15 min: write up the result + close this TODO with the commit SHA

## Cross-references

- Dockerfile current state: [deploy/images/server/Dockerfile](../deploy/images/server/Dockerfile)
- Build script: [deploy/microk8s/build.sh](../deploy/microk8s/build.sh) (`./build.sh server`)
- Kaniko job: [deploy/microk8s/kaniko-server-job.yaml](../deploy/microk8s/kaniko-server-job.yaml) — mounts `/home/itadmin/tools/ppxai` as build context, so the current working-tree commit IS the build source
- Live registry: `localhost:32000/coder-server:latest` (`sha256:de680b6d`, 2026-05-06; needs refresh)
