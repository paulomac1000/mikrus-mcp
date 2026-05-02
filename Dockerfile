# syntax=docker/dockerfile:1

# ---------- Build stage ----------
FROM python:3.12-slim AS builder

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src/ ./src/

RUN pip install --no-cache-dir .

# ---------- Production stage ----------
FROM python:3.12-slim AS prod

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/mikrus-mcp /usr/local/bin/mikrus-mcp

USER appuser

STOPSIGNAL SIGINT

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

CMD ["mikrus-mcp"]

# ---------- Development/testing stage ----------
FROM builder AS dev

COPY tests/ ./tests/

RUN pip install --no-cache-dir -e ".[dev]"
