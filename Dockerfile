FROM python:3.12.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MCP_TRANSPORT=stdio

RUN groupadd --system --gid 10001 appuser \
    && useradd --system --uid 10001 --gid appuser --home-dir /app --shell /usr/sbin/nologin appuser

ARG APP_WHEEL_SHA256
COPY wheelhouse/ /wheelhouse/
RUN set -eu; \
    test -n "$APP_WHEEL_SHA256"; \
    wheel="$(find /wheelhouse -maxdepth 1 -name 'mikrus_mcp-2.0.0-*.whl' -print -quit)"; \
    test -n "$wheel"; \
    printf '%s  %s\n' "$APP_WHEEL_SHA256" "$wheel" | sha256sum --check -; \
    python -m pip install --no-cache-dir --no-index --find-links=/wheelhouse "$wheel"; \
    python -m pip check; \
    rm -rf /wheelhouse

USER 10001:10001
STOPSIGNAL SIGINT
ENTRYPOINT ["mikrus-mcp"]
