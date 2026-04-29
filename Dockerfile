FROM python:3.12-slim AS builder

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY README.md ./
COPY src/ ./src/

RUN pip install --no-cache-dir .

# Production stage
FROM python:3.12-slim AS prod

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/mikrus-mcp /usr/local/bin/mikrus-mcp

CMD ["mikrus-mcp"]

# Development/testing stage
FROM prod AS dev

COPY pyproject.toml ./
COPY README.md ./
COPY src/ ./src/
COPY tests/ ./tests/

RUN pip install --no-cache-dir -e ".[dev]"
