# Mikrus MCP Server

[![CI](https://github.com/paulomac1000/mikrus-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/paulomac1000/mikrus-mcp/actions/workflows/ci.yml)
[![Docker](https://github.com/paulomac1000/mikrus-mcp/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/paulomac1000/mikrus-mcp/actions/workflows/docker-publish.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

MCP (Model Context Protocol) server for managing VPS servers via the [mikr.us](https://mikr.us) API. Built in Python, runs anywhere — locally, in Docker, or as a Claude Desktop integration.

## Requirements

- Python 3.11+ (for local use) or Docker
- A [mikr.us](https://mikr.us) account with an API key
- Your server identifier (e.g. `your_srv`)

## Quick Start

### 1. Configure environment

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```
MIKRUS_API_KEY=your_api_key_here
MIKRUS_SERVER_NAME=your_server_name_here
# MIKRUS_API_URL=https://api.mikr.us   # optional, default shown
```

**IMPORTANT:** The `.env` file contains your API key. It is gitignored and must never be committed.

### 2. Run with Docker

First, configure your credentials. Either use a `.env` file (recommended) or pass variables directly.

**Option A — with `.env` file:**

```bash
cp .env.example .env
# edit .env with your MIKRUS_API_KEY and MIKRUS_SERVER_NAME
docker compose up mcp-server
```

**Option B — without `.env` file:**

```bash
docker compose run --rm \
  -e MIKRUS_API_KEY=your_key \
  -e MIKRUS_SERVER_NAME=your_server \
  mcp-server
```

Or with plain `docker run`:

```bash
docker run --rm \
  -e MIKRUS_API_KEY=your_key \
  -e MIKRUS_SERVER_NAME=your_server \
  ghcr.io/paulomac1000/mikrus-mcp:master
```

**Building locally:**

```bash
docker build -t mikrus-mcp .
docker run --rm -e MIKRUS_API_KEY=your_key -e MIKRUS_SERVER_NAME=your_server mikrus-mcp
```

The server communicates over `stdio` per the MCP specification.

### 3. Run locally (Python 3.11+)

```bash
pip install -e ".[dev]"
mikrus-mcp
```

## Available Tools

### mikr.us API tools

| Tool | API endpoint | Description |
|------|-------------|-------------|
| `get_server_info` | `/info` | Server info: ID, RAM, disk, expiration date, PRO plan status (cache=60s) |
| `list_servers` | `/serwery` | List all servers associated with the account (cache=60s) |
| `get_server_stats` | `/stats` | Usage stats: RAM, disk, uptime, load avg, processes (cache=60s) |
| `execute_command` | `/exec` | Execute a shell command on the server (60s API limit) |
| `restart_server` | `/restart` | Restart the VPS server |
| `get_logs` | `/logs` | Last 10 task log entries from the panel |
| `get_log_by_id` | `/logs/ID` | Details of a specific log entry by ID |
| `boost_server` | `/amfetamina` | Temporary resource boost (+512MB RAM for 30 min, free) |
| `get_db_info` | `/db` | Database access credentials (MySQL/PostgreSQL, cache=60s) |
| `get_ports` | `/porty` | Assigned TCP/UDP ports (cache=60s) |
| `get_cloud` | `/cloud` | Cloud services and statistics assigned to the account |
| `assign_domain` | `/domain` | Assign a domain to a port (use `-` for auto-generated subdomain) |

### System management tools

| Tool | Description |
|------|-------------|
| `read_file` | Read a text file from the server (up to 200 lines) |
| `write_file` | Write text content to a file (base64-safe transfer) |
| `manage_service` | Manage systemd services: status, start, stop, restart, enable, disable |
| `analyze_disk` | Disk usage overview (`df -h` + top-20 largest directories) |
| `check_port` | Check if a TCP port is listening and what process uses it |
| `manage_process` | List top processes by memory or kill a process by PID/name |
| `update_system` | Run system updates (apt update + apt upgrade) |

## Claude Desktop Configuration

Add the following to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "mikrus": {
      "command": "docker",
      "args": [
        "run",
        "--rm",
        "--env-file",
        "/path/to/mikrus-mcp/.env",
        "ghcr.io/paulomac1000/mikrus-mcp:master"
      ]
    }
  }
}
```

After restarting Claude Desktop, the 19 mikrus tools will be available for use.

## Development

### Setup

```bash
pip install -e ".[dev]"
```

### Run tests

```bash
pytest tests/ -v
```

All tests use [respx](https://github.com/lundberg/respx) to mock HTTP — no real network calls are made.

### Lint & type check

```bash
ruff check src/ tests/
mypy src/
```

### In Docker

```bash
docker compose run test
```

## Architecture

```
src/mikrus_mcp/
├── __init__.py      # Package version
├── __main__.py      # python -m mikrus_mcp entry point
├── config.py        # Environment variable loader (dotenv)
├── client.py        # Async HTTP client (httpx) for the mikr.us API
├── server.py        # MCP server with 19 tools (12 API + 7 system), stdio transport

tests/
├── test_client.py   # HTTP client tests (respx mock)
└── test_server.py   # Tool handler tests (respx mock)
```

## Notes

- 19 MCP tools total: 12 mikr.us API endpoints + 7 system management tools (file I/O, services, disk, processes, updates).
- System management tools execute commands via the mikr.us `/exec` endpoint with input validation and safe encoding.
- All write operations (`write_file`, `manage_service`, `manage_process`, `update_system`) are protected by input validation — no shell injection possible.
- Errors are logged to `stderr`, in compliance with the MCP specification.
- The `/exec` endpoint has a 65-second timeout on the client side (API limit is 60s).
- `/stats`, `/info`, `/serwery`, `/db`, and `/porty` have a 60-second cache on the API side.
- Tool descriptions are optimized for LLM agents — each explains *when* and *why* to use the tool.

## License

MIT — see [LICENSE](LICENSE) for details.
