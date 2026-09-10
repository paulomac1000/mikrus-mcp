"""Pure Docker/Compose semantic plan logic and the durable plan record store.

The projection, diff, and receipt functions perform no I/O. The
:class:`PlanRecordStore` persists canonical plan payloads server-side in one
private atomically replaced file so ``docker_recreate_apply`` can derive every
desired-state input from the stored record instead of invocation arguments.
Environment values are carried inside the canonical receipt payload (and thus
inside the private store file) but are never projected into model-visible
evidence; only environment keys leave the projection functions.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PLAN_RECEIPT_PREFIX = "plan:v1:sha256:"
PLAN_TTL_SECONDS = 300
MAX_PLAN_RECORDS = 16
_MODELLED_FIELDS = (
    "image",
    "command",
    "entrypoint",
    "env",
    "mounts",
    "networks",
    "ports",
    "labels",
    "restart",
    "healthcheck",
)
_COMPOSE_LABEL_PREFIX = "com.docker.compose."
_MAX_MOUNTS = 32
_MAX_NETWORKS = 16
_MAX_PORTS = 64
_MAX_LABELS = 64
_MAX_ENV_KEYS = 128
_MAX_DEPENDS_ON = 32
_duration_ns = re.compile(
    r"^(?:(\d+(?:\.\d+)?)h)?(?:(\d+(?:\.\d+)?)m)?(?:(\d+(?:\.\d+)?)s)?(?:(\d+(?:\.\d+)?)ms)?(?:(\d+(?:\.\d+)?)us)?(?:(\d+)(?:ns)?)?$"
)


def canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def encode_receipt(payload: dict[str, Any]) -> str:
    digest = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    return f"{PLAN_RECEIPT_PREFIX}{digest}"


def receipt_digest(receipt: str) -> str:
    if not receipt.startswith(PLAN_RECEIPT_PREFIX):
        raise ValueError("receipt must use the plan:v1:sha256: prefix")
    digest = receipt[len(PLAN_RECEIPT_PREFIX) :]
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("receipt digest must be 64 hex characters")
    return digest


def parse_go_duration(value: object) -> int | None:
    """Parse a Go duration string into nanoseconds; None when absent."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if not isinstance(value, str):
        raise ValueError("duration must be a string or number")
    match = _duration_ns.fullmatch(value.strip())
    if match is None:
        raise ValueError(f"unsupported duration literal: {value}")
    hours, minutes, seconds, millis, micros, nanos = match.groups()
    total = 0.0
    for group, scale in (
        (hours, 3_600_000_000_000),
        (minutes, 60_000_000_000),
        (seconds, 1_000_000_000),
        (millis, 1_000_000),
        (micros, 1_000),
        (nanos, 1),
    ):
        if group is not None:
            total += float(group) * scale
    return int(total)


def _as_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return shlex.split(value)
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            if isinstance(item, list):  # exec/entrypoint pre-quoted form
                result.extend(str(part) for part in item)
            else:
                result.append(str(item))
        return result
    raise ValueError("command-like field must be a string or list")


def _env_mapping(value: object) -> dict[str, str]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return {str(key): "" if item is None else str(item) for key, item in value.items()}
    if isinstance(value, list):
        result: dict[str, str] = {}
        for item in value:
            if not isinstance(item, str) or "=" not in item:
                continue
            key, _, item_value = item.partition("=")
            result[key] = item_value
        return result
    raise ValueError("environment must be a mapping or list")


def _label_mapping(value: object) -> dict[str, str]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return {str(key): str(item) for key, item in value.items()}
    if isinstance(value, list):
        result: dict[str, str] = {}
        for item in value:
            if isinstance(item, str) and "=" in item:
                key, _, item_value = item.partition("=")
                result[key] = item_value
        return result
    raise ValueError("labels must be a mapping or list")


def _mount_mode(compose_volume: dict[str, Any]) -> str:
    return "ro" if compose_volume.get("read_only") else "rw"


def _canonical_mounts(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    mounts: list[dict[str, str]] = []
    for item in value[:_MAX_MOUNTS]:
        if isinstance(item, dict):
            mounts.append(
                {
                    "type": str(item.get("type", "volume")),
                    "source": str(item.get("source") or ""),
                    "destination": str(item.get("target") or item.get("destination") or ""),
                    "mode": _mount_mode(item),
                }
            )
        elif isinstance(item, str):
            parts = item.split(":")
            if len(parts) == 1:
                mounts.append(
                    {"type": "volume", "source": "", "destination": parts[0], "mode": "rw"}
                )
            else:
                source, destination = parts[0], parts[1]
                mode = parts[2] if len(parts) > 2 else "rw"
                mounts.append(
                    {
                        "type": "bind" if source.startswith("/") else "volume",
                        "source": source,
                        "destination": destination,
                        "mode": mode,
                    }
                )
    return sorted(mounts, key=lambda item: (item["destination"], item["source"]))


def _live_mounts(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    mounts: list[dict[str, str]] = []
    for item in value[:_MAX_MOUNTS]:
        if not isinstance(item, dict):
            continue
        destination = str(item.get("Destination") or "")
        mode_value = str(item.get("Mode") or "")
        if mode_value in ("", "z", "Z"):
            mode_value = "rw"
        mounts.append(
            {
                "type": str(item.get("Type") or "volume"),
                "source": str(item.get("Source") or ""),
                "destination": destination,
                "mode": mode_value,
            }
        )
    return sorted(mounts, key=lambda item: (item["destination"], item["source"]))


def _canonical_ports(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    ports: list[str] = []
    for item in value[:_MAX_PORTS]:
        if isinstance(item, dict):
            published = item.get("published")
            target = item.get("target")
            if published is None or target is None:
                continue
            protocol = str(item.get("protocol") or "tcp")
            host_ip = str(item.get("host_ip") or "")
            prefix = f"[{host_ip}]:" if host_ip and host_ip != "::" else ""
            ports.append(f"{prefix}{published}:{target}/{protocol}")
        elif isinstance(item, str):
            ports.append(item)
    return sorted(set(ports))


def _live_ports(value: object) -> list[str]:
    if not isinstance(value, dict):
        return []
    ports: list[str] = []
    for container_port, bindings in value.items():
        if not isinstance(bindings, list):
            continue
        protocol = "udp" if str(container_port).endswith("/udp") else "tcp"
        target = str(container_port).split("/")[0]
        for binding in bindings[:_MAX_PORTS]:
            if not isinstance(binding, dict):
                continue
            host_port = binding.get("HostPort")
            if host_port in (None, ""):
                continue
            host_ip = str(binding.get("HostIp") or "")
            prefix = f"[{host_ip}]:" if host_ip and host_ip != "::" else ""
            ports.append(f"{prefix}{host_port}:{target}/{protocol}")
    return sorted(set(ports))


def _restart_tuple(value: object) -> tuple[str, int]:
    if value is None:
        return ("", 0)
    text = str(value)
    if text in ("no", ""):
        return ("", 0)
    name, _, raw_maximum = text.partition(":")
    if name == "on-failure":
        try:
            return ("on-failure", int(raw_maximum or 0))
        except ValueError:
            return ("on-failure", 0)
    return (name, 0)


def _canonical_healthcheck(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    test = value.get("test")
    if isinstance(test, str):
        test_list = shlex.split(test)
    elif isinstance(test, list):
        test_list = [str(item) for item in test]
    else:
        test_list = []
    if value.get("disable"):
        test_list = ["NONE"]
    healthcheck: dict[str, Any] = {"test": test_list}
    interval = parse_go_duration(value.get("interval"))
    timeout = parse_go_duration(value.get("timeout"))
    start_period = parse_go_duration(value.get("start_period"))
    if interval is not None:
        healthcheck["interval_ns"] = interval
    if timeout is not None:
        healthcheck["timeout_ns"] = timeout
    if start_period is not None:
        healthcheck["start_period_ns"] = start_period
    retries = value.get("retries")
    if retries is not None:
        healthcheck["retries"] = int(retries)
    return healthcheck


def _live_healthcheck(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    test = value.get("Test")
    test_list = [str(item) for item in test] if isinstance(test, list) else []
    if test_list == ["NONE"]:
        return {"test": ["NONE"]}
    healthcheck: dict[str, Any] = {"test": test_list}
    for source, target in (
        ("Interval", "interval_ns"),
        ("Timeout", "timeout_ns"),
        ("StartPeriod", "start_period_ns"),
    ):
        raw = value.get(source)
        if isinstance(raw, (int, float)) and raw > 0:
            healthcheck[target] = int(raw)
    retries = value.get("Retries")
    if isinstance(retries, int) and retries >= 0:
        healthcheck["retries"] = retries
    return healthcheck


def _public_labels(labels: dict[str, str]) -> dict[str, str]:
    return {
        key: value
        for key, value in sorted(labels.items())
        if not key.startswith(_COMPOSE_LABEL_PREFIX)
    }


def env_keys(env: dict[str, str]) -> list[str]:
    return sorted(env)[:_MAX_ENV_KEYS]


def ps_labels(entry: dict[str, Any]) -> dict[str, str]:
    """Labels from one ``docker ps --format json`` entry.

    ``docker ps`` serializes Labels as a comma-separated string while
    ``docker inspect`` uses an object; both forms are accepted here.
    """
    raw = entry.get("Labels")
    if isinstance(raw, dict):
        return {str(key): str(value) for key, value in raw.items()}
    if isinstance(raw, str):
        labels: dict[str, str] = {}
        for pair in raw.split(","):
            if "=" in pair:
                key, _, value = pair.partition("=")
                labels[key] = value
        return labels
    return {}


def live_state(inspect_payload: dict[str, Any]) -> dict[str, Any]:
    """Full comparison view of one ``docker inspect`` object.

    Contains environment values and the complete label mapping so semantic
    comparison can run server-side; ``project_inspect`` strips those two
    fields before anything becomes model-visible.
    """
    config = inspect_payload.get("Config") or {}
    host_config = inspect_payload.get("HostConfig") or {}
    state = inspect_payload.get("State") or {}
    network_settings = inspect_payload.get("NetworkSettings") or {}
    labels = _label_mapping(config.get("Labels"))
    health = state.get("Health") if isinstance(state.get("Health"), dict) else None
    restart_policy = host_config.get("RestartPolicy") or {}
    restart_name = str(restart_policy.get("Name") or "")
    restart_maximum = restart_policy.get("MaximumRetryCount")
    env = _env_mapping(config.get("Env"))
    names = [str(item) for item in inspect_payload.get("Names") or []]
    name = inspect_payload.get("Name")
    if isinstance(name, str) and name:
        names = [name, *names]
    return {
        "id": str(inspect_payload.get("Id") or ""),
        "names": sorted(set(names))[:8],
        "image": str(config.get("Image") or ""),
        "image_id": str(inspect_payload.get("Image") or ""),
        "state": str(state.get("Status") or ""),
        "running": bool(state.get("Running")),
        "health": str(health.get("Status")) if health else None,
        "project": str(labels.get("com.docker.compose.project") or ""),
        "service": str(labels.get("com.docker.compose.service") or ""),
        "config_files": str(labels.get("com.docker.compose.project.config_files") or ""),
        "command": [str(item) for item in config.get("Cmd") or []],
        "entrypoint": [str(item) for item in config.get("Entrypoint") or []],
        "env_values": env,
        "env_keys": env_keys(env),
        "all_labels": labels,
        "mounts": _live_mounts(inspect_payload.get("Mounts")),
        "networks": sorted((network_settings.get("Networks") or {}).keys())[:_MAX_NETWORKS],
        "ports": _live_ports(network_settings.get("Ports")),
        "labels": _public_labels(labels),
        "restart": {"name": restart_name, "maximum_retry_count": restart_maximum}
        if restart_name
        else None,
        "healthcheck": _live_healthcheck(config.get("Healthcheck")),
    }


def project_inspect(inspect_payload: dict[str, Any]) -> dict[str, Any]:
    """Model-visible bounded subset of one ``docker inspect`` object.

    Environment values and the full label map are removed; only environment
    keys and non-compose-internal labels survive.
    """
    projected = live_state(inspect_payload)
    projected.pop("env_values", None)
    projected.pop("all_labels", None)
    return projected


def desired_from_compose(compose_config: dict[str, Any], service: str) -> dict[str, Any]:
    """Extract the compose-desired semantic state for one service."""
    services = compose_config.get("services")
    if not isinstance(services, dict) or service not in services:
        raise KeyError(service)
    entry = services[service]
    if not isinstance(entry, dict):
        raise ValueError("compose service entry must be a mapping")
    networks_value = entry.get("networks")
    if isinstance(networks_value, dict):
        network_names = [str(name) for name in networks_value]
    elif isinstance(networks_value, list):
        network_names = [str(name) for name in networks_value]
    else:
        network_names = ["default"]
    depends_on = entry.get("depends_on")
    if isinstance(depends_on, dict):
        dependency_names = [str(name) for name in depends_on]
    elif isinstance(depends_on, list):
        dependency_names = [str(name) for name in depends_on]
    else:
        dependency_names = []
    image = entry.get("image")
    desired: dict[str, Any] = {
        "image_ref": str(image) if image else None,
        "command": _as_list(entry.get("command")),
        "entrypoint": _as_list(entry.get("entrypoint")),
        "env": _env_mapping(entry.get("environment")),
        "mounts": _canonical_mounts(entry.get("volumes")),
        "networks": sorted(set(network_names))[:_MAX_NETWORKS],
        "ports": _canonical_ports(entry.get("ports")),
        "labels": _label_mapping(entry.get("labels")),
        "restart": _restart_tuple(entry.get("restart")),
        "healthcheck": _canonical_healthcheck(entry.get("healthcheck")),
        "depends_on": sorted(set(dependency_names))[:_MAX_DEPENDS_ON],
    }
    return desired


def normalize_desired_networks(desired: dict[str, Any], project: str) -> list[str]:
    """Map the compose ``default`` network to its runtime ``<project>_default`` name."""
    normalized = []
    for name in desired["networks"]:
        normalized.append(f"{project}_default" if name == "default" else name)
    return sorted(set(normalized))


def semantic_diff(live: dict[str, Any], desired: dict[str, Any], *, project: str) -> dict[str, Any]:
    """Model-visible differences between live state and compose-desired state.

    Environment differences expose keys only, never values.
    """
    differences: dict[str, Any] = {}
    if desired["image_ref"] is not None and live["image_id"] != desired.get("image_id"):
        differences["image"] = {"live": live["image_id"], "desired": desired.get("image_id")}
    if live["command"] != desired["command"]:
        differences["command"] = {"live": live["command"], "desired": desired["command"]}
    if live["entrypoint"] != desired["entrypoint"]:
        differences["entrypoint"] = {
            "live": live["entrypoint"],
            "desired": desired["entrypoint"],
        }
    live_env = dict(live.get("env_values") or {})
    desired_env = desired["env"]
    added = sorted(set(desired_env) - set(live_env))
    changed = sorted(
        key for key in set(live_env) & set(desired_env) if live_env[key] != desired_env[key]
    )
    if added or changed:
        differences["env"] = {
            "keys_added": added,
            "keys_changed": changed,
        }
    if live["mounts"] != desired["mounts"]:
        differences["mounts"] = {"live": live["mounts"], "desired": desired["mounts"]}
    if live["networks"] != normalize_desired_networks(desired, project):
        differences["networks"] = {
            "live": live["networks"],
            "desired": normalize_desired_networks(desired, project),
        }
    if live["ports"] != desired["ports"]:
        differences["ports"] = {"live": live["ports"], "desired": desired["ports"]}
    live_labels = dict(live.get("all_labels") or {})
    desired_labels = desired["labels"]
    mismatched_labels = {
        key: {"live": live_labels.get(key), "desired": desired_labels[key]}
        for key in sorted(desired_labels)
        if live_labels.get(key) != desired_labels[key]
    }
    if mismatched_labels:
        differences["labels"] = mismatched_labels
    live_restart = live.get("restart")
    if isinstance(live_restart, dict):
        live_restart_tuple = (
            str(live_restart.get("name") or ""),
            int(live_restart.get("maximum_retry_count") or 0),
        )
    elif live_restart is None:
        live_restart_tuple = ("", 0)
    else:
        live_restart_tuple = _restart_tuple(live_restart)
    if live_restart_tuple != tuple(desired["restart"]):
        differences["restart"] = {
            "live": list(live_restart_tuple),
            "desired": list(desired["restart"]),
        }
    if desired["healthcheck"] is not None and live["healthcheck"] != desired["healthcheck"]:
        differences["healthcheck"] = {
            "live": live["healthcheck"],
            "desired": desired["healthcheck"],
        }
    return differences


def receipt_payload(
    *,
    service: str,
    project: str,
    compose_files: list[str],
    desired_image_explicit: bool,
    desired: dict[str, Any],
    image_digest: str | None,
) -> dict[str, Any]:
    """Canonical plan payload bound by the receipt.

    Environment values are included (apply comparison requires them); they must
    be stripped from any model-visible projection of this payload.
    """
    return {
        "version": "v1",
        "service": service,
        "project": project,
        "compose_files": list(compose_files),
        "desired_image_explicit": bool(desired_image_explicit),
        "image_digest": image_digest,
        "modeled_fields": list(_MODELLED_FIELDS),
        "desired": {
            "image_ref": desired["image_ref"],
            "command": desired["command"],
            "entrypoint": desired["entrypoint"],
            "env": dict(desired["env"]),
            "mounts": desired["mounts"],
            "networks": desired["networks"],
            "ports": desired["ports"],
            "labels": desired["labels"],
            "restart": list(desired["restart"]),
            "healthcheck": desired["healthcheck"],
            "depends_on": desired["depends_on"],
        },
    }


def plan_output(
    *,
    receipt: str,
    service: str,
    project: str,
    compose_files: list[str],
    desired: dict[str, Any],
    image_digest: str | None,
    differences: dict[str, Any],
) -> dict[str, Any]:
    """Model-visible plan evidence: bounded, and environment values removed."""
    return {
        "plan_receipt": receipt,
        "service": service,
        "project": project,
        "compose_files": list(compose_files),
        "image_ref": desired["image_ref"],
        "image_digest": image_digest,
        "desired_env_keys": env_keys(desired["env"]),
        "desired_ports": desired["ports"],
        "desired_networks": desired["networks"],
        "depends_on": desired["depends_on"],
        "proposed_differences": differences,
        "modeled_fields": list(_MODELLED_FIELDS),
    }


def states_equal(live: dict[str, Any], desired: dict[str, Any], *, project: str) -> bool:
    """ALREADY_APPLIED decision: live modeled state equals compose-desired state."""
    return semantic_diff(live, desired, project=project) == {}


@dataclass(slots=True)
class PlanRecord:
    """Durable server-side plan record keyed by its receipt digest."""

    receipt_digest: str
    service: str
    project: str
    compose_files: list[str]
    desired_image: str | None
    desired_image_explicit: bool
    payload: dict[str, Any]
    created_at: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "receiptDigest": self.receipt_digest,
            "service": self.service,
            "project": self.project,
            "composeFiles": list(self.compose_files),
            "desiredImage": self.desired_image,
            "desiredImageExplicit": self.desired_image_explicit,
            "payload": self.payload,
            "createdAt": self.created_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> PlanRecord:
        required = (
            "receiptDigest",
            "service",
            "project",
            "composeFiles",
            "desiredImageExplicit",
            "payload",
            "createdAt",
        )
        values = {key: payload.get(key) for key in required}
        if any(value is None for value in values.values()):
            raise ValueError("plan record has missing fields")
        if not isinstance(values["composeFiles"], list) or not isinstance(values["payload"], dict):
            raise ValueError("plan record has malformed fields")
        desired_image = payload.get("desiredImage")
        return cls(
            receipt_digest=str(values["receiptDigest"]),
            service=str(values["service"]),
            project=str(values["project"]),
            compose_files=[str(item) for item in values["composeFiles"]],
            desired_image=None if desired_image is None else str(desired_image),
            desired_image_explicit=bool(values["desiredImageExplicit"]),
            payload=dict(values["payload"]),
            created_at=float(str(values["createdAt"])),
        )


class PlanRecordStore:
    """Persist bounded plan records in one atomically replaced JSON file."""

    def __init__(
        self,
        path: Path,
        *,
        max_records: int = MAX_PLAN_RECORDS,
        ttl_seconds: float = PLAN_TTL_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if max_records < 1:
            raise ValueError("max_records must be positive")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self.path = path
        self.max_records = max_records
        self.ttl_seconds = ttl_seconds
        self._clock = clock

    def save(
        self,
        *,
        receipt_digest: str,
        service: str,
        project: str,
        compose_files: list[str],
        desired_image: str | None,
        desired_image_explicit: bool,
        payload: dict[str, Any],
    ) -> PlanRecord:
        with self._lock():
            records = [
                record
                for record in self._load_unlocked()
                if record.receipt_digest != receipt_digest
            ]
            records = [r for r in records if not self._expired(r)]
            record = PlanRecord(
                receipt_digest=receipt_digest,
                service=service,
                project=project,
                compose_files=list(compose_files),
                desired_image=desired_image,
                desired_image_explicit=desired_image_explicit,
                payload=payload,
                created_at=self._clock(),
            )
            records.append(record)
            while len(records) > self.max_records:
                records.pop(0)
            self._persist_unlocked(records)
            return record

    def get(self, receipt_digest: str) -> PlanRecord | None:
        with self._lock():
            for record in self._load_unlocked():
                if record.receipt_digest == receipt_digest and not self._expired(record):
                    return record
            return None

    def _expired(self, record: PlanRecord) -> bool:
        return (self._clock() - record.created_at) > self.ttl_seconds

    def _load_unlocked(self) -> list[PlanRecord]:
        if not self.path.exists():
            return []
        if self.path.is_symlink() or not self.path.is_file():
            raise ValueError("plan record store must be a regular file")
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(raw, list) or len(raw) > self.max_records:
            raise ValueError("plan record store is malformed or exceeds its bound")
        if any(not isinstance(item, dict) for item in raw):
            raise ValueError("plan record store contains a non-object record")
        return [PlanRecord.from_dict(item) for item in raw]

    def _persist_unlocked(self, records: list[PlanRecord]) -> None:
        fd, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump([item.as_dict() for item in records], stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @contextmanager
    def _lock(self) -> Iterator[None]:
        import fcntl

        if self.path.parent.is_symlink():
            raise ValueError("plan record store parent must not be a symlink")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_name(f".{self.path.name}.lock")
        if lock_path.is_symlink():
            raise ValueError("plan record store lock must not be a symlink")
        with lock_path.open("a+", encoding="utf-8") as lock:
            os.chmod(lock_path, 0o600)
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
