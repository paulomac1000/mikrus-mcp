"""Canonical exported MCP tool registry."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mikrus_mcp.tool_mikrus import (
    assign_domain,
    boost_server,
    describe_mikrus_capabilities,
    get_cloud,
    get_db_info,
    get_log_by_id,
    get_logs,
    get_ports,
    get_server_info,
    get_server_stats,
    list_configured_servers,
    list_servers,
    restart_server,
)
from mikrus_mcp.tool_system import (
    analyze_disk,
    change_service_state,
    check_port,
    find_system_errors,
    get_docker_logs,
    get_docker_stats,
    get_journal_logs,
    get_memory_info,
    get_network_info,
    get_process_tree,
    get_service_status,
    list_directory,
    list_docker_containers,
    list_processes,
    read_file,
    search_in_files,
    search_journal_logs,
    tail_file,
    terminate_process,
    update_system,
    write_file,
)

_TOOL_FUNCTIONS = (
    describe_mikrus_capabilities,
    list_configured_servers,
    get_server_info,
    list_servers,
    get_server_stats,
    restart_server,
    get_logs,
    get_log_by_id,
    boost_server,
    get_db_info,
    get_ports,
    get_cloud,
    assign_domain,
    read_file,
    write_file,
    get_service_status,
    change_service_state,
    analyze_disk,
    check_port,
    list_processes,
    terminate_process,
    update_system,
    list_directory,
    tail_file,
    search_in_files,
    get_memory_info,
    get_network_info,
    get_process_tree,
    list_docker_containers,
    get_docker_logs,
    get_docker_stats,
    get_journal_logs,
    find_system_errors,
    search_journal_logs,
)

TOOL_FUNCTIONS: dict[str, Callable[..., Any]] = {
    function.__name__: function for function in _TOOL_FUNCTIONS
}
