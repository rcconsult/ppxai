# Dockerfile for ppxai-server
# Multi-stage build for minimal image size
#
# Build: docker build -f deploy/docker/Dockerfile -t ppxai-server .
# Run:   docker run -p 54320:54320 --env-file .env ppxai-server

# =============================================================================
# Stage 1: Builder
# =============================================================================
FROM python:3.12-slim-bookworm AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy only files needed for installation
COPY pyproject.toml README.md ./
COPY ppxai/ ./ppxai/

# Install package with server and search extras
RUN pip install --no-cache-dir ".[server,search]"

# =============================================================================
# Stage 2: Runtime
# =============================================================================
FROM python:3.12-slim-bookworm AS runtime

# Labels
LABEL org.opencontainers.image.title="ppxai-server"
LABEL org.opencontainers.image.description="HTTP server for ppxai AI assistant"
LABEL org.opencontainers.image.source="https://github.com/rcconsult/ppxai"
LABEL org.opencontainers.image.version="1.13.10"

# Create non-root user for security
RUN groupadd --gid 1000 ppxai && \
    useradd --uid 1000 --gid 1000 --create-home ppxai

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Create data directory
RUN mkdir -p /home/ppxai/.ppxai && chown -R ppxai:ppxai /home/ppxai/.ppxai

# Switch to non-root user
USER ppxai
WORKDIR /home/ppxai

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Default port
EXPOSE 54320

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:54320/health')" || exit 1

# Run server
# Use --host 0.0.0.0 to bind to all interfaces (required for container networking)
CMD ["python", "-m", "ppxai.server.http", "--host", "0.0.0.0", "--port", "54320"]
