"""Mock data constants for tests."""

MOCK_SERVER_INFO = {
    "server_id": "test-srv",
    "param_ram": "1024",
    "param_disk": "15",
    "expires": "2026-06-01",
    "pro": False,
}

MOCK_SERVER_STATS = {
    "uptime": "10 days",
    "ram_used": "512M",
    "disk_used": "5G",
    "load_average": "0.10 0.30 0.25",
    "processes": 42,
}

MOCK_LOGS = [
    {"id": "1", "task": "restart", "date": "2024-01-01", "result": "OK"},
    {"id": "2", "task": "update", "date": "2024-01-02", "result": "OK"},
]

MOCK_LOG_BY_ID = {"id": "5", "task": "restart", "output": "done"}

MOCK_CLOUD_DATA = {
    "services": [{"name": "storage", "size": "10GB"}],
}

MOCK_PORTS = [20359, 30359, 40176, 40177, 40279, 40281, 40282]

MOCK_DB_INFO = {
    "host": "db.mikr.us",
    "port": "3306",
    "user": "u_test",
    "password": "secret",
}

MOCK_EXEC_OUTPUT = {
    "output": "hello",
    "exit_code": 0,
}

MOCK_RESTART_RESULT = {"raw": "OK"}
