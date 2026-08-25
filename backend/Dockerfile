# =========================================================================
# Production Dockerfile for RecoverX Backend API & Background Worker
# =========================================================================

FROM python:3.11-slim AS builder

WORKDIR /app

# Install system dependencies needed for compiling native extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies in a virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt


# =========================================================================
# Final Production Runtime Stage
# =========================================================================
FROM python:3.11-slim AS runner

WORKDIR /app

# Install runtime PostgreSQL client library
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy virtualenv from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Create non-root unprivileged user and storage directory
RUN useradd -m -u 1001 recoverx && \
    mkdir -p /app/storage/documents && \
    chown -R recoverx:recoverx /app

# Copy application source
COPY --chown=recoverx:recoverx . /app/

USER recoverx

# Dynamic port handling for Render / cloud container hosting
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/health/live || exit 1

# Production command using dynamic PORT
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}

