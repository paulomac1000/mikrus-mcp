from __future__ import annotations

import json
from pathlib import Path

import pytest

from mikrus_mcp.docker_ops import (
    desired_from_compose,
    encode_receipt,
    live_state,
    parse_go_duration,
    plan_output,
    project_inspect,
    ps_labels,
    receipt_digest,
    receipt_payload,
    semantic_diff,
    states_equal,
)


def inspect_payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "Id": "abc123def0",
        "Name": "/web-1",
        "Names": ["/web-1"],
        "Image": "sha256:" + "1" * 64,
        "Config": {
            "Image": "nginx:1.27",
            "Cmd": ["nginx", "-g", "daemon off;"],
            "Entrypoint": ["/docker-entrypoint.sh"],
            "Env": ["PATH=/usr/bin", "LOG_LEVEL=info"],
            "Labels": {
                "com.docker.compose.project": "site",
                "com.docker.compose.service": "web",
                "com.docker.compose.project.config_files": "/srv/site/compose.yaml",
                "app.team": "platform",
            },
            "Healthcheck": {
                "Test": ["CMD", "curl", "-f", "localhost"],
                "Interval": 30_000_000_000,
                "Retries": 3,
            },
        },
        "HostConfig": {
            "RestartPolicy": {"Name": "unless-stopped", "MaximumRetryCount": 0},
            "PortBindings": {
                "80/tcp": [{"HostIp": "", "HostPort": "8080"}],
                "443/tcp": [{"HostIp": "", "HostPort": "8443"}],
            },
        },
        "State": {"Status": "running", "Running": True, "Health": {"Status": "healthy"}},
        "NetworkSettings": {
            "Ports": {
                "80/tcp": [{"HostIp": "", "HostPort": "8080"}],
                "443/tcp": [{"HostIp": "", "HostPort": "8443"}],
            },
            "Networks": {"site_default": {}},
        },
        "Mounts": [
            {
                "Type": "bind",
                "Source": "/srv/site/static",
                "Destination": "/usr/share/nginx/html",
                "Mode": "ro",
            }
        ],
    }
    base.update(overrides)
    return base


def compose_config() -> dict[str, object]:
    return {
        "services": {
            "web": {
                "image": "nginx:1.27",
                "command": ["nginx", "-g", "daemon off;"],
                "entrypoint": ["/docker-entrypoint.sh"],
                "environment": {"LOG_LEVEL": "info"},
                "volumes": [
                    {
                        "type": "bind",
                        "source": "/srv/site/static",
                        "target": "/usr/share/nginx/html",
                        "read_only": True,
                    }
                ],
                "networks": {"default": {}},
                "ports": [
                    {"published": "8080", "target": 80, "protocol": "tcp"},
                    {"published": "8443", "target": 443, "protocol": "tcp"},
                ],
                "labels": {"app.team": "platform"},
                "restart": "unless-stopped",
                "healthcheck": {
                    "test": ["CMD", "curl", "-f", "localhost"],
                    "interval": "30s",
                    "retries": 3,
                },
                "depends_on": ["cache"],
            }
        }
    }


def desired_state() -> dict[str, object]:
    return desired_from_compose(compose_config(), "web")


def test_parse_go_duration_variants() -> None:
    assert parse_go_duration("30s") == 30_000_000_000
    assert parse_go_duration("1m30s") == 90_000_000_000
    assert parse_go_duration("2h") == 7_200_000_000_000
    assert parse_go_duration(5_000_000) == 5_000_000
    assert parse_go_duration(None) is None
    with pytest.raises(ValueError):
        parse_go_duration("later")


def test_ps_labels_accepts_string_and_dict_forms() -> None:
    assert ps_labels({"Labels": "a=1,b=2"}) == {"a": "1", "b": "2"}
    assert ps_labels({"Labels": {"a": "1"}}) == {"a": "1"}
    assert ps_labels({}) == {}


def test_project_inspect_strips_env_values_and_internal_labels() -> None:
    projected = project_inspect(inspect_payload())
    assert "env_values" not in projected
    assert "all_labels" not in projected
    assert projected["env_keys"] == ["LOG_LEVEL", "PATH"]
    assert projected["labels"] == {"app.team": "platform"}
    assert projected["project"] == "site"
    assert projected["service"] == "web"
    assert projected["config_files"] == "/srv/site/compose.yaml"
    assert projected["ports"] == ["8080:80/tcp", "8443:443/tcp"]
    assert projected["networks"] == ["site_default"]
    assert projected["restart"] == {"name": "unless-stopped", "maximum_retry_count": 0}
    assert projected["health"] == "healthy"


def test_desired_state_normalizes_compose_semantics() -> None:
    desired = desired_state()
    assert desired["image_ref"] == "nginx:1.27"
    assert desired["env"] == {"LOG_LEVEL": "info"}
    assert desired["networks"] == ["default"]
    assert desired["ports"] == ["8080:80/tcp", "8443:443/tcp"]
    assert desired["restart"] == ("unless-stopped", 0)
    assert desired["healthcheck"] == {
        "test": ["CMD", "curl", "-f", "localhost"],
        "interval_ns": 30_000_000_000,
        "retries": 3,
    }
    assert desired["depends_on"] == ["cache"]
    assert desired["mounts"] == [
        {
            "type": "bind",
            "source": "/srv/site/static",
            "destination": "/usr/share/nginx/html",
            "mode": "ro",
        }
    ]


def test_string_command_is_normalized_like_engine_argv() -> None:
    config = {"services": {"job": {"image": "busybox", "command": 'run --flag "two words"'}}}
    desired = desired_from_compose(config, "job")
    assert desired["command"] == ["run", "--flag", "two words"]


def test_semantic_diff_reports_key_only_env_changes() -> None:
    live = live_state(inspect_payload())
    desired = {**desired_state(), "image_id": live["image_id"]}
    assert semantic_diff(live, desired, project="site") == {}

    drifted_env = inspect_payload(
        Config={
            **inspect_payload()["Config"],  # type: ignore[dict-item]
            "Env": ["PATH=/usr/bin", "LOG_LEVEL=debug"],
        }
    )
    differences = semantic_diff(live_state(drifted_env), desired, project="site")
    assert differences["env"] == {"keys_added": [], "keys_changed": ["LOG_LEVEL"]}
    encoded = json.dumps(differences)
    assert "debug" not in encoded and "info" not in encoded


def test_states_equal_matches_default_network_and_missing_healthcheck() -> None:
    imageless = {"services": {"web": {"image": "nginx:1.27"}}}
    desired = desired_from_compose(imageless, "web")
    desired = {**desired, "image_id": "sha256:" + "1" * 64}
    bare = live_state(
        inspect_payload(
            Config={
                "Image": "nginx:1.27",
                "Cmd": None,
                "Entrypoint": None,
                "Env": None,
                "Labels": {"com.docker.compose.project": "site"},
            },
            HostConfig={
                "RestartPolicy": {"Name": "", "MaximumRetryCount": 0},
                "PortBindings": {},
            },
            NetworkSettings={"Ports": {}, "Networks": {"site_default": {}}},
            Mounts=[],
        )
    )
    assert states_equal(bare, desired, project="site")


def test_receipt_binds_inputs_and_fresh_desired_state() -> None:
    desired = desired_state()
    payload = receipt_payload(
        service="web",
        project="site",
        compose_files=["/srv/site/compose.yaml"],
        desired_image_explicit=False,
        desired=desired,
        image_digest="sha256:" + "9" * 64,
    )
    receipt = encode_receipt(payload)
    assert receipt.startswith("plan:v1:sha256:")
    assert receipt_digest(receipt) == receipt.split(":")[-1]

    identical = encode_receipt(
        receipt_payload(
            service="web",
            project="site",
            compose_files=["/srv/site/compose.yaml"],
            desired_image_explicit=False,
            desired=desired_from_compose(compose_config(), "web"),
            image_digest="sha256:" + "9" * 64,
        )
    )
    assert identical == receipt

    tampered = encode_receipt(
        receipt_payload(
            service="web",
            project="site",
            compose_files=["/srv/site/compose.yaml"],
            desired_image_explicit=False,
            desired=desired,
            image_digest="sha256:" + "8" * 64,
        )
    )
    assert tampered != receipt

    reordered_files = encode_receipt(
        receipt_payload(
            service="web",
            project="site",
            compose_files=["/srv/site/compose.yaml", "/srv/site/override.yaml"],
            desired_image_explicit=False,
            desired=desired,
            image_digest="sha256:" + "9" * 64,
        )
    )
    assert reordered_files != receipt
    assert "LOG_LEVEL" in json.dumps(payload["desired"])  # values in receipt
    with pytest.raises(ValueError):
        receipt_digest("md5:zz")


def test_plan_output_never_contains_env_values() -> None:
    desired = desired_state()
    receipt = encode_receipt(
        receipt_payload(
            service="web",
            project="site",
            compose_files=["/srv/site/compose.yaml"],
            desired_image_explicit=True,
            desired=desired,
            image_digest="sha256:" + "9" * 64,
        )
    )
    output = plan_output(
        receipt=receipt,
        service="web",
        project="site",
        compose_files=["/srv/site/compose.yaml"],
        desired=desired,
        image_digest="sha256:" + "9" * 64,
        differences={},
    )
    assert output["desired_env_keys"] == ["LOG_LEVEL"]
    assert "info" not in json.dumps(output)


def test_image_drift_detection_via_digest_difference() -> None:
    """Receipt mismatch caused only by image digest differs from config drift."""
    desired = desired_state()
    planned = receipt_payload(
        service="web",
        project="site",
        compose_files=["/srv/site/compose.yaml"],
        desired_image_explicit=False,
        desired=desired,
        image_digest="sha256:" + "9" * 64,
    )
    repushed = receipt_payload(
        service="web",
        project="site",
        compose_files=["/srv/site/compose.yaml"],
        desired_image_explicit=False,
        desired=desired,
        image_digest="sha256:" + "8" * 64,
    )
    assert encode_receipt(planned) != encode_receipt(repushed)


def test_on_failure_restart_parsing() -> None:
    from mikrus_mcp.docker_ops import _restart_tuple

    assert _restart_tuple("on-failure:5") == ("on-failure", 5)
    assert _restart_tuple("always") == ("always", 0)
    assert _restart_tuple("no") == ("", 0)
    assert _restart_tuple(None) == ("", 0)
    live = live_state(
        inspect_payload(
            HostConfig={"RestartPolicy": {"Name": "on-failure", "MaximumRetryCount": 5}}
        )
    )
    desired = desired_state()
    desired = {**desired, "restart": ("on-failure", 5)}
    assert "restart" not in semantic_diff(live, desired, project="site")


def test_missing_compose_service_maps_to_not_found() -> None:
    with pytest.raises(KeyError):
        desired_from_compose({"services": {}}, "web")


def test_wait_helper_readiness_timeout_and_unsupported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mikrus_mcp.clients import ssh as ssh_module
    from tests.unit.test_ssh_client import _run_helper

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"State": {"Status": "exited", "Running": False}}))
    docker_stub = fake_bin / "docker"
    inspect_snippet = (
        'if [ "$1" = "inspect" ]; then python3 -c '
        f"\"import json;print(json.dumps(json.load(open('{state_file}'))))\"; fi\n"
    )
    docker_stub.write_text("#!/bin/sh\n" + inspect_snippet + "exit 0\n")
    docker_stub.chmod(0o755)

    def set_state(running: bool, health: str | None) -> None:
        state = {"Status": "running" if running else "exited", "Running": running}
        if health is not None:
            state["Health"] = {"Status": health}
        state_file.write_text(json.dumps({"State": state}))

    set_state(running=False, health=None)
    timeout = _run_helper(
        ssh_module._DOCKER_HELPER,
        {
            "operation": "wait",
            "container_id": "abc123",
            "readiness": "running",
            "timeout_seconds": 2,
        },
        env_path=str(fake_bin),
    )
    assert timeout["error"] == "READINESS_TIMEOUT"

    set_state(running=False, health=None)
    unsupported = _run_helper(
        ssh_module._DOCKER_HELPER,
        {
            "operation": "wait",
            "container_id": "abc123",
            "readiness": "healthy",
            "timeout_seconds": 2,
        },
        env_path=str(fake_bin),
    )
    assert unsupported["error"] == "UNSUPPORTED_CONFIGURATION"

    set_state(running=True, health=None)
    ready = _run_helper(
        ssh_module._DOCKER_HELPER,
        {
            "operation": "wait",
            "container_id": "abc123",
            "readiness": "running",
            "timeout_seconds": 5,
        },
        env_path=str(fake_bin),
    )
    assert ready["status"] == "READY"
    assert ready["state"] == "running"

    set_state(running=True, health="unhealthy")
    unhealthy = _run_helper(
        ssh_module._DOCKER_HELPER,
        {
            "operation": "wait",
            "container_id": "abc123",
            "readiness": "healthy",
            "timeout_seconds": 2,
        },
        env_path=str(fake_bin),
    )
    assert unhealthy["error"] == "HEALTH_FAILED"


def test_plan_record_store_round_trip_ttl_and_bounds(tmp_path: Path) -> None:
    from mikrus_mcp.docker_ops import PlanRecordStore, receipt_payload

    payload = receipt_payload(
        service="web",
        project="site",
        compose_files=["/srv/site/compose.yaml"],
        desired_image_explicit=False,
        desired=desired_state(),
        image_digest="sha256:" + "9" * 64,
    )
    digest = receipt_digest(encode_receipt(payload))
    current = {"now": 1000.0}
    store = PlanRecordStore(tmp_path / "plans.json", ttl_seconds=300, clock=lambda: current["now"])
    store.save(
        receipt_digest=digest,
        service="web",
        project="site",
        compose_files=["/srv/site/compose.yaml"],
        desired_image=None,
        desired_image_explicit=False,
        payload=payload,
    )
    assert (tmp_path / "plans.json").stat().st_mode & 0o077 == 0
    record = store.get(digest)
    assert record is not None
    assert record.service == "web"
    assert record.desired_image_explicit is False
    assert record.payload["desired"]["env"] == {"LOG_LEVEL": "info"}

    current["now"] = 1000.0 + 301
    assert store.get(digest) is None
    current["now"] = 1000.0 + 299
    assert store.get(digest) is not None

    for index in range(20):
        current["now"] = 1000.0 + index
        variant = {**payload, "service": f"svc{index}"}
        store.save(
            receipt_digest=encode_receipt(variant).split(":")[-1],
            service=f"svc{index}",
            project="site",
            compose_files=["/srv/site/compose.yaml"],
            desired_image=None,
            desired_image_explicit=False,
            payload=variant,
        )
    assert len(store._load_unlocked()) <= 16
    with pytest.raises(ValueError):
        receipt_digest("bogus")


def test_plan_store_missing_record_is_none(tmp_path: Path) -> None:
    from mikrus_mcp.docker_ops import PlanRecordStore

    store = PlanRecordStore(tmp_path / "absent.json")
    assert store.get("a" * 64) is None
