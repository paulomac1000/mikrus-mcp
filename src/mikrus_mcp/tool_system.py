"""Public MCP tool callables for system, container, and journal capabilities."""

from __future__ import annotations

from mcp.server.mcpserver import Context

from mikrus_mcp.tool_common import AppContext, ToolResult, _invoke


async def read_file(
    path: str,
    ctx: Context[AppContext],
    server: str | None = None,
) -> ToolResult:
    """Read a bounded text preview from an authorized absolute path."""
    return await _invoke(ctx, "read_file", {"server": server, "path": path})


async def write_file(
    path: str,
    content: str,
    ctx: Context[AppContext],
    server: str | None = None,
) -> ToolResult:
    """Replace a file under a safe root after a matching approval is loaded."""
    return await _invoke(
        ctx,
        "write_file",
        {"server": server, "path": path, "content": content},
    )


async def get_service_status(
    name: str,
    ctx: Context[AppContext],
    server: str | None = None,
) -> ToolResult:
    """Read systemd status for one validated service name."""
    return await _invoke(ctx, "get_service_status", {"server": server, "name": name})


async def change_service_state(
    name: str,
    action: str,
    ctx: Context[AppContext],
    server: str | None = None,
) -> ToolResult:
    """Change systemd state after a matching server-side approval is loaded."""
    return await _invoke(
        ctx,
        "change_service_state",
        {"server": server, "name": name, "action": action},
    )


async def analyze_disk(
    ctx: Context[AppContext],
    path: str = "/",
    server: str | None = None,
) -> ToolResult:
    """Return bounded filesystem usage information for an authorized path."""
    return await _invoke(ctx, "analyze_disk", {"server": server, "path": path})


async def check_port(
    port: str,
    ctx: Context[AppContext],
    server: str | None = None,
) -> ToolResult:
    """Check whether one validated TCP port is listening."""
    return await _invoke(ctx, "check_port", {"server": server, "port": port})


async def list_processes(ctx: Context[AppContext], server: str | None = None) -> ToolResult:
    """Return a bounded process summary for one authorized target."""
    return await _invoke(ctx, "list_processes", {"server": server})


async def terminate_process(
    target: str,
    ctx: Context[AppContext],
    server: str | None = None,
) -> ToolResult:
    """Terminate one process after a matching server-side approval is loaded."""
    return await _invoke(
        ctx,
        "terminate_process",
        {"server": server, "target": target},
    )


async def update_system(
    ctx: Context[AppContext],
    server: str | None = None,
) -> ToolResult:
    """Run package updates after a matching server-side approval is loaded."""
    return await _invoke(ctx, "update_system", {"server": server})


async def list_directory(
    path: str,
    ctx: Context[AppContext],
    server: str | None = None,
) -> ToolResult:
    """List a bounded directory view for an authorized absolute path."""
    return await _invoke(ctx, "list_directory", {"server": server, "path": path})


async def tail_file(
    path: str,
    ctx: Context[AppContext],
    lines: int = 50,
    server: str | None = None,
) -> ToolResult:
    """Return a bounded tail of an authorized text file."""
    return await _invoke(ctx, "tail_file", {"server": server, "path": path, "lines": lines})


async def search_in_files(
    path: str,
    pattern: str,
    ctx: Context[AppContext],
    server: str | None = None,
) -> ToolResult:
    """Search files under one authorized path with bounded fixed-string matching."""
    return await _invoke(
        ctx,
        "search_in_files",
        {"server": server, "path": path, "pattern": pattern},
    )


async def get_memory_info(ctx: Context[AppContext], server: str | None = None) -> ToolResult:
    """Return bounded memory usage information for one target."""
    return await _invoke(ctx, "get_memory_info", {"server": server})


async def get_network_info(ctx: Context[AppContext], server: str | None = None) -> ToolResult:
    """Return authorized network interface and listening-port information."""
    return await _invoke(ctx, "get_network_info", {"server": server})


async def get_process_tree(ctx: Context[AppContext], server: str | None = None) -> ToolResult:
    """Return a bounded process tree for one authorized target."""
    return await _invoke(ctx, "get_process_tree", {"server": server})


async def list_docker_containers(ctx: Context[AppContext], server: str | None = None) -> ToolResult:
    """List Docker containers visible to the configured target identity."""
    return await _invoke(ctx, "list_docker_containers", {"server": server})


async def get_docker_logs(
    container: str,
    ctx: Context[AppContext],
    lines: int = 50,
    server: str | None = None,
) -> ToolResult:
    """Return a bounded log tail for one validated container name."""
    return await _invoke(
        ctx,
        "get_docker_logs",
        {"server": server, "container": container, "lines": lines},
    )


async def get_docker_stats(ctx: Context[AppContext], server: str | None = None) -> ToolResult:
    """Return one bounded Docker resource snapshot."""
    return await _invoke(ctx, "get_docker_stats", {"server": server})


async def get_journal_logs(
    unit: str,
    ctx: Context[AppContext],
    lines: int = 50,
    server: str | None = None,
) -> ToolResult:
    """Return a bounded journal tail for one validated service unit."""
    return await _invoke(
        ctx,
        "get_journal_logs",
        {"server": server, "unit": unit, "lines": lines},
    )


async def find_system_errors(
    ctx: Context[AppContext],
    hours: int = 1,
    server: str | None = None,
) -> ToolResult:
    """Return bounded error-level journal entries from a validated time window."""
    return await _invoke(ctx, "find_system_errors", {"server": server, "hours": hours})


async def search_journal_logs(
    term: str,
    ctx: Context[AppContext],
    lines: int = 50,
    server: str | None = None,
) -> ToolResult:
    """Search a bounded journal window using validated fixed-string input."""
    return await _invoke(
        ctx,
        "search_journal_logs",
        {"server": server, "term": term, "lines": lines},
    )


async def execute_program(
    executable: str,
    ctx: Context[AppContext],
    argv: list[str] | None = None,
    cwd: str | None = None,
    stdin: str | None = None,
    server: str | None = None,
) -> ToolResult:
    """Run an approved typed program request without exposing a shell command string."""
    return await _invoke(
        ctx,
        "execute_program",
        {
            "server": server,
            "executable": executable,
            "argv": [] if argv is None else argv,
            "cwd": cwd,
            "stdin": stdin,
        },
    )


async def start_program(
    executable: str,
    ctx: Context[AppContext],
    argv: list[str] | None = None,
    cwd: str | None = None,
    stdin: str | None = None,
    server: str | None = None,
) -> ToolResult:
    """Start an approved typed program and return a bounded in-process job handle."""
    return await _invoke(
        ctx,
        "start_program",
        {
            "server": server,
            "executable": executable,
            "argv": [] if argv is None else argv,
            "cwd": cwd,
            "stdin": stdin,
        },
    )


async def get_program_status(
    job_id: str,
    ctx: Context[AppContext],
) -> ToolResult:
    """Return the status of a typed program job owned by the calling principal."""
    return await _invoke(ctx, "get_program_status", {"job_id": job_id})


async def get_program_result(
    job_id: str,
    ctx: Context[AppContext],
) -> ToolResult:
    """Return a terminal result, or the current status, for an owned program job."""
    return await _invoke(ctx, "get_program_result", {"job_id": job_id})


async def cancel_program(
    job_id: str,
    ctx: Context[AppContext],
) -> ToolResult:
    """Cancel an owned typed program job without exposing a remote shell."""
    return await _invoke(ctx, "cancel_program", {"job_id": job_id})
