# ppxai-server — Kubernetes multi-session image
# Built by Kaniko from the repo hostPath volume.
#
# Differences from root Dockerfile:
#   - Runs as root (required for PVC mount permission compatibility with local-path provisioner)
#   - PPXAI_WORKING_DIR / PPXAI_DATA_DIR / PPXAI_USERNAME env vars for per-session config
#   - /workspace and /tmp/session created as mount points for PVCs
#   - web UI path prefix support (app.js patched in the web/ tree)

# =============================================================================
# Stage 1: Builder
# =============================================================================
FROM python:3.12-slim-bookworm AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml README.md ./
COPY ppxai/ ./ppxai/

RUN pip install --no-cache-dir ".[server,search,data]"

# =============================================================================
# Stage 2: Runtime
# =============================================================================
FROM python:3.12-slim-bookworm AS runtime

LABEL org.opencontainers.image.title="ppxai-server-k8s"
LABEL org.opencontainers.image.description="ppxai HTTP server — Kubernetes multi-session build"

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Runtime system deps:
#   poppler-utils    — pdf2image (GetPdfPageImageTool)
#   libreoffice-nogui — PPTX/DOCX slide rasterization (RenderPptxSlideTool)
#   git              — version control (essential for any coding workflow)
#   curl, wget, ca-certificates — HTTP fetch + TLS for yq/rtk downloads below
#   jq               — JSON wrangling in shell
#   ripgrep, fd-find — fast code search (fd binary is named fdfind; symlinked below)
#   tree, less, unzip, zip — common shell utilities
#   vim-tiny, nano   — minimal editors (vim-tiny for sed-style; nano for non-vim agents)
# Rationale + alternatives considered: docs/TODO-v1.18.6-coder-image-tools.md
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

# Corporate / org CA certificates — install into the image's trust store so
# httpx + openai-sdk + curl can verify TLS to enterprise-CA-signed endpoints
# (e.g. dgx-cluster.trad.int presents a cert chain from CN=CA Compagnie
# Financiere Tradition; default debian trust doesn't include it, so without
# this every call fails with "unable to get local issuer certificate").
#
# The extra-certs/ directory is gitignored except for .gitkeep. Operators
# drop their org's *.crt files in before running build.sh. An empty
# directory is fine — `update-ca-certificates` is a no-op when nothing is
# new, so this Dockerfile slice still works in fresh checkouts with no
# corporate certs to install.
COPY deploy/images/server/extra-certs/ /usr/local/share/ca-certificates/
RUN update-ca-certificates
# Python's TLS (httpx, openai-sdk, requests) uses certifi's bundled CA list,
# NOT the system bundle. update-ca-certificates above only updates the
# system bundle (used by curl, OS tools). Append our corporate CAs to
# certifi's bundle too so Python clients trust them. Guarded so that if
# extra-certs/ is empty the cat-glob doesn't error.
RUN CERTIFI_BUNDLE=$(/opt/venv/bin/python -c "import certifi; print(certifi.where())") \
    && if ls /usr/local/share/ca-certificates/*.crt >/dev/null 2>&1; then \
         cat /usr/local/share/ca-certificates/*.crt >> "$CERTIFI_BUNDLE" ; \
         echo "appended corporate CAs to $CERTIFI_BUNDLE" ; \
       fi
# Belt + suspenders: tell Python's ssl module to use the system bundle by
# default. Some libraries bypass certifi (e.g. anything that calls
# ssl.create_default_context() with no cafile argument). The system bundle
# is now authoritative thanks to update-ca-certificates.
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

# yq (Go binary from mikefarah/yq — apt's yq is the slow Python wrapper)
RUN curl -fsSL -o /usr/local/bin/yq \
        https://github.com/mikefarah/yq/releases/latest/download/yq_linux_amd64 \
    && chmod +x /usr/local/bin/yq

# rtk — Rust Token Killer (github.com/rtk-ai/rtk, NOT reachingforthejack/rtk).
# Pinned for reproducibility. Pairs with v1.18.5 shell-wrapper framework —
# DEFAULT_SHELL_WRAPPERS ships rtk as the canonical first entry, so the
# in-image binary + the engine-side rewrite hook line up. Bump RTK_VERSION
# as new releases land; double-check the rewrite-command shape didn't change.
#
# Why musl tarball, not the .deb: the official .deb is built against
# glibc >= 2.39 (Trixie / Ubuntu 24.04). python:3.12-slim-bookworm ships
# glibc 2.36, so the .deb fails dependency resolution. The
# x86_64-unknown-linux-musl tarball is statically linked — no glibc
# dependency at all, works on any kernel >=3.2.
ARG RTK_VERSION=0.39.0
RUN set -eux \
    && mkdir -p /tmp/rtk-install \
    && curl -fsSL -o /tmp/rtk-install/rtk.tar.gz \
        https://github.com/rtk-ai/rtk/releases/download/v${RTK_VERSION}/rtk-x86_64-unknown-linux-musl.tar.gz \
    && tar -xzf /tmp/rtk-install/rtk.tar.gz -C /tmp/rtk-install \
    && find /tmp/rtk-install -name rtk -type f -executable \
        -exec install -m 0755 {} /usr/local/bin/rtk \; \
    && rm -rf /tmp/rtk-install \
    && /usr/local/bin/rtk --version

# Web UI files — served by the HTTP server from ~/.ppxai/web/
COPY --from=builder /build/ppxai/web/ /root/.ppxai/web/

# Agent instructions — loaded by bootstrap as global AGENTS.md
COPY AGENTS.md /root/.ppxai/AGENTS.md

# Per-session environment — overridden at pod creation time by session manager
ENV PPXAI_WORKING_DIR=/workspace
ENV PPXAI_DATA_DIR=/workspace/.ppxai
ENV PPXAI_USERNAME=""

# PVC mount points
RUN mkdir -p /workspace /tmp/session

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 54320

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:54320/health')" || exit 1

CMD ["python", "-m", "ppxai.server.http", "--host", "0.0.0.0", "--port", "54320"]
