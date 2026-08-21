"""Authorized target registry with lazy client construction and no fallback."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from mikrus_mcp.client import Client, build_client
from mikrus_mcp.config import TargetConfig
from mikrus_mcp.errors import AppError, ErrorCode

logger = logging.getLogger(__name__)


class TargetRegistry:
    """Lazily construct clients only after caller and selector authorization."""

    def __init__(
        self,
        targets: dict[str, TargetConfig],
        *,
        factory: Callable[[TargetConfig], Client] = build_client,
    ) -> None:
        self._targets = dict(targets)
        self._factory = factory
        self._clients: dict[str, Client] = {}
        self._failures: dict[str, str] = {}
        self._locks = {name: asyncio.Lock() for name in targets}

    @property
    def names(self) -> set[str]:
        return set(self._targets)

    def config(self, target: str) -> TargetConfig:
        try:
            return self._targets[target]
        except KeyError as exc:
            raise AppError(ErrorCode.NOT_FOUND, f"unknown target: {target}") from exc

    async def get(self, target: str) -> Client:
        config = self.config(target)
        async with self._locks[target]:
            existing = self._clients.get(target)
            if existing is not None:
                connected = getattr(existing, "is_connected", True)
                if connected:
                    return existing
                try:
                    await existing.close()
                finally:
                    self._clients.pop(target, None)
            client = self._factory(config)
            try:
                await client.open()
            except Exception as exc:
                self._failures[target] = type(exc).__name__
                raise AppError(
                    ErrorCode.UNAVAILABLE,
                    f"target '{target}' is unavailable",
                    retryable=True,
                ) from exc
            expected_identity = config.stable_identity
            if config.type == "ssh":
                suffix = "#host-key=SHA256:" if config.verify_host_key else "#host-key=UNVERIFIED"
                identity_matches = client.stable_identity.startswith(expected_identity + suffix)
            else:
                identity_matches = client.stable_identity == expected_identity
            if not identity_matches:
                await client.close()
                raise AppError(
                    ErrorCode.AUTHORIZATION,
                    "resolved target identity changed",
                )
            self._clients[target] = client
            self._failures.pop(target, None)
            return client

    def resolved_identity(self, target: str) -> str | None:
        client = self._clients.get(target)
        if client is None or not getattr(client, "is_connected", True):
            return None
        return client.stable_identity

    def status(self, default_target: str) -> dict[str, Any]:
        targets: list[dict[str, object]] = []
        for name, config in self._targets.items():
            if name in self._clients:
                state = "connected"
            elif name in self._failures:
                state = "unavailable"
            else:
                state = "not_connected"
            targets.append(
                {
                    "name": name,
                    "type": config.type,
                    "configured_identity": config.stable_identity,
                    "resolved_identity": self.resolved_identity(name),
                    "status": state,
                    "is_default": name == default_target,
                }
            )
        return {"default_target": default_target, "targets": targets}

    async def close(self) -> None:
        clients, self._clients = self._clients, {}
        for client in clients.values():
            try:
                await client.close()
            except Exception as exc:
                logger.warning("Failed to close a target client: %s", type(exc).__name__)
