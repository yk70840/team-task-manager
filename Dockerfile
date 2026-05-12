# ── Stage 1: dependency install ───────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /app

# Install uv for fast dependency resolution
RUN pip install --no-cache-dir uv

# Copy dependency manifests first for layer caching
COPY pyproject.toml uv.lock ./

# Install all runtime deps into the project venv
RUN uv sync --frozen --no-dev --no-install-project

# asyncpg is the async PostgreSQL driver.
# uv doesn't install pip into the venv, so use uv's own pip interface.
RUN uv pip install --no-cache-dir asyncpg

# ── Stage 2: runtime image ─────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Copy the installed packages from the builder stage
COPY --from=builder /app/.venv /app/.venv

# Copy application source
COPY app/ ./app/

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8765

# PORT is the standard Railway/Docker variable for the listening port.
CMD sh -c "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8765}"
