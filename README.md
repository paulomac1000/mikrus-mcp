# Mikrus MCP Server

[![CI](https://github.com/paulomac1000/mikrus-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/paulomac1000/mikrus-mcp/actions/workflows/ci.yml)
[![Docker](https://github.com/paulomac1000/mikrus-mcp/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/paulomac1000/mikrus-mcp/actions/workflows/docker-publish.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

MCP (Model Context Protocol) server for managing VPS servers via the [mikr.us](https://mikr.us) API **and** remote Linux servers over SSH. Built in Python, runs anywhere — locally, in Docker, or as a Claude Desktop integration.

## Contents

- [Requirements](#requirements)
- [Quick Start](#quick-start)
  - [Configure environment](#1-configure-environment)
  - [Run with Docker](#2-run-with-docker)
  - [Run locally](#3-run-locally-python-311)
- [Available Tools](#available-tools)
- [Multi-server Configuration](#multi-server-configuration)
- [Security Considerations](#security-considerations)
- [Claude Desktop Configuration](#claude-desktop-configuration)
- [Development](#development)
- [Architecture](#architecture)
- [Troubleshooting](#troubleshooting)
- [Notes](#notes)
- [License](#license)

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

**A — Single-server (mikr.us API only):**
```
MIKRUS_API_KEY=your_api_key_here
MIKRUS_SERVER_NAME=your_server_name_here
```

**B — Multi-server JSON (mikr.us + SSH):**
```bash
MCP_SERVERS={"your_srv": {"type": "mikrus", "key": "xxx", "srv": "your_srv"}, "myssh": {"type": "ssh", "host": "srvXX.mikr.us", "port": 22, "user": "root", "password": "secret"}}
MCP_DEFAULT_SERVER=your_srv
```

**C — SSH-only (no mikr.us account needed):**
```bash
MCP_SERVERS={"prod": {"type": "ssh", "host": "prod.example.com", "user": "admin", "ssh_key": "/home/user/.ssh/id_ed25519"}}
```

Variable name aliases (`MCP_*` and `MIKRUS_*` are interchangeable):
- `MCP_SERVERS` ←→ `MIKRUS_SERVERS`
- `MCP_DEFAULT_SERVER` ←→ `MIKRUS_DEFAULT_SERVER`

**IMPORTANT:** The `.env` file contains your API key / passwords. It is gitignored and must never be committed.

### 2. Run with Docker

Two approaches are available:

#### Pre-built image (recommended — no local build needed)

Pulls the published image from GitHub Container Registry:

```bash
docker run --rm \
  --env-file .env \
  ghcr.io/paulomac1000/mikrus-mcp:master
```

Or pass credentials directly:

```bash
docker run --rm \
  -e MIKRUS_API_KEY=your_key \
  -e MIKRUS_SERVER_NAME=your_server \
  ghcr.io/paulomac1000/mikrus-mcp:master
```

#### Local build (use when modifying the code or for development)

Build the image from source and run it:

```bash
# with docker compose (reads .env automatically)
docker compose up mikrus-mcp

# with docker compose and SSH key mount
docker compose run --rm \
  -v ~/.ssh/id_ed25519:/home/appuser/.ssh/id_ed25519:ro \
  mikrus-mcp

# or with plain docker build
docker build -t mikrus-mcp .
docker run --rm --env-file .env mikrus-mcp
```

The server communicates over `stdio` by default. Set `MCP_PORT` to enable SSE transport (see [Security Considerations](#security-considerations)).

> **Using SSH keys in Docker:** Mount your private key as a read-only volume:
> ```bash
> docker run --rm \
>   --env-file .env \
>   -v ~/.ssh/id_ed25519:/home/appuser/.ssh/id_ed25519:ro \
>   ghcr.io/paulomac1000/mikrus-mcp:master
> ```
> SSH keys must have permissions `600` or `400` and be readable by the `appuser` user inside the container (UID 1000). If your host user has a different UID, adjust ownership with `chown 1000:1000 ~/.ssh/id_ed25519` or use a less restrictive mode. Certificates can be mounted the same way.

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

All system tools accept an optional `server` parameter to target a specific configured
server (e.g. `server=myssh`). If omitted, the default server is used.

### Example usage

```text
User: What's the status of my server?
Agent: [calls get_server_info] →  server srv123, 2GB RAM, 20GB disk, expires 2026-06-01

User: Restart nginx on myssh
Agent: [calls manage_service name=nginx action=restart server=myssh] → nginx restarted
```

## Multi-server Configuration

You can manage multiple servers simultaneously by using the `MCP_SERVERS` JSON.
You can mix mikrus and SSH servers, or use SSH servers exclusively (no mikr.us account required).

```json
{
  "your_srv": {"type": "mikrus", "key": "xxx", "srv": "your_srv"},
  "myssh":   {"type": "ssh", "host": "192.168.1.10", "port": 22, "user": "root", "password": "secret", "sudo_password": "secret"}
}
```

#### SSH server fields

| Field | Required | Description |
|-------|----------|-------------|
| `type` | Yes | Must be `"ssh"` |
| `host` | Yes | SSH hostname or IP |
| `port` | No | SSH port (default: 22) |
| `user` | No | SSH username (default: `root`) |
| `password` | No | SSH password (if not using key auth) |
| `ssh_key` | No | Path to SSH private key file |
| `ssh_cert` | No | Path to SSH certificate signed by CA |
| `sudo_password` | No | Password for `sudo -S` (needed for journal tools if user lacks group privileges) |
| `timeout` | No | SSH timeout in seconds (default: 30) |
| `verify_host_key` | No | Verify SSH host key (default: `false`) |
| `known_hosts_file` | No | Path to known_hosts file (used when `verify_host_key=true`) |

#### mikr.us API server fields

| Field | Required | Description |
|-------|----------|-------------|
| `type` | Yes | Must be `"mikrus"` |
| `key` | Yes | API key from the mikr.us panel |
| `srv` | Yes | Server identifier (e.g. `srv123`) |

#### Usage

All tools accept an optional `server` parameter to target a specific configured server.
If `MCP_DEFAULT_SERVER` is not set, the **first server** in the JSON object is used as the default.

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

Add the following to your `claude_desktop_config.json`. Use absolute paths — Claude Desktop may run from a different working directory.

**With `.env` file (Docker):**

```json
{
  "mcpServers": {
    "mikrus": {
      "command": "docker",
      "args": [
        "run",
        "--rm",
        "--env-file",
        "/absolute/path/to/mikrus-mcp/.env",
        "ghcr.io/paulomac1000/mikrus-mcp:master"
      ]
    }
  }
}
```

**With inline credentials (Docker, no `.env` file):**

```json
{
  "mcpServers": {
    "mikrus": {
      "command": "docker",
      "args": [
        "run",
        "--rm",
        "-e", "MIKRUS_API_KEY=your_key",
        "-e", "MIKRUS_SERVER_NAME=your_server",
        "ghcr.io/paulomac1000/mikrus-mcp:master"
      ]
    }
  }
}
```

**Native Python (no Docker):**

```json
{
  "mcpServers": {
    "mikrus": {
      "command": "mikrus-mcp",
      "env": {
        "MIKRUS_API_KEY": "your_key",
        "MIKRUS_SERVER_NAME": "your_server"
      }
    }
  }
}
```

**Multi-server with SSH key mount:**

```json
{
  "mcpServers": {
    "mikrus": {
      "command": "docker",
      "args": [
        "run",
        "--rm",
        "-v", "/home/user/.ssh/id_ed25519:/home/appuser/.ssh/id_ed25519:ro",
        "-e", "MCP_SERVERS={\"prod\":{\"type\":\"ssh\",\"host\":\"10.0.0.5\",\"user\":\"admin\",\"ssh_key\":\"/home/appuser/.ssh/id_ed25519\"}}",
        "-e", "MCP_DEFAULT_SERVER=prod",
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
├── config.py        # Environment variable loader (dotenv) — single-server, multi-server, SSH-only
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

- **32 tools total:** 13 mikr.us API endpoints + 19 system management tools.
- **All write operations** are protected by input validation — no shell injection possible.
- **Errors are logged to `stderr`**, in compliance with the MCP specification.
- The mikr.us `/exec` endpoint has a 65-second client timeout (API limit is 60s).
- `/stats`, `/info`, `/serwery`, `/db`, and `/porty` have a 60-second API-side cache.
- Tool descriptions are optimized for LLM agents — each explains *when* and *why* to use the tool.

## License

MIT — see [LICENSE](LICENSE) for details.
