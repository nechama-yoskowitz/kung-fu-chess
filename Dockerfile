# ── Kung-Fu Chess WebSocket Server ──────────────────────────────────────────
# Multi-stage build: keep the final image small.
#
# Stage 1 target: runnable server with PostgreSQL + Redis support.
# The graphical client (OpenCV) is NOT installed here — server only.

FROM python:3.12-slim AS base

LABEL maintainer="kungfu-chess"
LABEL description="Kung-Fu Chess multiplayer game server"

# Prevent .pyc files and enable unbuffered stdout/stderr for clean Docker logs.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# ── System dependencies ───────────────────────────────────────────────────────
# libpq-dev is needed by psycopg[binary] at runtime.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
    && rm -rf /var/lib/apt/lists/*

# ── Python dependencies ───────────────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir \
        --trusted-host pypi.org \
        --trusted-host pypi.python.org \
        --trusted-host files.pythonhosted.org \
        -r requirements.txt

# ── Application source ────────────────────────────────────────────────────────
# Copy only the game package (not tests, docs, assets, etc.)
COPY game/ ./game/

# ── Runtime configuration defaults ───────────────────────────────────────────
# These are overridden by docker-compose.yml environment section.
ENV KFC_DB_BACKEND=postgres \
    KFC_WS_HOST=0.0.0.0 \
    KFC_WS_PORT=8765 \
    KFC_LOG_LEVEL=INFO \
    KFC_REDIS_ENABLED=1

# ── Health check ─────────────────────────────────────────────────────────────
# TCP-only check: the WebSocket server accepts connections on 8765.
# Uses /dev/tcp bash built-in so no curl/netcat needed.
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD bash -c "echo > /dev/tcp/localhost/${KFC_WS_PORT:-8765}" 2>/dev/null || exit 1

EXPOSE 8765

CMD ["python", "-m", "game.server"]
