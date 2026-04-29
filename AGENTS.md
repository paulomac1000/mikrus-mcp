# Agent Guidelines

## Project Overview

This is an MCP (Model Context Protocol) server for managing VPS servers via the [mikr.us](https://mikr.us) API. It is written in Python and runs either locally or inside Docker.

## Build & Run

```bash
# Local development
pip install -e ".[dev]"
pytest tests/ -v

# Docker
docker build -t mikrus-mcp .
docker run --rm --env-file .env mikrus-mcp
```

## Architecture

- `src/mikrus_mcp/config.py` — loads configuration from environment variables (`.env`).
- `src/mikrus_mcp/client.py` — async HTTP client for the mikr.us API (`httpx` + timeouts).
- `src/mikrus_mcp/server.py` — MCP server with 12 tools and `stdio` transport.
- `tests/` — integration tests with mocked API (`respx`).

## Coding Conventions

- Language: **100% English** in code, comments, docstrings, and log messages.
- Formatter / Linter: `ruff`
- Type checker: `mypy` (strict mode)
- Test framework: `pytest` + `pytest-asyncio`
- HTTP mocking: `respx`
- Line length: 100 characters
- Target Python: 3.11+

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `MIKRUS_API_KEY` | Yes | API key from the mikr.us panel |
| `MIKRUS_SERVER_NAME` | Yes | Server identifier (e.g. `your_srv`) |
| `MIKRUS_API_URL` | No | Custom API endpoint (default: `https://api.mikr.us`) |

## Entry Points

- `mikrus-mcp` CLI command (defined in `pyproject.toml`).
- `python -m mikrus_mcp` (via `__main__.py`).
