# ==============================================================================
# Multi-Stage Secure Dockerfile for Zero-Trust MLOps Financial Data Agent
# Base Image: Python 3.11 Slim (Debian Bookworm) - Minimal attack surface,
# glibc compatibility for PyArrow/Pandas wheels without build compilers in runtime.
# ==============================================================================

# ------------------------------------------------------------------------------
# Stage 1: Build & Dependency Isolation
# ------------------------------------------------------------------------------
FROM python:3.11-slim AS builder

# Security: Prevent Python from writing .pyc files and buffer outputs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /install

# Copy requirements file isolated from source code to leverage Docker layer caching
COPY requirements.txt .

# Create a virtual environment and install dependencies inside it
# Eliminates compilers and intermediate build files from leaking into runtime
RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --upgrade pip setuptools wheel && \
    /opt/venv/bin/pip install -r requirements.txt

# ------------------------------------------------------------------------------
# Stage 2: Hardened Runtime Stage
# ------------------------------------------------------------------------------
FROM python:3.11-slim AS runner

# Metadata labels for container governance and traceability
LABEL maintainer="DevSecOps Team" \
      pipeline="Zero-Trust MLOps" \
      component="financial-data-agent"

# Security & runtime environment configuration
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    HOME="/home/appuser"

# Principle of Least Privilege:
# 1. Create a dedicated system group and user with explicit non-root UID/GID (10001).
# 2. Assign /usr/sbin/nologin shell to block interactive shell logins.
# 3. Create isolated home directory for unprivileged runtime caching.
RUN groupadd --system --gid 10001 appgroup && \
    useradd --system --uid 10001 --gid appgroup --shell /usr/sbin/nologin --create-home --home-dir /home/appuser appuser

# Set working directory
WORKDIR /app

# Copy the prepared virtual environment from the builder stage
# Set ownership to root with read/executable access to prevent in-container tampering
COPY --from=builder /opt/venv /opt/venv

# Copy application script and ensure directory ownership belongs to non-root appuser
# so that the output parquet file can be securely written locally
COPY scraper.py /app/scraper.py
RUN chown -R appuser:appgroup /app /home/appuser && \
    chmod 755 /app

# Switch execution context from root to the non-privileged user (numeric UID for Kubernetes/CIS compliance)
USER 10001:10001

# Use Exec form for Entrypoint/CMD to ensure signals (SIGTERM/SIGINT) pass directly to Python for graceful shutdown
ENTRYPOINT ["python", "scraper.py"]
