"""Unit test fixtures — mocked dependencies, no real connections."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from mikrus_mcp.client import MikrusClient, SshClient


@pytest.fixture
def mock_client() -> MikrusClient:
    """Return a MikrusClient with test credentials."""
    return MikrusClient("https://api.mikr.us", "test-key", "test-srv")


@pytest.fixture
def mock_ssh_client() -> SshClient:
    """Return an SshClient with test credentials and sudo password."""
    return SshClient("test-host", "testuser", password="secret", sudo_password="secret")


@pytest.fixture
def mock_ssh_client_no_sudo() -> SshClient:
    """Return an SshClient without sudo password."""
    return SshClient("test-host", "testuser")


@pytest.fixture
def mock_asyncssh() -> MagicMock:
    """Return a mock asyncssh module with all required attributes."""
    mock = MagicMock()
    mock.PIPE = -1
    mock.Error = Exception
    mock.read_known_hosts = MagicMock(return_value=())
    return mock


@pytest.fixture
def mock_mcp_context() -> MagicMock:
    """Return a mock MCP context for server tool tests."""
    mock_ctx = MagicMock()
    return mock_ctx


@pytest.fixture
def mock_config() -> dict:
    """Return a sample two-server multi-server config."""
    return {
        "servers": {
            "alpha": {
                "type": "mikrus",
                "key": "k1",
                "srv": "alpha",
                "api_url": "https://api.mikr.us",
            },
            "beta": {
                "type": "ssh",
                "host": "beta.host",
                "user": "root",
            },
        },
        "default": "alpha",
    }


@pytest.fixture
def mock_config_three() -> dict:
    """Return a sample three-server multi-server config."""
    return {
        "servers": {
            "alpha": {
                "type": "mikrus",
                "key": "k1",
                "srv": "alpha",
                "api_url": "https://api.mikr.us",
            },
            "beta": {
                "type": "ssh",
                "host": "beta.host",
                "user": "root",
            },
            "gamma": {
                "type": "ssh",
                "host": "gamma.host",
                "user": "root",
            },
        },
        "default": "alpha",
    }


@pytest.fixture
def mock_mikrus() -> MagicMock:
    """Return a mocked MikrusClient with all async methods."""
    mock = MagicMock(spec=MikrusClient)
    mock.get_server_info = AsyncMock()
    mock.list_servers = AsyncMock()
    mock.get_server_stats = AsyncMock()
    mock.restart_server = AsyncMock()
    mock.get_logs = AsyncMock()
    mock.get_log_by_id = AsyncMock()
    mock.boost_server = AsyncMock()
    mock.get_db_info = AsyncMock()
    mock.get_ports = AsyncMock()
    mock.get_cloud = AsyncMock()
    mock.assign_domain = AsyncMock()
    mock.execute_command = AsyncMock()
    mock.read_file = AsyncMock()
    mock.write_file = AsyncMock()
    mock.manage_service = AsyncMock()
    mock.analyze_disk = AsyncMock()
    mock.check_port = AsyncMock()
    mock.manage_process = AsyncMock()
    mock.update_system = AsyncMock()
    mock.list_directory = AsyncMock()
    mock.tail_file = AsyncMock()
    mock.search_in_files = AsyncMock()
    mock.get_memory_info = AsyncMock()
    mock.get_network_info = AsyncMock()
    mock.get_process_tree = AsyncMock()
    mock.list_docker_containers = AsyncMock()
    mock.get_docker_logs = AsyncMock()
    mock.get_docker_stats = AsyncMock()
    mock.get_journal_logs = AsyncMock()
    mock.find_system_errors = AsyncMock()
    mock.search_journal_logs = AsyncMock()
    return mock


@pytest.fixture
def mock_ssh() -> MagicMock:
    """Return a mocked SshClient with all async methods."""
    mock = MagicMock(spec=SshClient)
    mock.execute_command = AsyncMock()
    mock.read_file = AsyncMock()
    mock.write_file = AsyncMock()
    mock.manage_service = AsyncMock()
    mock.analyze_disk = AsyncMock()
    mock.check_port = AsyncMock()
    mock.manage_process = AsyncMock()
    mock.update_system = AsyncMock()
    mock.list_directory = AsyncMock()
    mock.tail_file = AsyncMock()
    mock.search_in_files = AsyncMock()
    mock.get_memory_info = AsyncMock()
    mock.get_network_info = AsyncMock()
    mock.get_process_tree = AsyncMock()
    mock.list_docker_containers = AsyncMock()
    mock.get_docker_logs = AsyncMock()
    mock.get_docker_stats = AsyncMock()
    mock.get_journal_logs = AsyncMock()
    mock.find_system_errors = AsyncMock()
    mock.search_journal_logs = AsyncMock()
    return mock


@pytest.fixture
def mcp_context(mock_mikrus: MagicMock, mock_ssh: MagicMock) -> MagicMock:
    """Return a mock MCP context with preset lifespan containing mocked clients."""
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {
        "clients": {"alpha": mock_mikrus, "beta": mock_ssh},
        "default": "alpha",
        "failed": {},
    }
    return ctx


@pytest.fixture
def mock_mcp() -> MagicMock:
    """Return a mock MCP instance with a working tool() decorator.

    Follows Canonical Template 9 from mcp_standards.md.
    Accepts both @mcp.tool and @mcp.tool() forms.
    """
    mcp = MagicMock()
    mcp._tools = {}

    def tool_decorator(*args: object, **kwargs: object) -> object:
        def wrapper(func: object) -> object:
            tool_name = kwargs.get("name", getattr(func, "__name__", "unknown"))
            assert isinstance(tool_name, str)
            mcp._tools[tool_name] = func
            return func

        if len(args) == 1 and callable(args[0]) and not kwargs:
            name = getattr(args[0], "__name__", "unknown")
            assert isinstance(name, str)
            mcp._tools[name] = args[0]
            return args[0]
        return wrapper

    mcp.tool = tool_decorator

    def get_tool(name: str) -> object:
        return mcp._tools.get(name)

    mcp.get_tool = get_tool
    return mcp
