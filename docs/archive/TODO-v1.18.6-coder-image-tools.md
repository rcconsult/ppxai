# TODO: v1.18.6 — Rebuild coder image with latest code + utility tools

**Status:** ✅ DONE — both phases shipped 2026-05-13.
**Target:** v1.18.6.
**Branch:** `bugfix/v1.18.6`.

## Outcome

- **Phase 1 (latest code)** — image rebuilt 2026-05-13 from `bugfix/v1.18.6` HEAD, registry digest `sha256:7151576c9c60665b74308fc84ca49f7d4abb340aadde7d50f49ebc191bd7ef2e`. Carries: context-indicator fixes (`a4002844`, `1507e5ca`, `f5c84b7e`, `70a0457f`), benchmark commits (`68624251`, `c7a35b01`), version bump to 1.18.6 (`ea21f244`).
- **Phase 2 (utility tools)** — Dockerfile Stage-2 patched in `e2737da4` + musl-tarball fix in `9a9343ef`. Image rebuilt 2026-05-13, registry digest `sha256:80bed0680306ab785f5a733af0af3f2b9b0f7719e1cfa95bd047762524ab0cec`. Verified in a fresh pod: all 14 tools (`git jq yq rg fd tree nano vim.tiny rtk curl wget unzip zip less`) resolve to expected paths, `rtk hook check git status` returns the expected `rtk git status` rewrite, and ppxai's wrapper-registry probe reports `is_available=True, is_active=True` against rtk.
- **rtk integration ppxai-in-pod ≡ ppxai-on-host** — confirmed identical. No filters.toml or history.db needed in the image: rtk is fully passive (binary on PATH + ppxai `DEFAULT_SHELL_WRAPPERS` auto-detection). Per-pod state (history.db) is the right scoping — each developer's pod tracks its own analytics.

The rest of this doc preserves the design rationale for future audits + the install-on-demand snippets for the deferred tools.

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
| `rtk` | (install from GH release `.deb` — `rtk-ai/rtk` v0.39.0) | ~3 MB | **Rust Token Killer** — token-optimized CLI proxy (60-90% savings on dev ops). Once installed + integrated via the Claude Code hook, `git status` → `rtk git status` transparently. Wrapper framework in v1.18.5 already ships `rtk` as the canonical first entry in `DEFAULT_SHELL_WRAPPERS` — so the in-image binary + the engine-side rewrite hook line up. NOTE: a different `reachingforthejack/rtk` (Rust Type Kit) exists on GH — we explicitly want `rtk-ai/rtk`. |

**Total estimated size delta:** ~83 MB (mostly `git`).

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

# rtk — Rust Token Killer (github.com/rtk-ai/rtk, NOT reachingforthejack/rtk).
# Pin the version explicitly so the Dockerfile is reproducible. Bump as new
# releases land — also bump the v1.18.5 DEFAULT_SHELL_WRAPPERS rtk entry if
# the rewrite-command shape ever changes.
ARG RTK_VERSION=0.39.0
RUN curl -fsSL -o /tmp/rtk.deb \
    https://github.com/rtk-ai/rtk/releases/download/v${RTK_VERSION}/rtk_${RTK_VERSION}-1_amd64.deb \
    && apt-get update \
    && apt-get install -y --no-install-recommends /tmp/rtk.deb \
    && rm -f /tmp/rtk.deb \
    && rm -rf /var/lib/apt/lists/*
```

## Verify after the rebuild

```bash
# Once Kaniko has pushed :latest, spawn a fresh pod and shell in:
microk8s kubectl exec -n coder coder-server-<user> -- which git jq yq rg fd tree nano vim.tiny rtk
# Expect 9 paths, no "not found".

# Quick sanity on tool versions:
microk8s kubectl exec -n coder coder-server-<user> -- bash -c \
  'git --version; jq --version; yq --version; rg --version | head -1; nano --version | head -1; rtk --version'

# Confirm rtk-ai/rtk (NOT reachingforthejack/rtk) — the "gain" subcommand
# only exists on rtk-ai/rtk:
microk8s kubectl exec -n coder coder-server-<user> -- rtk gain --help | head -3
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
