# Mikrus MCP Server

[![CI](https://github.com/paulomac1000/mikrus-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/paulomac1000/mikrus-mcp/actions/workflows/ci.yml)
[![AI Skills](https://github.com/paulomac1000/mikrus-mcp/actions/workflows/ai-skills-adoption.yml/badge.svg)](https://github.com/paulomac1000/mikrus-mcp/actions/workflows/ai-skills-adoption.yml)
[![Python 3.12–3.14](https://img.shields.io/badge/python-3.12%E2%80%933.14-blue)](https://www.python.org/)
[![Version 2.0.0](https://img.shields.io/badge/version-2.0.0-blueviolet)](https://github.com/paulomac1000/mikrus-mcp)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

A hardened [Model Context Protocol](https://modelcontextprotocol.io/) server for managing [mikr.us](https://mikr.us/) VPS instances and remote Linux hosts over SSH.

`mikrus-mcp` exposes a bounded set of administration capabilities through one policy-enforced invocation path. It supports local `stdio` and authenticated loopback-only Streamable HTTP, separates read operations from mutations, binds privileged actions to an exact target identity and resource, and keeps raw shell execution out of the public MCP surface.

> **Version 2.0 is intentionally stricter than 1.x.** Python 3.12+ is required, legacy HTTP+SSE is removed, SSH host verification is enabled by default, mutations require explicit write enablement and short-lived server-side approvals, and broad legacy management tools have been replaced with operation-specific capabilities.

## Contents

- [Highlights](#highlights)
- [Requirements](#requirements)
- [Quick start](#quick-start)
- [MCP client configuration](#mcp-client-configuration)
- [Available tools](#available-tools)
- [Multi-server configuration](#multi-server-configuration)
- [Authorization and approvals](#authorization-and-approvals)
- [Transports](#transports)
- [Result format](#result-format)
- [Security model](#security-model)
- [Development](#development)
- [Architecture](#architecture)
- [Troubleshooting](#troubleshooting)
- [Standards and migration](#standards-and-migration)
- [License](#license)

## Highlights

- **mikr.us + SSH** — manage mikr.us API targets and ordinary SSH-accessible Linux hosts from the same MCP server.
- **One invocation kernel** — validation, authorization, target binding, approvals, deadlines, concurrency, sanitization, provenance, and failure classification are enforced in one application-owned path.
- **Two-phase authorization** — selector and data-policy checks happen before target resolution; exact backend identity and resource checks happen after resolution.
- **Safe-by-default mutations** — writes are disabled by default, never automatically retried, and require a one-time approval bound to principal, capability, resolved target identity, resource, and normalized arguments.
- **Verified SSH identity** — host-key verification is enabled by default; mutation identity includes the verified SHA-256 host-key fingerprint.
- **No public raw shell tool** — privileged operations are exposed as bounded, operation-specific tools with validation.
- **Reproducible builds** — committed hashed dependency locks are maintained for Linux x64 on CPython 3.12, 3.13, and 3.14.
- **Exact artifact verification** — CI builds and exercises the exact wheel and Linux/amd64 container artifact.
- **Pinned standards authority** — repository contracts are aligned with the pinned `ai-skills@main` stable revision recorded in `ai-skills.lock.yaml`.

## Requirements

For local execution:

- Python **3.12, 3.13, or 3.14**
- a mikr.us API key and server identifier, **or** an SSH-accessible Linux host
- for SSH writes: a verified host key and a target with the required POSIX/Python primitives

Docker can be used instead of installing Python directly.

## Quick start

### 1. Clone and create an environment

```bash
git clone https://github.com/paulomac1000/mikrus-mcp.git
cd mikrus-mcp

python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install .
```

For repository development, use the committed hashed development lock instead of resolving dependencies ad hoc. See [Development](#development).

### 2. Configure a single mikr.us server

```bash
export MIKRUS_API_KEY='replace-me'
export MIKRUS_SERVER_NAME='srv123'
```

The single-server form is the smallest configuration. For SSH or multiple targets use `MCP_SERVERS`; examples are below.

### 3. Start the MCP server

```bash
.venv/bin/python -m mikrus_mcp
```

`stdio` is the default transport, so this command is suitable for desktop MCP clients which launch the server as a subprocess.

### 4. Build and run with Docker

```bash
docker build -t mikrus-mcp:2.0.0 .

docker run --rm \
  -e MIKRUS_API_KEY='replace-me' \
  -e MIKRUS_SERVER_NAME='srv123' \
  mikrus-mcp:2.0.0
```

Published release images are promoted by immutable digest. Prefer a release tag or digest over an unpinned moving tag in production.

## MCP client configuration

A typical desktop-client configuration can launch the project directly through Python:

```json
{
  "mcpServers": {
    "mikrus": {
      "command": "/absolute/path/to/mikrus-mcp/.venv/bin/python",
      "args": ["-m", "mikrus_mcp"],
      "env": {
        "MIKRUS_API_KEY": "replace-me",
        "MIKRUS_SERVER_NAME": "srv123"
      }
    }
  }
}
```

Use absolute paths. GUI applications frequently start with a different working directory than your shell.

For Docker-based clients, point the MCP command at `docker run` and pass credentials through an environment file or secret mechanism rather than embedding long-lived credentials in the client configuration.

## Available tools

The supported catalog contains **34 application-owned capabilities**. Runtime registration is configuration-aware: tools that do not apply to any configured backend, or mutations disabled by policy, are omitted from the public tool list and remain visible in the capability catalog with an inactive reason.

### Discovery

| Tool | Type | Description |
| --- | --- | --- |
| `list_configured_servers` | Read | List configured targets and their current connection state. |
| `describe_mikrus_capabilities` | Read | Return the supported capability catalog and policy metadata. |

### mikr.us API tools

These capabilities require at least one configured `mikrus` target.

| Tool | Type | Description |
| --- | --- | --- |
| `get_server_info` | Read | Basic VPS information such as RAM, disk, expiry, and server state. |
| `list_servers` | Read | List servers associated with the mikr.us account. |
| `get_server_stats` | Read | Retrieve resource and runtime statistics. |
| `restart_server` | Mutation | Restart the selected VPS. |
| `get_logs` | Read | Fetch recent mikr.us task logs. |
| `get_log_by_id` | Read | Fetch one task log by ID. |
| `boost_server` | Mutation | Request the supported temporary resource boost. |
| `get_db_info` | Sensitive read | Retrieve database connection information; credential fields are protected by the response sanitizer. |
| `get_ports` | Read | Show assigned ports. |
| `get_cloud` | Read | Show cloud services associated with the account. |
| `assign_domain` | Mutation | Assign a domain or generated subdomain to a port. |

### Linux system tools

These capabilities operate through the configured backend abstraction and are available where the target supports them.

| Tool | Type | Description |
| --- | --- | --- |
| `read_file` | Sensitive read | Read a bounded text file from an allowed path. |
| `write_file` | Mutation | Atomically write a file using no-follow directory traversal. |
| `get_service_status` | Read | Inspect one systemd service. |
| `change_service_state` | Mutation | Start, stop, restart, enable, or disable a validated service. |
| `analyze_disk` | Read | Inspect filesystem usage. |
| `check_port` | Read | Check whether a TCP port is listening and identify the owning process where available. |
| `list_processes` | Sensitive read | List processes using a bounded output contract. |
| `terminate_process` | Mutation | Terminate a validated process target. |
| `update_system` | Mutation | Run the supported system-update workflow. |
| `list_directory` | Sensitive read | List a validated directory. |
| `tail_file` | Sensitive read | Read the bounded tail of a text file. |
| `search_in_files` | Sensitive read | Search within a validated path. |
| `get_memory_info` | Read | Show memory usage. |
| `get_network_info` | Sensitive read | Show network interfaces and listening sockets. |
| `get_process_tree` | Sensitive read | Show the process tree. |

### Docker tools

| Tool | Type | Description |
| --- | --- | --- |
| `list_docker_containers` | Sensitive read | List containers and current state. |
| `get_docker_logs` | Sensitive read | Fetch bounded recent logs for one container. |
| `get_docker_stats` | Read | Show container resource statistics. |

### Journal tools

| Tool | Type | Description |
| --- | --- | --- |
| `get_journal_logs` | Sensitive read | Fetch bounded journal output for one unit. |
| `find_system_errors` | Sensitive read | Find recent error-level journal events. |
| `search_journal_logs` | Sensitive read | Search journal output for a bounded term. |

Journal access depends on the remote account's permissions. A configured `sudo_password` can be used when the account is not already allowed to read the journal; the password is sent over process stdin rather than interpolated into the shell command.

## Multi-server configuration

Set `MCP_SERVERS` to a JSON object keyed by the public target alias.

### Mixed mikr.us + SSH example

```bash
export MCP_SERVERS='{
  "vps": {
    "type": "mikrus",
    "key": "replace-me",
    "srv": "srv123"
  },
  "host": {
    "type": "ssh",
    "host": "server.example.com",
    "port": 22,
    "user": "admin",
    "ssh_key": "/home/me/.ssh/id_ed25519",
    "known_hosts_file": "/home/me/.ssh/known_hosts"
  }
}'
export MCP_DEFAULT_SERVER='vps'
```

### SSH target fields

| Field | Required | Default | Notes |
| --- | --- | --- | --- |
| `type` | yes | — | Must be `"ssh"`. |
| `host` | yes | — | Hostname or IP address. |
| `port` | no | `22` | TCP port, 1–65535. |
| `user` | no | `root` | SSH username. |
| `password` | no | — | Password authentication. Prefer key authentication where possible. |
| `ssh_key` | no | — | Existing private-key file; must be protected from group/other access. |
| `ssh_cert` | no | — | Optional SSH certificate. |
| `sudo_password` | no | — | Optional password for operation-specific `sudo -S` commands. |
| `known_hosts_file` | no | AsyncSSH default policy | Optional explicit `known_hosts` file. |
| `timeout` | no | `30` | Connection/operation timeout input, 1–300 seconds. |
| `verify_host_key` | no | `true` | Host-key verification is enabled by default. |

Disabling SSH host verification requires `MCP_ALLOW_INSECURE_SSH=1` and is limited to read-only development use. Startup fails if writes are enabled while an SSH target has host verification disabled.

### mikr.us target fields

| Field | Required | Default | Notes |
| --- | --- | --- | --- |
| `type` | yes | — | Must be `"mikrus"`. |
| `key` | yes | — | API key. |
| `srv` | yes | — | Stable mikr.us server ID. |
| `api_url` | no | `https://api.mikr.us` | Must use HTTPS. |

If `MCP_DEFAULT_SERVER` is omitted, the first configured target is used as the default selector.

## Authorization and approvals

### Scope model

The built-in single-operator default includes these read-policy axes:

```text
tool:*
target:*
target-id:*
resource:*
data:*
```

Mutations additionally require their capability scope and `write:server`.

If you set `MCP_ALLOWED_SCOPES` yourself, it replaces the default set. A legacy `tool:*,target:*` override is therefore intentionally insufficient for target-backed operations after the resolved-identity authorization phase.

The important scope families are:

- `tool:<capability>` — allows the capability itself.
- `target:<selector>` — allows the configured public target alias before target resolution.
- `target-id:<resolved-identity>` — allows the exact resolved backend identity.
- `resource:<capability>:sha256:<digest>` — allows an exact normalized resource; `resource:*` is the explicit wildcard profile.
- `data:<classification>` — permits the manifest confidentiality class; `data:*` is the explicit wildcard profile.
- `write:server` — enables mutation authorization when process write policy is also enabled.

### Enabling mutations

Mutations require both process policy and a matching short-lived approval record:

```bash
export MCP_WRITE_ENABLED=true
export MCP_APPROVAL_FILE="$PWD/.mikrus-approvals.json"
```

Approval records are created from the trusted operator shell, not by the model. The helper resolves the target before persisting the record; for SSH this binds the current verified host-key fingerprint.

General form:

```bash
.venv/bin/python scripts/approval.py \
  --file "$MCP_APPROVAL_FILE" \
  --capability '<capability>' \
  --principal '<principal>' \
  --server '<configured-alias>' \
  --resource '<normalized-resource>' \
  --arguments-json '<JSON object without server>' \
  --ttl-seconds 60
```

Approvals expire quickly (default 60 seconds, maximum 300 seconds), are consumed once, and are matched against principal, capability, exact resolved target identity, resource, and normalized argument digest.

## Transports

### stdio

`stdio` is the default and recommended transport for local desktop integrations:

```bash
export MCP_TRANSPORT=stdio
.venv/bin/python -m mikrus_mcp
```

Protocol traffic owns stdout; diagnostics are written to stderr.

### Streamable HTTP

Streamable HTTP is deliberately restricted to literal loopback addresses and requires a protected bearer-token file.

```bash
umask 077
python -c 'import secrets; print(secrets.token_urlsafe(48))' > .mcp-http-token
chmod 600 .mcp-http-token

export MCP_TRANSPORT=streamable-http
export MCP_HOST=127.0.0.1
export MCP_PORT=8000
export MCP_HTTP_BEARER_TOKEN_FILE="$PWD/.mcp-http-token"

.venv/bin/python -m mikrus_mcp
```

Clients connect to `http://127.0.0.1:8000/mcp` with `Authorization: Bearer <token>`.

Remote/public HTTP exposure is not part of the supported security profile. Legacy two-endpoint HTTP+SSE and the unauthenticated REST bridge were removed in 2.0.

## Result format

Application results use a structured success/error envelope and include correlation/provenance metadata.

Representative success:

```json
{
  "success": true,
  "data": {
    "param_ram": "1024"
  },
  "_meta": {
    "request_id": "6a5c...",
    "capability": "get_server_info",
    "capability_version": "2.0.0",
    "source": "mikrus-mcp",
    "artifact": "mikrus-mcp==2.0.0",
    "target": "srv123",
    "target_identity": "mikrus:srv123",
    "backend": "mikrus",
    "duration_ms": 42
  }
}
```

Representative failure:

```json
{
  "success": false,
  "error": {
    "code": "RATE_LIMITED",
    "message": "request rate limit exceeded",
    "retryable": true,
    "retry_after_seconds": 2.0
  },
  "_meta": {
    "request_id": "9b8f...",
    "capability": "get_server_info",
    "source": "mikrus-mcp"
  }
}
```

Metadata is only included when it is safe and actually known. For example, a pre-resolution authorization failure does not disclose the backend's resolved identity.

Result limits are enforced against the serialized application envelope, including metadata, rather than only the nested `data` value.

## Security model

`mikrus-mcp` is a privileged administration service. Treat its process environment, bearer-token file, SSH keys, approval registry, and target credentials as secrets.

Key defaults:

- no fallback from a failed target to another configured target;
- SSH host-key verification enabled by default;
- loopback-only authenticated Streamable HTTP;
- mutations disabled unless `MCP_WRITE_ENABLED=true`;
- one-time server-side approvals for every public mutation;
- no automatic mutation retries after timeout, disconnect, rate limit, or ambiguous completion;
- no public arbitrary-command tool;
- component-safe no-follow remote file writes;
- bounded request, response, output, concurrency, and deadline behavior;
- sensitive response fields sanitized before model-visible serialization.

Read [SECURITY.md](SECURITY.md) before enabling writes or deploying the server outside a disposable environment.

## Development

The repository maintains hashed Linux x64 development locks for every supported Python lane. For the default 3.12 lane:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install "pip==26.1.2"
.venv/bin/python -m pip install --require-hashes -r requirements-dev-linux-x64-py312.lock
.venv/bin/python -m pip install --no-deps .
```

Run the fast credential-free gate:

```bash
.venv/bin/python scripts/core_gate.py
```

Run the complete local repository gate:

```bash
.venv/bin/python scripts/ci.py
```

Run a focused test:

```bash
.venv/bin/python -m pytest tests/unit/test_kernel.py -q
```

Build the wheel:

```bash
.venv/bin/python -m build --wheel
```

`requirements-runtime.in` and `requirements-dev.in` are human-edited inputs. `requirements-*-linux-x64-py3*.lock` files are generated exact hashed graphs and should not be hand-edited.

Hosted CI additionally validates the supported Python matrix, manifests, documentation, static security policy, exact wheel behavior, official MCP transports, dependency locks, and Linux/amd64 container behavior.

## Architecture

```text
MCP client
   |
   |  stdio / authenticated loopback Streamable HTTP
   v
MCP registration + transport boundary
   |
   v
InvocationKernel
   |-- argument validation
   |-- principal / selector authorization
   |-- target resolution
   |-- resolved identity / resource authorization
   |-- write policy + one-time approval
   |-- deadline + concurrency policy
   |-- adapter execution
   |-- sanitization + provenance + structured errors
   |
   v
TargetRegistry
   |                    |
   v                    v
mikr.us API adapter   SSH adapter
```

Backend adapters do not own MCP policy. Transport wrappers do not bypass the kernel. Public tool registration is derived from the active application-owned manifest catalog.

For the full lifecycle and failure model see [docs/architecture.md](docs/architecture.md).

## Troubleshooting

### A tool is missing from `list_tools`

The supported and active catalogs are intentionally different. A capability may be inactive because:

- no configured backend supports it;
- writes are disabled;
- another process policy makes the capability unavailable.

Inspect `describe_mikrus_capabilities` / `capabilities://catalog` for the inactive reason.

### `AUTHORIZATION_FAILED` after upgrading from 1.x

If you explicitly set `MCP_ALLOWED_SCOPES`, check that it includes the resolved authorization axes. The 2.0 default is:

```text
tool:*,target:*,target-id:*,resource:*,data:*
```

Mutations additionally need the relevant tool scope plus `write:server`, process write enablement, and a matching approval.

### SSH refuses to start or connect

Host verification is enabled by default. Make sure the remote host is present in the effective `known_hosts` policy or set a valid `known_hosts_file`. Do not disable verification for writable deployments.

### `health://ready` reports not ready

The configured default target is a mandatory readiness dependency. Startup itself is lazy, so the target can initially be `not_connected`; readiness becomes true only after a successful connection to the default target.

### Mutation returns `AMBIGUOUS_OUTCOME`

Do not retry blindly. The request may have reached the backend before the transport/deadline failure. Reconcile the remote state first, then issue a fresh approval only if another mutation is actually required.

### Streamable HTTP refuses the token file

The token file must be a regular, non-symlink file owned by the process user, not accessible by group/other users, and contain one token of at least 32 characters.

## Standards and migration

The repository pins the exact AI Skills authority in [`ai-skills.lock.yaml`](ai-skills.lock.yaml). The MCP architecture contract is based on the stable [`mcp-server-architect/STANDARD.md`](https://github.com/paulomac1000/ai-skills/blob/main/skills/mcp-server-architect/STANDARD.md) entrypoint.

Repository CI emits structural evidence against the pinned authority. Structural evidence is not the same thing as independent production acceptance; deployment-specific real-system evidence and independent review remain separate gates.

For the 1.x → 2.0 breaking changes and rollback procedure see [MIGRATION.md](MIGRATION.md).

Additional references:

- [Security model](SECURITY.md)
- [Runtime architecture](docs/architecture.md)
- [Compliance status](docs/compliance-status.md)
- [AI Skills review notes](docs/ai-skills-review.md)
- [Repository agent instructions](AGENTS.md)

## License

[MIT](LICENSE)
