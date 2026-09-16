#!/usr/bin/env python3
"""Promote an exact OCI digest between registries without docker or image bytes.

The protected publisher receives only an immutable source identity
(registry/repository/digest) plus the tags it is allowed to apply, and copies
manifests and blobs through the OCI Distribution API. It never loads, runs, or
rebuilds candidate image bytes and cannot widen beyond the exact digest and
tags supplied on its command line. Insecure (plain HTTP) registries are
admitted only for loopback hosts so disposable-registry regressions can run.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from http.client import HTTPResponse

DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
INDEX_MEDIA_TYPES = frozenset(
    {
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
    }
)
MANIFEST_MEDIA_TYPES = frozenset(
    {
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    }
)
ACCEPT_MANIFESTS = ", ".join(sorted(INDEX_MEDIA_TYPES | MANIFEST_MEDIA_TYPES))
MAX_BLOB_BYTES = 2 * 1024 * 1024 * 1024


class PromotionError(SystemExit):
    def __init__(self, message: str) -> None:
        super().__init__(f"promote_digest: {message}")


@dataclass(frozen=True)
class RegistryRef:
    registry: str
    repository: str

    @classmethod
    def parse(cls, value: str, label: str) -> RegistryRef:
        if "/" not in value:
            raise PromotionError(f"{label} must be <registry>/<repository>: {value!r}")
        registry, repository = (part.strip("/") for part in value.split("/", 1))
        if not registry or not repository:
            raise PromotionError(f"{label} is not a valid registry reference: {value!r}")
        return cls(registry=registry, repository=repository)

    def base_url(self, allow_http: bool) -> str:
        host = self.registry.split(":", 1)[0].lower()
        if allow_http and host not in LOOPBACK_HOSTS:
            raise PromotionError(
                f"plain HTTP is admitted only for loopback registries, not {self.registry!r}"
            )
        scheme = "http" if allow_http else "https"
        return f"{scheme}://{self.registry}/v2/{self.repository}"


@dataclass(frozen=True)
class Credentials:
    username: str | None
    password: str | None

    def basic_header(self) -> str | None:
        if self.username is None or self.password is None:
            return None
        encoded = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
        return f"Basic {encoded}"


def _env_credentials(prefix: str) -> Credentials:
    username = os.environ.get(f"{prefix}_USERNAME") or None
    password = os.environ.get(f"{prefix}_PASSWORD") or None
    if (username is None) != (password is None):
        raise PromotionError(f"{prefix}_USERNAME and {prefix}_PASSWORD must be set together")
    return Credentials(username=username, password=password)


def _assert_registry_scheme(url: str) -> None:
    scheme, host = urllib.parse.urlsplit(url).scheme, urllib.parse.urlsplit(url).hostname
    if scheme == "https":
        return
    if scheme == "http" and host is not None and host.lower() in LOOPBACK_HOSTS:
        return
    raise PromotionError(f"refusing non-registry URL: {url[:60]!r}")


def _parse_challenge(challenge: str) -> dict[str, str]:
    body = challenge[len("bearer ") :]
    params: dict[str, str] = {}
    index = 0
    length = len(body)
    while index < length:
        equals = body.find("=", index)
        if equals == -1:
            break
        key = body[index:equals].strip()
        index = equals + 1
        if index < length and body[index] == '"':
            closing = body.find('"', index + 1)
            if closing == -1:
                break
            value = body[index + 1 : closing]
            index = closing + 1
        else:
            comma = body.find(",", index)
            if comma == -1:
                value = body[index:].strip()
                index = length
            else:
                value = body[index:comma].strip()
                index = comma
        if key:
            params[key] = value
        while index < length and body[index] == ",":
            index += 1
    return params


class RegistryClient:
    """Minimal OCI Distribution API client with bearer-token authentication."""

    def __init__(self, ref: RegistryRef, credentials: Credentials, allow_http: bool) -> None:
        self.ref = ref
        self.credentials = credentials
        self._base = ref.base_url(allow_http)
        self._token: str | None = None

    def _url(self, path: str, **query: str) -> str:
        base = f"{self._base}/{path}"
        if query:
            base = f"{base}?{urllib.parse.urlencode(query)}"
        return base

    def _authenticate(self, challenge: str) -> None:
        if not challenge.lower().startswith("bearer "):
            raise PromotionError(
                f"{self.ref.registry}: unsupported authentication challenge: {challenge[:80]!r}"
            )
        params = _parse_challenge(challenge)
        realm = params.get("realm", "").strip('"')
        if not realm:
            raise PromotionError(f"{self.ref.registry}: bearer challenge without realm")
        query: dict[str, str] = {}
        service = params.get("service", "").strip('"')
        scope = params.get("scope", "").strip('"')
        if service:
            query["service"] = service
        if scope:
            query["scope"] = scope
        url = f"{realm}?{urllib.parse.urlencode(query)}" if query else realm
        _assert_registry_scheme(url)
        request = urllib.request.Request(url)
        basic = self.credentials.basic_header()
        if basic is not None:
            request.add_header("Authorization", basic)
        try:
            with urllib.request.urlopen(request, timeout=60) as token_response:
                payload = json.load(token_response)
        except (urllib.error.URLError, OSError, ValueError) as error:
            raise PromotionError(f"{self.ref.registry}: token request failed: {error}") from error
        token = payload.get("token") or payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise PromotionError(f"{self.ref.registry}: token endpoint returned no token")
        self._token = token

    def _open(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        data: bytes | None = None,
        allow_status: frozenset[int] = frozenset(),
    ) -> HTTPResponse:
        _assert_registry_scheme(url)
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Accept", ACCEPT_MANIFESTS)
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        if self._token is not None:
            request.add_header("Authorization", f"Bearer {self._token}")
        else:
            basic = self.credentials.basic_header()
            if basic is not None:
                request.add_header("Authorization", basic)
        try:
            response = urllib.request.urlopen(request, timeout=300)
            return response  # type: ignore[no-any-return]
        except urllib.error.HTTPError as error:
            if error.code == 401 and self._token is None:
                self._authenticate(error.headers.get("WWW-Authenticate", ""))
                return self._open(
                    method, url, headers=headers, data=data, allow_status=allow_status
                )
            if error.code in allow_status:
                return error  # type: ignore[return-value]
            raise PromotionError(f"{method} {url} failed: HTTP {error.code}") from error
        except (urllib.error.URLError, OSError) as error:
            raise PromotionError(f"{method} {url} failed: {error}") from error

    def get_manifest(self, reference: str) -> tuple[bytes, str]:
        with self._open("GET", self._url(f"manifests/{reference}")) as response:
            body = response.read()
            media_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip()
        if not body:
            raise PromotionError(f"{self.ref.registry}: empty manifest for {reference}")
        return body, media_type or "application/vnd.oci.image.manifest.v1+json"

    def get_blob(self, digest: str) -> bytes:
        with self._open("GET", self._url(f"blobs/{digest}")) as response:
            data = response.read(MAX_BLOB_BYTES + 1)
        if len(data) > MAX_BLOB_BYTES:
            raise PromotionError(f"source blob {digest} exceeds the bounded transfer limit")
        return data

    def blob_exists(self, digest: str) -> bool:
        response = self._open("HEAD", self._url(f"blobs/{digest}"), allow_status=frozenset({404}))
        with response:
            return response.status != 404

    def mount_blob(self, digest: str, source_repository: str) -> bool:
        """Mount only when the registry reports the cross-repository mount (201).

        202 Accepted means an upload session was started without mounting; the
        caller must then fall back to streaming the blob from the source.
        """
        url = self._url("blobs/uploads/", mount=digest, **{"from": source_repository})
        with self._open("POST", url) as response:
            return response.status == 201

    def upload_blob(self, digest: str, data: bytes) -> None:
        with self._open("POST", self._url("blobs/uploads/")) as response:
            location = response.headers.get("Location")
        if not location:
            raise PromotionError(f"{self.ref.registry}: blob upload returned no location")
        upload_url = urllib.parse.urljoin(f"{self._base}/", location)
        separator = "&" if "?" in upload_url else "?"
        upload_url = f"{upload_url}{separator}digest={urllib.parse.quote(digest)}"
        with self._open(
            "PUT",
            upload_url,
            headers={
                "Content-Type": "application/octet-stream",
                "Content-Length": str(len(data)),
            },
            data=data,
        ) as response:
            if not 200 <= response.status < 300:
                raise PromotionError(
                    f"{self.ref.registry}: blob upload for {digest} failed: HTTP {response.status}"
                )

    def put_manifest(self, reference: str, body: bytes, media_type: str) -> None:
        with self._open(
            "PUT",
            self._url(f"manifests/{reference}"),
            headers={"Content-Type": media_type, "Content-Length": str(len(body))},
            data=body,
        ) as response:
            if not 200 <= response.status < 300:
                raise PromotionError(
                    f"{self.ref.registry}: manifest PUT for {reference} failed: "
                    f"HTTP {response.status}"
                )


def _descriptor_blobs(manifest: dict[str, object]) -> list[str]:
    digests: list[str] = []
    config = manifest.get("config")
    if isinstance(config, dict) and isinstance(config.get("digest"), str):
        digests.append(str(config["digest"]))
    layers = manifest.get("layers")
    if isinstance(layers, list):
        for layer in layers:
            if isinstance(layer, dict) and isinstance(layer.get("digest"), str):
                digests.append(str(layer["digest"]))
    subject = manifest.get("subject")
    if isinstance(subject, dict) and isinstance(subject.get("digest"), str):
        digests.append(str(subject["digest"]))
    return digests


def _validate_descriptor_digests(payload: dict[str, object], label: str) -> None:
    for digest in _descriptor_blobs(payload):
        if DIGEST_PATTERN.fullmatch(digest) is None:
            raise PromotionError(f"{label}: descriptor digest is malformed: {digest!r}")
    manifests = payload.get("manifests")
    if isinstance(manifests, list):
        for entry in manifests:
            if isinstance(entry, dict) and isinstance(entry.get("digest"), str):
                if DIGEST_PATTERN.fullmatch(str(entry["digest"])) is None:
                    raise PromotionError(f"{label}: child digest is malformed: {entry['digest']!r}")


class Promoter:
    def __init__(self, source: RegistryClient, destination: RegistryClient) -> None:
        self.source = source
        self.destination = destination
        self._copied_manifests: dict[str, tuple[bytes, str]] = {}
        self._present_blobs: set[str] = set()

    def _ensure_blob(self, digest: str) -> None:
        if digest in self._present_blobs:
            return
        if self.destination.blob_exists(digest):
            self._present_blobs.add(digest)
            return
        if self.destination.mount_blob(digest, self.source.ref.repository):
            self._present_blobs.add(digest)
            return
        blob = self.source.get_blob(digest)
        if hashlib.sha256(blob).hexdigest() != digest.split(":", 1)[1]:
            raise PromotionError(f"source blob {digest} failed integrity verification")
        self.destination.upload_blob(digest, blob)
        self._present_blobs.add(digest)

    def _copy_manifest(self, digest: str) -> tuple[bytes, str]:
        cached = self._copied_manifests.get(digest)
        if cached is not None:
            return cached
        body, media_type = self.source.get_manifest(digest)
        if hashlib.sha256(body).hexdigest() != digest.split(":", 1)[1]:
            raise PromotionError(f"source manifest {digest} failed integrity verification")
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise PromotionError(f"source manifest {digest} is not an object")
        _validate_descriptor_digests(payload, f"source manifest {digest}")
        if media_type in INDEX_MEDIA_TYPES:
            manifests = payload.get("manifests")
            children = (
                [entry["digest"] for entry in manifests if isinstance(entry, dict)]
                if isinstance(manifests, list)
                else []
            )
            for child in children:
                self._copy_manifest(str(child))
        elif media_type in MANIFEST_MEDIA_TYPES:
            for blob_digest in _descriptor_blobs(payload):
                self._ensure_blob(blob_digest)
        else:
            raise PromotionError(
                f"source manifest {digest} has unsupported media type {media_type!r}"
            )
        self.destination.put_manifest(digest, body, media_type)
        self._copied_manifests[digest] = (body, media_type)
        return body, media_type

    def promote(self, digest: str, tags: list[str]) -> dict[str, str]:
        if DIGEST_PATTERN.fullmatch(digest) is None:
            raise PromotionError(f"digest is malformed: {digest!r}")
        for tag in tags:
            if (
                not tag
                or tag.startswith((".", "-"))
                or any(character in tag for character in ":/ \t")
            ):
                raise PromotionError(f"tag is not a plain immutable tag: {tag!r}")
        body, media_type = self._copy_manifest(digest)
        results: dict[str, str] = {}
        for tag in tags:
            self.destination.put_manifest(tag, body, media_type)
            verified, _ = self.destination.get_manifest(tag)
            verified_digest = f"sha256:{hashlib.sha256(verified).hexdigest()}"
            if verified_digest != digest:
                raise PromotionError(
                    f"tag {tag!r} does not resolve to the promoted digest: "
                    f"{verified_digest} != {digest}"
                )
            results[tag] = verified_digest
        return results

    def verify_only(self, digest: str, tags: list[str]) -> None:
        """Read-only proof that existing production tags resolve to the digest."""
        if DIGEST_PATTERN.fullmatch(digest) is None:
            raise PromotionError(f"digest is malformed: {digest!r}")
        if not tags:
            raise PromotionError("at least one --tag is required")
        for tag in tags:
            body, _ = self.destination.get_manifest(tag)
            verified_digest = f"sha256:{hashlib.sha256(body).hexdigest()}"
            if verified_digest != digest:
                raise PromotionError(
                    f"tag {tag!r} does not resolve to the promoted digest: "
                    f"{verified_digest} != {digest}"
                )
            print(
                f"verified {self.destination.ref.registry}/"
                f"{self.destination.ref.repository}:{tag} -> {verified_digest}"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-ref", required=True, help="<registry>/<repository>")
    parser.add_argument("--digest", required=True, help="Immutable digest to promote (sha256:...)")
    parser.add_argument(
        "--expected-digest",
        help="Fail closed before any mutation when the supplied digest differs",
    )
    parser.add_argument("--destination-ref", required=True, help="<registry>/<repository>")
    parser.add_argument(
        "--tag", action="append", default=[], help="Immutable tag to apply (repeatable)"
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Read-only check that the destination tags already resolve to the digest.",
    )
    parser.add_argument(
        "--allow-insecure-loopback-registry",
        action="store_true",
        help="Allow plain HTTP for loopback registries only (disposable-registry regressions).",
    )
    parser.add_argument(
        "--source-credentials-env",
        default="SOURCE_REGISTRY",
        help="Prefix of SOURCE_REGISTRY_USERNAME/SOURCE_REGISTRY_PASSWORD variables",
    )
    parser.add_argument(
        "--destination-credentials-env",
        default="DESTINATION_REGISTRY",
        help="Prefix of DESTINATION_REGISTRY_USERNAME/DESTINATION_REGISTRY_PASSWORD variables",
    )
    args = parser.parse_args()

    source_ref = RegistryRef.parse(args.source_ref, "--source-ref")
    destination_ref = RegistryRef.parse(args.destination_ref, "--destination-ref")
    if args.expected_digest is not None:
        if DIGEST_PATTERN.fullmatch(args.expected_digest) is None:
            raise PromotionError(f"--expected-digest is malformed: {args.expected_digest!r}")
        if args.expected_digest != args.digest:
            raise PromotionError(
                "supplied digest does not match the validated expected digest; "
                "failing closed before any destination mutation"
            )
    if args.verify_only and args.expected_digest is not None:
        raise PromotionError("--verify-only takes no --expected-digest")
    if not args.tag:
        raise PromotionError("at least one --tag is required")

    source = RegistryClient(
        source_ref,
        _env_credentials(args.source_credentials_env),
        args.allow_insecure_loopback_registry,
    )
    destination = RegistryClient(
        destination_ref,
        _env_credentials(args.destination_credentials_env),
        args.allow_insecure_loopback_registry,
    )
    promoter = Promoter(source, destination)
    if args.verify_only:
        promoter.verify_only(args.digest, args.tag)
        return 0
    results = promoter.promote(args.digest, args.tag)
    for tag, verified in results.items():
        print(
            f"promoted {destination_ref.registry}/{destination_ref.repository}:{tag} -> {verified}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
