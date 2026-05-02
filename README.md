# Mikrus MCP Server

[![CI](https://github.com/paulomac1000/mikrus-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/paulomac1000/mikrus-mcp/actions/workflows/ci.yml)
[![Docker](https://github.com/paulomac1000/mikrus-mcp/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/paulomac1000/mikrus-mcp/actions/workflows/docker-publish.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

MCP (Model Context Protocol) server for managing VPS servers via the [mikr.us](https://mikr.us) API **and** remote Linux servers over SSH. Built in Python, runs anywhere — locally, in Docker, or as a Claude Desktop integration.

## Requirements

- Python 3.11+ (for local use) or Docker
- A [mikr.us](https://mikr.us) account with an API key **or** any SSH-accessible Linux server
- Your server identifier (e.g. `your_srv`) or SSH host

## Quick Start

### 1. Configure environment

```bash
cp .env.example .env
```

Edit `.env` with your credentials. Three modes are supported:

**A — Legacy single-server (mikr.us API only):**
```
MIKRUS_API_KEY=your_api_key_here
MIKRUS_SERVER_NAME=your_server_name_here
```

**B — Multi-server JSON (mikr.us + SSH):**
```bash
MCP_SERVERS={"ssh1": {"type": "ssh", "host": "srvXX.mikr.us", "port": 22, "user": "root", "password": "secret", "sudo_password": "secret"}}
MCP_DEFAULT_SERVER=ssh1
```

**C — SSH-only (no mikr.us account needed):**
```bash
MCP_SERVERS={"prod": {"type": "ssh", "host": "prod.example.com", "user": "admin", "ssh_key": "/home/user/.ssh/id_ed25519"}}
```

Environment variable aliases (neutral `MCP_*` names take priority over legacy `MIKRUS_*`):
- `MCP_SERVERS` → `MIKRUS_SERVERS`
- `MCP_DEFAULT_SERVER` → `MIKRUS_DEFAULT_SERVER`

**IMPORTANT:** The `.env` file contains your API key / passwords. It is gitignored and must never be committed.

### 2. Run with Docker

**Option A — with `.env` file:**

```bash
cp .env.example .env
# edit .env with your credentials
docker compose up mikrus-mcp-dev
```

**Option B — without `.env` file:**

```bash
docker compose run --rm \
  -e MIKRUS_API_KEY=your_key \
  -e MIKRUS_SERVER_NAME=your_server \
  mikrus-mcp-dev
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

The server communicates over `stdio` by default. Set `MCP_PORT` to enable SSE transport (see [Security Considerations](#security-considerations)).

### 3. Run locally (Python 3.11+)

```bash
pip install -e ".[dev]"
mikrus-mcp
```

## Available Tools

### Discovery

| Tool | Description |
|------|-------------|
| `list_configured_servers` | List all configured servers, their types, and connection status. Use this first to discover available servers. |

### mikr.us API tools (mikrus servers only)

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

### System management tools (mikrus + SSH servers)

| Tool | Description |
|------|-------------|
| `read_file` | Read a text file from the server (up to 200 lines) |
| `write_file` | Write text content to a file (base64-safe transfer) |
| `manage_service` | Manage systemd services: status, start, stop, restart, enable, disable |
| `analyze_disk` | Disk usage overview (`df -h` + top-20 largest directories) |
| `check_port` | Check if a TCP port is listening and what process uses it |
| `manage_process` | List top processes by memory or kill a process by PID/name |
| `update_system` | Run system updates (`apt update && apt upgrade -y`) |
| `list_directory` | List directory contents (`ls -la`) |
| `tail_file` | Read last N lines from a text file (max 500) |
| `search_in_files` | Search for a pattern in files under a path (`grep -r`) |
| `get_memory_info` | Show memory usage (`free -h`) |
| `get_network_info` | Show network interfaces and listening TCP ports |
| `get_process_tree` | Show running processes in a tree view (`ps auxf`) |

### Docker tools (mikrus + SSH servers, requires Docker access)

| Tool | Description |
|------|-------------|
| `list_docker_containers` | List all Docker containers with status and image |
| `get_docker_logs` | Fetch recent logs from a Docker container |
| `get_docker_stats` | Show resource usage stats for Docker containers |

### Journal tools (mikrus + SSH servers, may require `sudo_password`)

| Tool | Description |
|------|-------------|
| `get_journal_logs` | Fetch systemd journal logs for a specific service unit |
| `find_system_errors` | Find error-level journal entries from the last N hours |
| `search_journal_logs` | Search journal logs for a keyword or phrase |

> **Note about journal tools:** If the remote user is not in the `systemd-journal` or `adm` group, journal commands will fail. To fix this, add `sudo_password` to the SSH server configuration. If `sudo_password` is omitted, the tool will still work but returns a helpful hint for the user when privileges are insufficient.

## Multi-server Configuration

You can manage multiple servers simultaneously by using the `MCP_SERVERS` JSON:

```json
{
  "your_srv": {"type": "mikrus", "key": "xxx", "srv": "your_srv"},
  "myssh":   {"type": "ssh", "host": "192.168.1.10", "port": 22, "user": "root", "password": "secret", "sudo_password": "secret"}
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `type` | Yes | `mikrus` or `ssh` |
| `key` / `srv` | Yes (mikrus) | API key and server name |
| `host` | Yes (ssh) | SSH hostname or IP |
| `port` | No (ssh) | SSH port (default: 22) |
| `user` | No (ssh) | SSH username (default: `root`) |
| `password` | No (ssh) | SSH password (if not using key auth) |
| `ssh_key` | No (ssh) | Path to SSH private key file |
| `ssh_cert` | No (ssh) | Path to SSH certificate signed by CA |
| `sudo_password` | No (ssh) | Password for `sudo -S` (needed for journal tools if user lacks group privileges) |
| `timeout` | No (ssh) | SSH timeout in seconds (default: 30) |
| `verify_host_key` | No (ssh) | Verify SSH host key (default: `false`) |
| `known_hosts_file` | No (ssh) | Path to known_hosts file (used when `verify_host_key=true`) |

All tools accept an optional `server` parameter to target a specific configured server.

## Security Considerations

This MCP server grants full system access to configured servers. Treat it as a **privileged remote administration tool**.

### SSE Transport
- By default, SSE listens on `127.0.0.1` only.
- Binding to `0.0.0.0` requires `MCP_UNSAFE_PUBLIC_ACCESS_CONFIRMED=1`.
- **Never expose SSE to the internet without authentication.** Use a reverse proxy (nginx, Traefik) with TLS and basic auth if remote access is needed.

### SSH Security
- `verify_host_key` defaults to `false` for ease of use. In production, set it to `true` and provide a `known_hosts_file` to prevent MITM attacks.
- `sudo_password` is fed via `asyncssh.create_process` + stdin, **never** via shell string interpolation, so it won't appear in `ps aux`.
- SSH private keys mounted into Docker must have permissions `600` or `400`.

### Input Validation
- All file paths are validated against traversal (`..`) and forbidden paths (`/etc/shadow`, etc.).
- Dangerous commands (`rm -rf /`, `mkfs`, `dd if=`) are blocked before execution.
- Service names, container names, ports, and domains are validated with strict regex patterns.
- File writes outside `/home`, `/var/www`, `/opt`, `/tmp`, `/srv`, `/var/log` trigger a warning.

### Credentials
- API keys and passwords are loaded from environment variables or `.env` (gitignored).
- Never commit credentials to version control.

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

After restarting Claude Desktop, the 32 mikrus tools will be available for use.

## Development

### Setup

```bash
pip install -e ".[dev]"
```

### Run tests

```bash
pytest tests/ -v
```

All HTTP tests use [respx](https://github.com/lundberg/respx) to mock the mikr.us API. SSH tests mock `asyncssh` so no real network calls are made.

### Lint & type check

```bash
ruff check src/ tests/
ruff format --check src/ tests/
mypy src/
bandit -r src/
```

### In Docker

```bash
docker compose run --rm test
```

## Architecture

```
src/mikrus_mcp/
├── __init__.py      # Package version
├── __main__.py      # python -m mikrus_mcp entry point
├── config.py        # Environment variable loader (dotenv) — legacy + multi-server + SSH-only
├── validators.py    # Centralized input validation (path, port, service, container, domain)
├── client.py        # Async HTTP client (httpx) + SSH client (asyncssh)
└── server.py        # MCP server with 32 tools, stdio + SSE transport, partial startup

tests/
├── test_client.py       # HTTP client tests (respx mock)
├── test_server.py       # Tool handler tests (respx mock)
├── test_config.py       # Configuration loader tests
├── test_ssh_client.py   # SSH client tests (asyncssh mock)
└── test_multi_server.py # Multi-server routing & partial startup tests
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `No servers available` | Check that `MIKRUS_API_KEY` + `MIKRUS_SERVER_NAME` or `MCP_SERVERS` JSON is set correctly. |
| `SSH key not found` | Verify the path in `ssh_key` is absolute and accessible from the container (mount it as a volume). |
| `Journal access denied` | Add `sudo_password` to the SSH server config, or add the user to the `systemd-journal` / `adm` group. |
| `Port must be 1-65535` | The `MCP_PORT` env var must be a valid TCP port number. |
| `Refusing to start on 0.0.0.0` | Set `MCP_HOST=127.0.0.1` or set `MCP_UNSAFE_PUBLIC_ACCESS_CONFIRMED=1` (not recommended). |
| Partial startup warning | One or more servers failed to connect. Check logs — other servers are still available. |

## Notes

- **32 MCP tools total:** 13 mikr.us API endpoints + 19 system management tools (file I/O, services, disk, processes, Docker, journal, updates, network, memory).
- **Multi-server support:** Manage mikr.us VPS and remote SSH servers from a single MCP instance.
- **SSH-only mode:** Works on any Debian/Ubuntu server without a mikr.us account.
- **Optional `sudo_password`:** Journal tools automatically use `sudo -S` when configured. If omitted, they return a helpful hint when privileges are insufficient.
- **System management tools** execute commands via the mikr.us `/exec` endpoint or SSH with input validation and safe encoding.
- **All write operations** (`write_file`, `manage_service`, `manage_process`, `update_system`) are protected by input validation — no shell injection possible.
- **Errors are logged to `stderr`**, in compliance with the MCP specification.
- **The `/exec` endpoint** has a 65-second timeout on the client side (API limit is 60s).
- **`/stats`, `/info`, `/serwery`, `/db`, and `/porty`** have a 60-second cache on the API side.
- **Tool descriptions are optimized for LLM agents** — each explains *when* and *why* to use the tool.

## License

MIT — see [LICENSE](LICENSE) for details.
