# Dockerfile — AI Native Business Data Agent OS (API Server)
# Multi-stage build: Python backend for the Trusted Loop HTTP surface.
#
# Build context: repository root (ai-native-business-data-agent-os/)
#
# Usage:
#   docker build -t agent-os-api .
#   docker run -p 8000:8000 --env-file .env agent-os-api

# ── Stage 1: Python backend ──────────────────────────────────────────────────
FROM python:3.12-slim AS backend

# Prevent Python from writing .pyc files and enable unbuffered stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# System dependencies for psycopg (libpq) and general build needs
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (layer caching)
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e ".[http,postgres]"

# Copy the PYTHONPATH-based monorepo packages.
# The Makefile defines:
#   PYTHONPATH = packages/contracts/src:packages/os_core/src:packages/persistence/src:
#                packages/sdk/src:action_connectors:apps/api_server/src
COPY packages/contracts/ ./packages/contracts/
COPY packages/os_core/ ./packages/os_core/
COPY packages/persistence/ ./packages/persistence/
COPY packages/sdk/ ./packages/sdk/

# Action connectors (manual_review, action_record)
COPY action_connectors/ ./action_connectors/

# Domain packs (content_commerce metrics, providers, SQL templates, seed data)
COPY domain_packs/ ./domain_packs/

# API server application code
COPY apps/api_server/ ./apps/api_server/

# Set the PYTHONPATH to match the Makefile monorepo layout
ENV PYTHONPATH="/app/packages/contracts/src:/app/packages/os_core/src:/app/packages/persistence/src:/app/packages/sdk/src:/app/action_connectors:/app/apps/api_server/src"

# Default environment: postgres-backed stores, sqlite executor for real SQL
ENV AGENT_OS_STORE_BACKEND=postgres \
    AGENT_OS_EXECUTOR=sqlite \
    AGENT_OS_DOMAIN_PACK=domain_packs/content_commerce

EXPOSE 8000

# Health check: FastAPI /docs endpoint is always available
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run with uvicorn; 0.0.0.0 for container networking
CMD ["python", "-m", "uvicorn", "agent_os_api.http_app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
