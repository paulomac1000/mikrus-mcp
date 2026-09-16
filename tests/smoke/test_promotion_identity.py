from __future__ import annotations

import hashlib
import json
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

from scripts.promote_digest import Promoter, RegistryClient, RegistryRef

REGISTRY_IMAGE = (
    "registry:2@sha256:a3d8aaa63ed8681a604f1dea0aa03f100d5895b6a58ace528858a7b332415373"
)
_CONFIG_MEDIA = "application/vnd.oci.image.config.v1+json"
_LAYER_MEDIA = "application/vnd.oci.image.layer.v1.tar+gzip"
_MANIFEST_MEDIA = "application/vnd.oci.image.manifest.v1+json"


def _docker_available() -> bool:
    return shutil.which("docker") is not None


@pytest.mark.skipif(
    not _docker_available(), reason="TODO(disposable-registry): docker CLI unavailable"
)
@pytest.mark.smoke
class TestExactDigestPromotion:
    @pytest.fixture()
    def registry_port(self) -> Iterator[int]:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        docker = shutil.which("docker")
        assert docker is not None
        container = subprocess.run(  # noqa: S603
            [
                docker,
                "run",
                "--rm",
                "-d",
                "-p",
                f"127.0.0.1:{port}:5000",
                REGISTRY_IMAGE,
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        base = f"http://127.0.0.1:{port}/v2/"
        try:
            deadline = time.monotonic() + 30
            ready = False
            while time.monotonic() < deadline:
                try:
                    with urllib.request.urlopen(base, timeout=2) as response:
                        ready = response.status == 200
                except (urllib.error.URLError, OSError):
                    ready = False
                if ready:
                    break
                time.sleep(0.2)
            if not ready:
                pytest.fail("disposable registry did not become ready")
            yield port
        finally:
            subprocess.run([docker, "rm", "-f", container], capture_output=True)  # noqa: S603

    def _client(self, repository: str, port: int) -> RegistryClient:
        from scripts.promote_digest import Credentials

        return RegistryClient(
            RegistryRef(f"127.0.0.1:{port}", repository), Credentials(None, None), True
        )

    def _push_synthetic_image(
        self, client: RegistryClient, *, layer_body: bytes = b"synthetic-layer-bytes"
    ) -> str:
        config = json.dumps(
            {"architecture": "amd64", "os": "linux", "rootfs": {"type": "layers", "diff_ids": []}}
        ).encode()
        layer = layer_body
        config_digest = f"sha256:{hashlib.sha256(config).hexdigest()}"
        layer_digest = f"sha256:{hashlib.sha256(layer).hexdigest()}"
        client.upload_blob(config_digest, config)
        client.upload_blob(layer_digest, layer)
        manifest = json.dumps(
            {
                "schemaVersion": 2,
                "mediaType": _MANIFEST_MEDIA,
                "config": {
                    "mediaType": _CONFIG_MEDIA,
                    "digest": config_digest,
                    "size": len(config),
                },
                "layers": [{"mediaType": _LAYER_MEDIA, "digest": layer_digest, "size": len(layer)}],
            }
        ).encode()
        manifest_digest = f"sha256:{hashlib.sha256(manifest).hexdigest()}"
        client.put_manifest(manifest_digest, manifest, _MANIFEST_MEDIA)
        return manifest_digest

    def test_validated_digest_equals_promoted_digest(self, registry_port: int) -> None:
        quarantine = self._client("campaign-quarantine", registry_port)
        digest = self._push_synthetic_image(quarantine)
        production = self._client("campaign-production", registry_port)
        results = Promoter(quarantine, production).promote(
            digest, [f"sha-campaign-{digest[7:19]}", "v0.0.0-campaign"]
        )
        assert all(verified == digest for verified in results.values())
        body, media_type = production.get_manifest("v0.0.0-campaign")
        assert f"sha256:{hashlib.sha256(body).hexdigest()}" == digest
        assert media_type == _MANIFEST_MEDIA

    def test_promotion_is_idempotent_for_same_digest(self, registry_port: int) -> None:
        quarantine = self._client("idem-quarantine", registry_port)
        digest = self._push_synthetic_image(quarantine)
        production = self._client("idem-production", registry_port)
        Promoter(quarantine, production).promote(digest, ["v0.0.0-idem"])
        Promoter(quarantine, production).promote(digest, ["v0.0.0-idem"])
        body, _ = production.get_manifest("v0.0.0-idem")
        assert f"sha256:{hashlib.sha256(body).hexdigest()}" == digest

    def test_substituted_digest_fails_closed(self, registry_port: int) -> None:
        import sys as _sys

        from scripts.promote_digest import main as promote_main

        quarantine = self._client("subst-quarantine", registry_port)
        digest = self._push_synthetic_image(quarantine)
        other = self._push_synthetic_image(quarantine, layer_body=b"substituted-layer-bytes")
        assert other != digest
        production_repo = "subst-production"
        argv = _sys.argv
        _sys.argv = [
            "promote_digest.py",
            "--source-ref",
            f"127.0.0.1:{registry_port}/subst-quarantine",
            "--digest",
            other,
            "--expected-digest",
            digest,
            "--destination-ref",
            f"127.0.0.1:{registry_port}/{production_repo}",
            "--tag",
            "v0.0.0-subst",
            "--allow-insecure-loopback-registry",
        ]
        try:
            with pytest.raises(SystemExit):
                promote_main()
        finally:
            _sys.argv = argv
        with pytest.raises(SystemExit):
            self._client(production_repo, registry_port).get_manifest("v0.0.0-subst")

    def test_http_outside_loopback_is_rejected(self) -> None:
        with pytest.raises(SystemExit):
            RegistryRef.parse("ghcr.io/owner/repo", "--source-ref").base_url(True)


def test_publisher_workflow_never_loads_runs_or_builds_candidate() -> None:
    publish = (
        Path(__file__).resolve().parents[2] / ".github" / "workflows" / "publish.yml"
    ).read_text(encoding="utf-8")
    publish_block = publish.split("\n  publish:", 1)[1].split("\n  release:", 1)[0]
    for marker in (
        "docker load",
        "docker run",
        "docker build",
        "docker create",
        "actions/checkout",
    ):
        assert marker not in publish_block, f"protected publisher uses forbidden {marker!r}"
    assert "bundle/release/promote_digest.py" in publish_block
    assert "--expected-digest" in publish_block
    assert "id: promote" in publish_block
    assert "${{ steps.promote.outputs.subject_name }}" in publish_block
    assert "${{ steps.promote.outputs.digest }}" in publish_block
    digest_verify_block = publish_block.split("trusted digest before any credential use", 1)[1]
    assert "sha256sum bundle/release/promote_digest.py" in digest_verify_block
    assert "do not match the trusted digest; refusing" in digest_verify_block
    validate_block = publish.split("\n  validate-release:", 1)[1].split("\n  publish:", 1)[0]
    assert "docker load" in validate_block
    assert "digest=" in validate_block
    assert "${QUARANTINE_REPOSITORY,,}" in validate_block


def test_promoter_content_digest_is_pinned_full_sha256() -> None:
    import hashlib
    import re

    root = Path(__file__).resolve().parents[2]
    publish = (root / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")
    match = re.search(r"PROMOTER_CONTENT_SHA256: ([0-9a-f]{64})", publish)
    assert match is not None, "PROMOTER_CONTENT_SHA256 must be a pinned 64-hex digest"
    pinned = match.group(1)
    script = (root / "scripts" / "promote_digest.py").read_bytes()
    assert hashlib.sha256(script).hexdigest() == pinned, (
        "scripts/promote_digest.py drifted from the workflow-pinned digest; "
        "update PROMOTER_CONTENT_SHA256 in the same reviewed commit"
    )


def test_realm_url_host_is_validated_not_prefix_matched() -> None:
    from scripts.promote_digest import Credentials, RegistryClient, RegistryRef

    client = RegistryClient(RegistryRef("ghcr.io", "owner/repo"), Credentials("u", "p"), False)
    client._authenticate(
        'Bearer realm="http://localhost.attacker.example/token",service="ghcr.io"'
    ) if False else None
    import pytest as _pytest

    with _pytest.raises(SystemExit):
        client._authenticate(
            'Bearer realm="http://localhost.attacker.example/token",service="ghcr.io"'
        )
    with _pytest.raises(SystemExit):
        client._authenticate('Bearer realm="http://127.0.0.1.attacker.example/token",service="s"')
    with _pytest.raises(SystemExit):
        client._authenticate('Bearer realm="http://192.168.0.5/token",service="s"')


def test_bearer_challenge_parser_preserves_comma_inside_quotes() -> None:
    from scripts.promote_digest import _parse_challenge

    params = _parse_challenge(
        'Bearer realm="https://ghcr.io/token",service="ghcr.io",'
        'scope="repository:owner/repo:pull,push"'
    )
    assert params["realm"] == "https://ghcr.io/token"
    assert params["service"] == "ghcr.io"
    assert params["scope"] == "repository:owner/repo:pull,push"


def test_mount_treats_202_as_session_not_mount() -> None:
    from unittest import mock

    from scripts.promote_digest import Credentials, RegistryClient, RegistryRef

    destination = RegistryClient(RegistryRef("127.0.0.1:1", "dst"), Credentials(None, None), True)

    class FakeResponse:
        status = 202
        headers = {"Location": "/v2/dst/blobs/uploads/session"}

        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            return None

    with mock.patch.object(destination, "_open", return_value=FakeResponse()):
        assert destination.mount_blob("sha256:" + "a" * 64, "src") is False
