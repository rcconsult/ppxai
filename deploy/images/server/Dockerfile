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
#   poppler-utils  — pdf2image (GetPdfPageImageTool)
#   libreoffice-nogui — PPTX/DOCX slide rasterization (RenderPptxSlideTool)
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    libreoffice-nogui \
    && rm -rf /var/lib/apt/lists/*

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
