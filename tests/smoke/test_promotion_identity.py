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
    """Bootstrap consistency: the pinned trust digest matches the reviewed
    promoter bytes in this tree. Changing the promoter without changing this
    digest fails closed at publish time; changing both is a promoter trust
    transition that must land through an independently reviewed master
    commit, never silently inside a candidate."""
    import hashlib
    import re

    root = Path(__file__).resolve().parents[2]
    publish = (root / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")
    match = re.search(r"PROMOTER_CONTENT_SHA256: ([0-9a-f]{64})", publish)
    assert match is not None, "PROMOTER_CONTENT_SHA256 must be a pinned 64-hex digest"
    pinned = match.group(1)
    script = (root / "scripts" / "promote_digest.py").read_bytes()
    assert hashlib.sha256(script).hexdigest() == pinned
    assert "TRUST TRANSITION" in publish


def _parse(challenge: str) -> dict[str, str]:
    from scripts.promote_digest import _parse_challenge

    return _parse_challenge(challenge)


class TestBearerChallengeParsing:
    """Issue #38 regressions: the historical promotion failure was a
    zero-scope token produced by silently mis-parsing a challenge whose
    parameters were separated by whitespace before the comma."""

    GHCR_CHALLENGE = (
        'Bearer realm="https://ghcr.io/token",service="ghcr.io",'
        'scope="repository:owner/repo:pull,push"'
    )

    def test_exact_ghcr_no_space_challenge(self) -> None:
        params = _parse(self.GHCR_CHALLENGE)
        assert params["realm"] == "https://ghcr.io/token"
        assert params["service"] == "ghcr.io"
        assert params["scope"] == "repository:owner/repo:pull,push"

    def test_comma_followed_by_space(self) -> None:
        params = _parse(
            'Bearer realm="https://ghcr.io/token", service="ghcr.io", '
            'scope="repository:owner/repo:pull"'
        )
        assert params["service"] == "ghcr.io"
        assert params["scope"] == "repository:owner/repo:pull"

    def test_whitespace_before_comma_is_not_a_key_prefix(self) -> None:
        params = _parse(
            'Bearer realm="https://ghcr.io/token" ,service="ghcr.io" '
            ',scope="repository:owner/repo:pull,push"'
        )
        assert params["realm"] == "https://ghcr.io/token"
        assert params["service"] == "ghcr.io"
        assert params["scope"] == "repository:owner/repo:pull,push"
        assert all(not key.startswith(",") for key in params)

    def test_whitespace_around_equals(self) -> None:
        params = _parse('Bearer realm = "https://ghcr.io/token" ,\tservice\t=\t"ghcr.io"')
        assert params["realm"] == "https://ghcr.io/token"
        assert params["service"] == "ghcr.io"

    def test_comma_inside_quoted_scope_is_one_value(self) -> None:
        params = _parse('Bearer realm="https://t.io/token",scope="repository:a/b:pull,push,sync"')
        assert params["scope"] == "repository:a/b:pull,push,sync"

    def test_escaped_quote_inside_quoted_value(self) -> None:
        params = _parse(r'Bearer realm="https://t.io/token",note="pull \"push\" done"')
        assert params["note"] == 'pull "push" done'

    def test_escaped_backslash_inside_quoted_value(self) -> None:
        params = _parse(r'Bearer realm="https://t.io/token",note="a\\b"')
        assert params["note"] == "a\\b"

    def test_unquoted_token_values_are_accepted(self) -> None:
        params = _parse("Bearer realm=token.example.com,service=registry-svc")
        assert params["realm"] == "token.example.com"
        assert params["service"] == "registry-svc"

    def test_duplicate_parameters_fail_closed(self) -> None:
        with pytest.raises(SystemExit, match="duplicate challenge parameter"):
            _parse('Bearer realm="https://a/token",realm="https://b/token"')

    def test_mixed_case_duplicate_parameters_fail_closed(self) -> None:
        with pytest.raises(SystemExit, match="duplicate challenge parameter"):
            _parse('Bearer realm="https://a/token",Realm="https://b/token"')

    def test_case_insensitive_parameter_names_are_normalized(self) -> None:
        params = _parse('Bearer REALM="https://t.io/token",SCOPE="repository:a/b:pull"')
        assert params["realm"] == "https://t.io/token"
        assert params["scope"] == "repository:a/b:pull"

    def test_missing_realm_fails_closed(self) -> None:
        with pytest.raises(SystemExit, match="without realm"):
            _parse('Bearer service="ghcr.io"')

    def test_empty_realm_fails_closed(self) -> None:
        with pytest.raises(SystemExit, match="without realm"):
            _parse('Bearer realm="",service="ghcr.io"')

    def test_empty_quoted_scope_fails_closed(self) -> None:
        with pytest.raises(SystemExit, match="empty challenge parameter value"):
            _parse('Bearer realm="https://t.io/token",scope=""')

    def test_control_character_in_quoted_value_fails_closed(self) -> None:
        with pytest.raises(SystemExit, match="invalid character in quoted challenge parameter"):
            _parse('Bearer realm="https://t.io/token",scope="a\x01b"')

    def test_escaped_invalid_character_fails_closed(self) -> None:
        with pytest.raises(SystemExit, match="invalid escaped character"):
            _parse('Bearer realm="https://t.io/token",scope="a\\\x7fb"')

    def test_unterminated_quote_fails_closed(self) -> None:
        with pytest.raises(SystemExit, match="unterminated"):
            _parse('Bearer realm="https://ghcr.io/token')

    def test_dangling_escape_fails_closed(self) -> None:
        with pytest.raises(SystemExit, match="dangling escape"):
            _parse('Bearer realm="abc\\')

    def test_dangling_separator_fails_closed(self) -> None:
        with pytest.raises(SystemExit, match="dangling parameter separator"):
            _parse('Bearer realm="https://t.io/token",')

    def test_parameter_without_value_fails_closed(self) -> None:
        with pytest.raises(SystemExit, match="has no value"):
            _parse('Bearer realm="https://t.io/token",service')

    def test_empty_value_fails_closed(self) -> None:
        with pytest.raises(SystemExit, match="empty challenge parameter value"):
            _parse('Bearer realm="https://t.io/token",service=')

    def test_non_token_parameter_name_fails_closed(self) -> None:
        with pytest.raises(SystemExit, match="malformed challenge parameter name"):
            _parse('Bearer re"alm="https://t.io/token"')

    def test_quoted_parameter_name_fails_closed(self) -> None:
        with pytest.raises(SystemExit, match="malformed challenge parameter name"):
            _parse('Bearer "realm"="https://t.io/token"')

    def test_unquoted_value_with_non_token_characters_fails_closed(self) -> None:
        # ':' and '/' are not token characters; a registry that omits the
        # quotes around a URL realm is ambiguous and must not be guessed.
        with pytest.raises(SystemExit, match="is not a token"):
            _parse("Bearer realm=https://t.io/token")

    def test_trailing_garbage_fails_closed(self) -> None:
        with pytest.raises(SystemExit, match="trailing challenge data"):
            _parse('Bearer realm="https://t.io/token" junk')

    def test_missing_scheme_fails_closed(self) -> None:
        with pytest.raises(SystemExit, match="malformed bearer challenge"):
            _parse('realm="https://t.io/token"')

    def test_empty_challenge_body_fails_closed(self) -> None:
        with pytest.raises(SystemExit, match="malformed bearer challenge"):
            _parse("Bearer ")


class TestAuthenticateUsesParsedChallenge:
    """End-to-end: after the parser fix the token exchange must carry the
    service and scope exactly as the registry announced them, even when the
    challenge separates parameters with whitespace before the comma."""

    def test_whitespace_mangled_challenge_requests_full_scope(self) -> None:
        import threading
        import urllib.parse
        from http.server import BaseHTTPRequestHandler, HTTPServer

        from scripts.promote_digest import Credentials, RegistryClient, RegistryRef

        token_requests: list[dict[str, list[str]]] = []
        manifest_hits = 0

        server_port = 0
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            server_port = probe.getsockname()[1]

        challenge_template = (
            f'Bearer realm="http://127.0.0.1:{server_port}/token" ,service="registry-svc" '
            ',scope="repository:owner/repo:pull,push"'
        )

        class Registry(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                nonlocal manifest_hits
                parsed = urllib.parse.urlsplit(self.path)
                if parsed.path == "/token":
                    token_requests.append(urllib.parse.parse_qs(parsed.query))
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b'{"token":"issued-token-value"}')
                    return
                if parsed.path.endswith("/manifests/check"):
                    manifest_hits += 1
                    if manifest_hits == 1:
                        self.send_response(401)
                        self.send_header("WWW-Authenticate", challenge_template)
                        self.end_headers()
                        self.wfile.write(b"{}")
                        return
                    self.send_response(200)
                    self.send_header("Content-Type", _MANIFEST_MEDIA)
                    self.end_headers()
                    self.wfile.write(b"{}")
                    return
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *args: object) -> None:
                return None

        server = HTTPServer(("127.0.0.1", server_port), Registry)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            client = RegistryClient(
                RegistryRef(f"127.0.0.1:{server_port}", "owner/repo"),
                Credentials("user", "secret"),
                True,
            )
            body, _ = client.get_manifest("check")
            assert body == b"{}"
        finally:
            server.shutdown()
        assert len(token_requests) == 1
        query = token_requests[0]
        assert query.get("service") == ["registry-svc"]
        assert query.get("scope") == ["repository:owner/repo:pull,push"]

    def test_malformed_challenge_fails_closed_without_token_request(self) -> None:
        import threading
        import urllib.parse
        from http.server import BaseHTTPRequestHandler, HTTPServer

        from scripts.promote_digest import Credentials, RegistryClient, RegistryRef

        token_hits = 0
        server_port = 0
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            server_port = probe.getsockname()[1]

        class Registry(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                nonlocal token_hits
                parsed = urllib.parse.urlsplit(self.path)
                if parsed.path == "/token":
                    token_hits += 1
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b'{"token":"should-never-be-issued"}')
                    return
                self.send_response(401)
                self.send_header(
                    "WWW-Authenticate",
                    f'Bearer realm="http://127.0.0.1:{server_port}/token",realm="other"',
                )
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *args: object) -> None:
                return None

        server = HTTPServer(("127.0.0.1", server_port), Registry)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            client = RegistryClient(
                RegistryRef(f"127.0.0.1:{server_port}", "owner/repo"),
                Credentials("user", "secret"),
                True,
            )
            with pytest.raises(SystemExit, match="duplicate challenge parameter"):
                client.get_manifest("check")
            assert token_hits == 0
        finally:
            server.shutdown()


def test_credentials_never_follow_cross_origin_redirects(tmp_path: Path) -> None:
    """P1 regression: a hostile registry redirect must not leak Basic or
    Bearer credentials to another origin."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from scripts.promote_digest import Credentials, RegistryClient, RegistryRef

    leaked: list[tuple[str, str]] = []

    class Evil(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            auth = self.headers.get("Authorization")
            if auth:
                leaked.append(("GET", auth))
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *args: object) -> None:
            return None

    evil_port = 0
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        evil_port = probe.getsockname()[1]
    server = HTTPServer(("127.0.0.1", evil_port), Evil)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = RegistryClient(
            RegistryRef("127.0.0.1:1", "owner/repo"),
            Credentials("user", "secret"),
            True,
        )
        client._token = "bearer-token-value"
        with pytest.raises(SystemExit):
            client._open(
                "GET",
                f"http://127.0.0.1:1/v2/owner/repo/manifests/redirect"
                f"?to=http://127.0.0.1:{evil_port}/steal",
            )
        assert leaked == [], leaked
    finally:
        server.shutdown()


def test_credentials_bind_to_registry_origin_only(tmp_path: Path) -> None:
    """P1 regression: token realms and blob-upload Locations pointing at
    another origin must not receive registry credentials."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from scripts.promote_digest import Credentials, RegistryClient, RegistryRef

    seen: list[tuple[str, str]] = []

    class Evil(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            auth = self.headers.get("Authorization")
            if auth:
                seen.append(("GET", auth))
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Bearer realm="https://ghcr.io/token"')
            self.end_headers()
            self.wfile.write(b"{}")

        def do_PUT(self) -> None:  # noqa: N802
            auth = self.headers.get("Authorization")
            if auth:
                seen.append(("PUT", auth))
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *args: object) -> None:
            return None

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        evil_port = probe.getsockname()[1]
    server = HTTPServer(("127.0.0.1", evil_port), Evil)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = RegistryClient(
            RegistryRef("127.0.0.1:1", "owner/repo"),
            Credentials("user", "secret"),
            True,
        )
        cross_realm = f"http://127.0.0.1:{evil_port}/token?scope=repository:owner/repo:pull,push"
        with pytest.raises(SystemExit):
            client._open("GET", cross_realm)
        digest = "sha256:" + "a" * 64
        with pytest.raises(SystemExit):
            client._open(
                "PUT",
                f"http://127.0.0.1:{evil_port}/v2/owner/repo/blobs/uploads/x?digest={digest}",
                headers={"Content-Type": "application/octet-stream"},
                data=b"x",
            )
        assert seen == [], seen
    finally:
        server.shutdown()
