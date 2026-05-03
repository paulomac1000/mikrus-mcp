# Agent Guidelines

## Project Overview

This is an MCP (Model Context Protocol) server for managing VPS servers via the [mikr.us](https://mikr.us) API **and** remote Linux servers over SSH. It is written in Python and runs either locally or inside Docker.

## Build & Run

```bash
# Local development
pip install -e ".[dev]"
pytest tests/ -v
ruff check src/ tests/
mypy src/
bandit -r src/

# Docker
docker build -t mikrus-mcp .
docker run --rm --env-file .env mikrus-mcp
```

## Architecture

- `src/mikrus_mcp/config.py` — loads configuration from environment variables (`.env`). Supports single-server, multi-server JSON, and SSH-only modes.
- `src/mikrus_mcp/validators.py` — centralized input validation (path, port, service, container, domain, content size, dangerous commands).
- `src/mikrus_mcp/client.py` — async HTTP client for the mikr.us API (`httpx`) + SSH client (`asyncssh`) with certificate support.
- `src/mikrus_mcp/server.py` — MCP server with 32 tools, `stdio` + SSE transport, partial startup graceful degradation.
- `tests/` — integration tests with mocked API (`respx`) and mocked `asyncssh`.

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
| `MCP_SERVERS` / `MIKRUS_SERVERS` | Yes* | JSON object with one or more server configs |
| `MCP_DEFAULT_SERVER` / `MIKRUS_DEFAULT_SERVER` | No | Default server name (auto-picks first if omitted) |
| `MIKRUS_API_KEY` | Yes* | API key from the mikr.us panel (single-server mode) |
| `MIKRUS_SERVER_NAME` | Yes* | Server identifier (single-server mode) |
| `MIKRUS_API_URL` | No | Custom API endpoint (default: `https://api.mikr.us`) |
| `MCP_PORT` | No | Enable SSE transport on this port |
| `MCP_HOST` | No | SSE bind address (default: `127.0.0.1`) |
| `MCP_UNSAFE_PUBLIC_ACCESS_CONFIRMED` | No | Required to bind SSE to `0.0.0.0` |
| `LOG_LEVEL` | No | Logging level (default: `INFO`) |

*Either `MCP_SERVERS` or `MIKRUS_API_KEY`+`MIKRUS_SERVER_NAME` is required.

## SSH Server Config Fields

| Field | Required | Description |
|-------|----------|-------------|
| `type` | Yes | Must be `"ssh"` |
| `host` | Yes | SSH hostname or IP |
| `port` | No | SSH port (default: 22) |
| `user` | No | SSH username (default: `root`) |
| `password` | No | SSH password |
| `ssh_key` | No | Path to SSH private key |
| `ssh_cert` | No | Path to SSH certificate (signed by CA) |
| `sudo_password` | No | Password for `sudo -S` (journal tools) |
| `timeout` | No | SSH connection timeout in seconds (default: 30) |
| `verify_host_key` | No | Verify SSH host key (default: `false`) |
| `known_hosts_file` | No | Path to known_hosts file |

## Entry Points

- `mikrus-mcp` CLI command (defined in `pyproject.toml`).
- `python -m mikrus_mcp` (via `__main__.py`).
