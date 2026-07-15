#!/usr/bin/env python3
"""Render the website's declared release regions from a verified resolver sidecar.

This program intentionally has no network client.  The only release input it
accepts is the canonical snapshot produced by resolve-release.py and the
sibling detached source checkout it describes.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import html
from html.parser import HTMLParser
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import quote, urlparse

SOURCE_REPOSITORY = "Yeachan-Heo/gajae-code"
CHANGELOG_PATH = "packages/coding-agent/CHANGELOG.md"
FINAL_EVIDENCE_NAME = "gajae-release-packages-v1.json"
EXPECTED_EVIDENCE_NAME = "gajae-release-packages-expected-v1.json"
STATE_NAME = "release-sync.json"
CONTROL_NAME = "release-sync-control.json"

SEMVER_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
TAG_RE = re.compile(r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SHA512_RE = re.compile(r"^[0-9a-f]{128}$")
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
MARKER_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MARKER_RE = re.compile(r"<!-- release-sync:([a-z0-9]+(?:-[a-z0-9]+)*):(start|end) -->")
ISSUE_RE = re.compile(r"(?<![A-Za-z0-9_])#([1-9][0-9]*)\b")
ENTITY_RE = re.compile(r"&(?:[A-Za-z][A-Za-z0-9]*|#[0-9]+|#[xX][0-9A-Fa-f]+);")
MAX_RENDERED_CHANGELOG_BODY_BYTES = 1048576
MAX_RENDERED_CHANGELOG_ITEM_BYTES = 65536
RESERVED_PACKAGE_PREFIXES = ("@gajae-code/", "@gajae-code-sync-sandbox/")
PACKAGE_DEPENDENCY_FIELDS = ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies")

CHANGELOG_CONTINUATION_BLOCK_RE = re.compile(
    r"(?:[-+*](?:\s|$)|[1-9][0-9]*[.)](?:\s|$)|>(?:\s|$)|#{1,6}(?:\s|$)|(?:`{3,}|~{3,})(?:\s|$)|(?:-{3,}|\*{3,}|_{3,}|={3,})\s*$|\|)"
)

EXPECTED_PACKAGES = {
    "@gajae-code/agent-core": "packages/agent",
    "@gajae-code/ai": "packages/ai",
    "@gajae-code/bridge-client": "packages/bridge-client",
    "@gajae-code/coding-agent": "packages/coding-agent",
    "@gajae-code/natives": "packages/natives",
    "@gajae-code/natives-darwin-arm64": "packages/natives-darwin-arm64",
    "@gajae-code/natives-darwin-x64": "packages/natives-darwin-x64",
    "@gajae-code/natives-linux-arm64": "packages/natives-linux-arm64",
    "@gajae-code/natives-linux-x64": "packages/natives-linux-x64",
    "@gajae-code/natives-win32-x64": "packages/natives-win32-x64",
    "@gajae-code/stats": "packages/stats",
    "@gajae-code/tui": "packages/tui",
    "@gajae-code/utils": "packages/utils",
    "gajae-code": "packages/gajae-code",
}
EXPECTED_PACKAGE_NAMES = tuple(sorted(EXPECTED_PACKAGES))

REQUIRED_BINARY_ASSET_NAMES = (
    "gjc-darwin-arm64",
    "gjc-darwin-x64",
    "gjc-linux-arm64",
    "gjc-linux-x64",
    "gjc-windows-x64.exe",
)

REQUIRED_REGIONS: dict[str, tuple[str, ...]] = {
    "index.html": (
        "public-release-meta",
        "homepage-hero-badge",
        "homepage-release-strip",
    ),
    "docs/architecture.html": ("docs-nav-release-label",),
    "docs/bridge-rpc.html": ("docs-nav-release-label",),
    "docs/browser-use.html": ("docs-nav-release-label",),
    "docs/computer-use.html": ("docs-nav-release-label",),
    "docs/gajae-remote.html": ("docs-nav-release-label",),
    "docs/getting-started.html": ("docs-nav-release-label",),
    "docs/harness.html": ("docs-nav-release-label",),
    "docs/hermes-mcp-bridge.html": ("docs-nav-release-label",),
    "docs/index.html": ("docs-nav-release-label", "docs-latest-release-card"),
    "docs/receipts.html": ("docs-nav-release-label",),
    "docs/rlm.html": ("docs-nav-release-label",),
    "docs/skills.html": ("docs-nav-release-label",),
    "docs/telegram-onboarding.html": ("docs-nav-release-label",),
    "docs/troubleshooting.html": ("docs-nav-release-label",),
    "docs/whats-new.html": (
        "docs-nav-release-label",
        "whats-new-meta-description",
        "whats-new-title",
        "whats-new-hero",
        "whats-new-body",
    ),
}


class ReleaseSyncError(RuntimeError):
    """An invalid release or generated website state."""


def fail(message: str) -> None:
    raise ReleaseSyncError(message)


def require_real_directory(path: Path, label: str) -> Path:
    """Return a real root without accepting a symlink at the supplied root."""
    candidate = path.absolute()
    try:
        info = candidate.lstat()
    except OSError as exc:
        fail(f"could not inspect {label} {candidate}: {exc}")
    if candidate.is_symlink() or not stat.S_ISDIR(info.st_mode):
        fail(f"{label} must be a real directory, not a symlink or other file")
    return candidate


def require_real_child(root: Path, path: Path, label: str, *, regular: bool = False) -> Path:
    """Reject lexical, resolved, and component-level escapes from ``root``."""
    lexical_root = root.absolute()
    candidate = path.absolute()
    try:
        resolved_root = require_real_directory(lexical_root, "declared root").resolve(strict=True)
    except OSError as exc:
        fail(f"could not resolve declared root {lexical_root}: {exc}")
    inspection_root = lexical_root
    try:
        relative = candidate.relative_to(lexical_root)
    except ValueError:
        inspection_root = resolved_root
        try:
            relative = candidate.relative_to(resolved_root)
        except ValueError:
            fail(f"{label} is outside its declared root")
    current = inspection_root
    for component in relative.parts:
        current /= component
        try:
            info = current.lstat()
        except OSError as exc:
            fail(f"could not inspect {label} {current}: {exc}")
        if current.is_symlink():
            fail(f"{label} has a symlinked path component: {current}")
        if current != candidate and not stat.S_ISDIR(info.st_mode):
            fail(f"{label} has a non-directory path component: {current}")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(resolved_root)
    except ValueError:
        fail(f"{label} resolves outside its declared root")
    except OSError as exc:
        fail(f"could not resolve {label} {candidate}: {exc}")
    if regular:
        try:
            info = candidate.lstat()
        except OSError as exc:
            fail(f"could not inspect {label} {candidate}: {exc}")
        if not stat.S_ISREG(info.st_mode):
            fail(f"{label} must be a regular non-symlink file")
    return resolved


def git_environment() -> dict[str, str]:
    """Use only Git settings needed by this protocol; ambient Git is untrusted."""
    return {
        "GIT_ASKPASS": os.devnull,
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_CONFIG_COUNT": "0",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_OPTIONAL_LOCKS": "0",
        "LC_ALL": "C",
        "PATH": os.defpath,
    }


def source_status_is_clean(source_dir: Path) -> bool:
    return not git(source_dir, "status", "--porcelain=v1", "--untracked-files=all", "--ignored=matching")


def is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)

def require_schema_version(value: Any, label: str) -> int:
    if not is_int(value) or value != 1:
        fail(f"{label} must equal 1 and be an integer")
    return value



def strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            fail(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def reject_noncanonical_numbers(value: Any, label: str) -> None:
    if isinstance(value, float):
        fail(f"{label} contains a floating-point value")
    if isinstance(value, dict):
        for key, child in value.items():
            reject_noncanonical_numbers(child, f"{label}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_noncanonical_numbers(child, f"{label}[{index}]")


def canonical_json(value: Any) -> bytes:
    reject_noncanonical_numbers(value, "JSON")
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def compact_canonical_json(value: Any) -> bytes:
    reject_noncanonical_numbers(value, "JSON")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def read_canonical_json(path: Path, label: str) -> Any:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        fail(f"could not read {label} {path}: {exc}")
    if raw.startswith(b"\xef\xbb\xbf"):
        fail(f"{label} must not contain a UTF-8 BOM")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=strict_object)
    except (UnicodeDecodeError, json.JSONDecodeError, ReleaseSyncError) as exc:
        fail(f"invalid {label} JSON: {exc}")
    reject_noncanonical_numbers(value, label)
    if raw != canonical_json(value):
        fail(f"{label} is not canonical UTF-8 sorted JSON with one trailing LF")
    return value


def require_keys(value: Any, keys: Iterable[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail(f"{label} must be an object")
    actual = set(value)
    expected = set(keys)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        fail(f"{label} has invalid keys (missing={missing}, unknown={unknown})")
    return value


def require_string(value: Any, label: str) -> str:
    if not isinstance(value, str):
        fail(f"{label} must be a string")
    return value


def require_positive_int(value: Any, label: str) -> int:
    if not is_int(value) or value <= 0:
        fail(f"{label} must be a positive integer")
    return value


def require_nonnegative_int(value: Any, label: str) -> int:
    if not is_int(value) or value < 0:
        fail(f"{label} must be a nonnegative integer")
    return value


def require_match(value: Any, expression: re.Pattern[str], label: str) -> str:
    text = require_string(value, label)
    if expression.fullmatch(text) is None:
        fail(f"{label} has invalid syntax")
    return text


def require_semver(value: Any, label: str) -> str:
    return require_match(value, SEMVER_RE, label)


def release_url(version: str) -> str:
    return f"https://github.com/{SOURCE_REPOSITORY}/releases/tag/v{version}"


def validate_timestamp(value: Any, label: str) -> str:
    timestamp = require_match(value, TIMESTAMP_RE, label)
    try:
        # strptime also rejects invalid calendar days.
        from datetime import datetime

        datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        fail(f"{label} is not a valid UTC timestamp")
    return timestamp
def is_reserved_package_name(name: Any) -> bool:
    return isinstance(name, str) and name.startswith(RESERVED_PACKAGE_PREFIXES)
def require_dependency_name(value: Any, label: str) -> str:
    name = require_string(value, label)
    if is_reserved_package_name(name) and name not in EXPECTED_PACKAGES:
        fail(f"{label} contains unknown reserved package {name!r}")
    return name






def validate_integrity(value: Any, label: str) -> bytes:
    integrity = require_string(value, label)
    if not integrity.startswith("sha512-"):
        fail(f"{label} must use sha512")
    encoded = integrity[len("sha512-") :]
    try:
        digest = base64.b64decode(encoded, validate=True)
    except Exception:
        fail(f"{label} is not base64")
    if len(digest) != 64:
        fail(f"{label} does not encode a SHA-512 digest")
    return digest



def validate_internal_dependencies(value: Any, version: str, label: str) -> dict[str, str]:
    if not isinstance(value, dict):
        fail(f"{label} must be an object")
    dependencies: dict[str, str] = {}
    for name, dependency_version in value.items():
        if name not in EXPECTED_PACKAGES:
            fail(f"{label} contains unknown or sandbox package {name!r}")
        if name in dependencies:
            fail(f"{label} has duplicate dependency {name!r}")
        if require_semver(dependency_version, f"{label}.{name}") != version:
            fail(f"{label}.{name} must equal release version {version}")
        dependencies[name] = dependency_version
    if list(dependencies) != sorted(dependencies):
        fail(f"{label} keys must be sorted")
    return dependencies


def validate_package_record(record: Any, version: str, label: str) -> dict[str, Any]:
    item = require_keys(
        record,
        (
            "dir",
            "expected_sri",
            "file_count",
            "internal_dependencies",
            "manifest_sha256",
            "name",
            "registry_internal_dependencies",
            "registry_manifest_sha256",
            "registry_sri",
            "registry_tarball_sha512",
            "tarball_sha512",
            "unpacked_size",
            "version",
        ),
        label,
    )
    name = require_string(item["name"], f"{label}.name")
    if name not in EXPECTED_PACKAGES:
        fail(f"{label}.name is not an expected production package: {name!r}")
    if require_string(item["dir"], f"{label}.dir") != EXPECTED_PACKAGES[name]:
        fail(f"{label}.dir does not match {name}")
    if require_semver(item["version"], f"{label}.version") != version:
        fail(f"{label}.version does not match release version")
    for key in ("manifest_sha256", "registry_manifest_sha256"):
        require_match(item[key], SHA256_RE, f"{label}.{key}")
    tarball_sha512 = require_match(item["tarball_sha512"], SHA512_RE, f"{label}.tarball_sha512")
    registry_tarball_sha512 = require_match(
        item["registry_tarball_sha512"], SHA512_RE, f"{label}.registry_tarball_sha512"
    )
    expected_sri = validate_integrity(item["expected_sri"], f"{label}.expected_sri")
    registry_sri = validate_integrity(item["registry_sri"], f"{label}.registry_sri")
    if expected_sri != bytes.fromhex(tarball_sha512):
        fail(f"{label}.expected_sri does not match tarball_sha512")
    if registry_sri != bytes.fromhex(registry_tarball_sha512):
        fail(f"{label}.registry_sri does not match registry_tarball_sha512")

    require_nonnegative_int(item["file_count"], f"{label}.file_count")
    require_nonnegative_int(item["unpacked_size"], f"{label}.unpacked_size")
    expected_dependencies = validate_internal_dependencies(
        item["internal_dependencies"], version, f"{label}.internal_dependencies"
    )
    registry_dependencies = validate_internal_dependencies(
        item["registry_internal_dependencies"], version, f"{label}.registry_internal_dependencies"
    )
    for expected_key, observed_key in (
        ("expected_sri", "registry_sri"),
        ("manifest_sha256", "registry_manifest_sha256"),
        ("tarball_sha512", "registry_tarball_sha512"),
    ):
        if item[expected_key] != item[observed_key]:
            fail(f"{label}.{observed_key} does not match {expected_key}")
    if expected_dependencies != registry_dependencies:
        fail(f"{label}.registry_internal_dependencies does not match internal_dependencies")
    return item


def validate_final_evidence(value: Any, *, expected_sha256: str | None = None) -> dict[str, Any]:
    evidence = require_keys(
        value,
        ("expected_evidence_sha256", "packages", "release_version", "schema_version", "source_commit"),
        "final evidence",
    )
    require_schema_version(evidence["schema_version"], "final evidence.schema_version")
    version = require_semver(evidence["release_version"], "final evidence.release_version")
    require_match(evidence["source_commit"], SHA_RE, "final evidence.source_commit")
    require_match(evidence["expected_evidence_sha256"], SHA256_RE, "final evidence.expected_evidence_sha256")
    if expected_sha256 is not None and evidence["expected_evidence_sha256"] != expected_sha256:
        fail("final evidence does not link to the downloaded expected evidence asset")
    packages = evidence["packages"]
    if not isinstance(packages, list) or len(packages) != len(EXPECTED_PACKAGES):
        fail("final evidence.packages must contain exactly the 14 production packages")
    names: list[str] = []
    for index, record in enumerate(packages):
        item = validate_package_record(record, version, f"final evidence.packages[{index}]")
        names.append(item["name"])
    if names != list(EXPECTED_PACKAGE_NAMES):
        fail("final evidence packages must be unique and sorted exact production package names")
    return evidence


def validate_expected_evidence(value: Any) -> dict[str, Any]:
    evidence = require_keys(
        value,
        ("packages", "release_version", "schema_version", "source_commit"),
        "expected evidence",
    )
    require_schema_version(evidence["schema_version"], "expected evidence.schema_version")
    version = require_semver(evidence["release_version"], "expected evidence.release_version")
    require_match(evidence["source_commit"], SHA_RE, "expected evidence.source_commit")
    packages = evidence["packages"]
    if not isinstance(packages, list) or len(packages) != len(EXPECTED_PACKAGES):
        fail("expected evidence.packages must contain exactly the 14 production packages")
    names: list[str] = []
    expected_keys = {
        "dir",
        "expected_sri",
        "file_count",
        "internal_dependencies",
        "manifest_sha256",
        "name",
        "tarball_sha512",
        "unpacked_size",
        "version",
    }
    for index, record in enumerate(packages):
        item = require_keys(record, expected_keys, f"expected evidence.packages[{index}]")
        name = require_string(item["name"], f"expected evidence.packages[{index}].name")
        if name not in EXPECTED_PACKAGES or item["dir"] != EXPECTED_PACKAGES[name]:
            fail(f"expected evidence.packages[{index}] has an invalid production package")
        if require_semver(item["version"], f"expected evidence.packages[{index}].version") != version:
            fail("expected evidence package version differs from envelope")
        expected_sri = validate_integrity(
            item["expected_sri"], f"expected evidence.packages[{index}].expected_sri"
        )
        require_match(item["manifest_sha256"], SHA256_RE, f"expected evidence.packages[{index}].manifest_sha256")
        tarball_sha512 = require_match(
            item["tarball_sha512"], SHA512_RE, f"expected evidence.packages[{index}].tarball_sha512"
        )
        if expected_sri != bytes.fromhex(tarball_sha512):
            fail(f"expected evidence.packages[{index}].expected_sri does not match tarball_sha512")

        require_nonnegative_int(item["file_count"], f"expected evidence.packages[{index}].file_count")
        require_nonnegative_int(item["unpacked_size"], f"expected evidence.packages[{index}].unpacked_size")
        validate_internal_dependencies(item["internal_dependencies"], version, f"expected evidence.packages[{index}].internal_dependencies")
        names.append(name)
    if names != list(EXPECTED_PACKAGE_NAMES):
        fail("expected evidence packages must be unique and sorted exact production package names")
    return evidence


def validate_evidence_pair(expected_value: Any, final_value: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    expected = validate_expected_evidence(expected_value)
    expected_sha256 = hashlib.sha256(canonical_json(expected)).hexdigest()
    final = validate_final_evidence(final_value, expected_sha256=expected_sha256)
    if expected["source_commit"] != final["source_commit"]:
        fail("expected and final evidence source_commit values differ")
    if expected["release_version"] != final["release_version"]:
        fail("expected and final evidence release_version values differ")
    expected_records = {record["name"]: record for record in expected["packages"]}
    for final_record in final["packages"]:
        expected_record = expected_records[final_record["name"]]
        for key, expected_item in expected_record.items():
            if final_record[key] != expected_item:
                fail(f"final package evidence does not match immutable expected record for {final_record['name']}")
    return expected, final


def validate_snapshot(value: Any) -> dict[str, Any]:
    snapshot = require_keys(
        value,
        ("expected_evidence", "final_evidence", "release", "requested", "schema_version", "source_checkout"),
        "snapshot",
    )
    require_schema_version(snapshot["schema_version"], "snapshot.schema_version")
    requested = require_keys(snapshot["requested"], ("hint_tag", "mode", "source_run_url"), "snapshot.requested")
    if requested["mode"] not in ("latest", "verify-only"):
        fail("snapshot.requested.mode must be latest or verify-only")
    for key in ("hint_tag", "source_run_url"):
        require_string(requested[key], f"snapshot.requested.{key}")
    hint_tag = requested["hint_tag"]
    if hint_tag and TAG_RE.fullmatch(hint_tag) is None:
        fail("snapshot.requested.hint_tag must be empty or a stable tag")
    source_run_url = requested["source_run_url"]
    if source_run_url and re.fullmatch(
        r"https://github\.com/Yeachan-Heo/gajae-code/actions/runs/[1-9][0-9]*", source_run_url
    ) is None:
        fail("snapshot.requested.source_run_url is invalid")
    if len(source_run_url.encode("utf-8")) > 200:
        fail("snapshot.requested.source_run_url is too long")

    release = require_keys(
        snapshot["release"],
        (
            "assets",
            "draft",
            "html_url",
            "id",
            "name",
            "peeled_commit_sha",
            "prerelease",
            "published_at",
            "tag",
            "target_commitish",
        ),
        "snapshot.release",
    )
    require_positive_int(release["id"], "snapshot.release.id")
    tag = require_match(release["tag"], TAG_RE, "snapshot.release.tag")
    version = tag[1:]
    if require_string(release["name"], "snapshot.release.name") != tag:
        fail("snapshot.release.name must equal release tag")
    if require_string(release["html_url"], "snapshot.release.html_url") != release_url(version):
        fail("snapshot.release.html_url is not the canonical production release URL")
    validate_timestamp(release["published_at"], "snapshot.release.published_at")
    if release["draft"] is not False or release["prerelease"] is not False:
        fail("snapshot.release must be a finalized stable release")
    require_string(release["target_commitish"], "snapshot.release.target_commitish")
    require_match(release["peeled_commit_sha"], SHA_RE, "snapshot.release.peeled_commit_sha")
    assets = release["assets"]
    if not isinstance(assets, list):
        fail("snapshot.release.assets must be an array")
    asset_names: list[str] = []
    asset_ids: set[int] = set()
    for index, asset in enumerate(assets):
        item = require_keys(
            asset,
            ("api_url", "browser_download_url", "digest", "id", "name", "size"),
            f"snapshot.release.assets[{index}]",
        )
        asset_id = require_positive_int(item["id"], f"snapshot.release.assets[{index}].id")
        name = require_string(item["name"], f"snapshot.release.assets[{index}].name")
        require_positive_int(item["size"], f"snapshot.release.assets[{index}].size")
        api_url = require_string(item["api_url"], f"snapshot.release.assets[{index}].api_url")
        if api_url != f"https://api.github.com/repos/{SOURCE_REPOSITORY}/releases/assets/{asset_id}":
            fail(f"snapshot.release.assets[{index}].api_url is not the immutable GitHub asset identity")
        digest = require_string(item["digest"], f"snapshot.release.assets[{index}].digest")
        if re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None:
            fail(f"snapshot.release.assets[{index}].digest is not a SHA-256 digest")
        url = require_string(item["browser_download_url"], f"snapshot.release.assets[{index}].browser_download_url")
        expected_url = f"https://github.com/{SOURCE_REPOSITORY}/releases/download/{tag}/{quote(name, safe='')}"
        if url != expected_url:
            fail(f"snapshot.release.assets[{index}].browser_download_url is not canonical")
        if asset_id in asset_ids:
            fail("snapshot.release.assets has duplicate immutable asset ids")
        asset_ids.add(asset_id)
        asset_names.append(name)
    if asset_names != sorted(asset_names) or len(asset_names) != len(set(asset_names)):
        fail("snapshot.release.assets must have sorted unique names")
    if not set(REQUIRED_BINARY_ASSET_NAMES).issubset(asset_names):
        fail("snapshot.release.assets is missing a required verified binary")

    checkout = require_keys(
        snapshot["source_checkout"],
        (
            "changelog_path",
            "changelog_sha256",
            "package_evidence_asset_sha256",
            "path",
            "peeled_commit_sha",
        ),
        "snapshot.source_checkout",
    )
    if checkout["path"] != "source":
        fail("snapshot.source_checkout.path must be the exact relative sidecar name source")
    if checkout["changelog_path"] != CHANGELOG_PATH:
        fail("snapshot.source_checkout.changelog_path is not the canonical production changelog")
    require_match(checkout["changelog_sha256"], SHA256_RE, "snapshot.source_checkout.changelog_sha256")
    require_match(
        checkout["package_evidence_asset_sha256"], SHA256_RE, "snapshot.source_checkout.package_evidence_asset_sha256"
    )
    if checkout["peeled_commit_sha"] != release["peeled_commit_sha"]:
        fail("snapshot source checkout SHA differs from release SHA")

    expected, final = validate_evidence_pair(snapshot["expected_evidence"], snapshot["final_evidence"])
    if expected["source_commit"] != release["peeled_commit_sha"]:
        fail("snapshot expected evidence source_commit differs from release SHA")
    if expected["release_version"] != version:
        fail("snapshot expected evidence release_version differs from release tag")
    if final["source_commit"] != release["peeled_commit_sha"]:
        fail("snapshot final evidence source_commit differs from release SHA")
    if final["release_version"] != version:
        fail("snapshot final evidence release_version differs from release tag")
    return snapshot


def validate_state(value: Any) -> dict[str, Any]:
    state = require_keys(value, ("generated_content_sha256", "release", "schema_version", "source"), "release state")
    require_schema_version(state["schema_version"], "release state.schema_version")
    require_match(state["generated_content_sha256"], SHA256_RE, "release state.generated_content_sha256")
    release = require_keys(state["release"], ("id", "published_at", "tag", "url", "version"), "release state.release")
    require_positive_int(release["id"], "release state.release.id")
    version = require_semver(release["version"], "release state.release.version")
    if release["tag"] != f"v{version}":
        fail("release state.release.tag must equal v plus release version")
    if release["url"] != release_url(version):
        fail("release state.release.url is not canonical")
    validate_timestamp(release["published_at"], "release state.release.published_at")
    source = require_keys(state["source"], ("changelog_path", "commit_sha", "repository"), "release state.source")
    if source["repository"] != SOURCE_REPOSITORY:
        fail("release state.source.repository is not the production source repository")
    if source["changelog_path"] != CHANGELOG_PATH:
        fail("release state.source.changelog_path is invalid")
    require_match(source["commit_sha"], SHA_RE, "release state.source.commit_sha")
    return state


def validate_control(value: Any) -> dict[str, Any]:
    control = require_keys(value, ("blocked_release_ids", "mode", "reason", "schema_version"), "release control")
    require_schema_version(control["schema_version"], "release control.schema_version")
    if control["mode"] not in ("active", "hold"):
        fail("release control.mode must be active or hold")
    require_string(control["reason"], "release control.reason")
    blocked = control["blocked_release_ids"]
    if not isinstance(blocked, list):
        fail("release control.blocked_release_ids must be an array")
    ids = [require_positive_int(item, f"release control.blocked_release_ids[{index}]") for index, item in enumerate(blocked)]
    if ids != sorted(ids) or len(ids) != len(set(ids)):
        fail("release control.blocked_release_ids must be positive, sorted, and unique")
    if control["mode"] == "hold" and not control["reason"]:
        fail("release control.reason is required when mode is hold")
    return control


def git(source_dir: Path, *arguments: str) -> str:
    source_root = require_real_directory(source_dir, "source sidecar")
    git_directory = require_real_child(source_root, source_root / ".git", "source Git directory")
    if not git_directory.is_dir():
        fail("source Git directory must be a real directory")
    result = subprocess.run(
        [
            "git",
            "-c",
            "core.fsmonitor=false",
            "-c",
            f"core.hooksPath={os.devnull}",
            "--git-dir",
            os.fspath(git_directory),
            "--work-tree",
            os.fspath(source_root),
            *arguments,
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=git_environment(),
    )
    if result.returncode != 0:
        fail(f"git {' '.join(arguments)} failed: {result.stderr.strip()}")
    return result.stdout


def read_json_file(path: Path, label: str) -> Any:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        fail(f"could not read {label} {path}: {exc}")
    if raw.startswith(b"\xef\xbb\xbf"):
        fail(f"{label} must not contain a UTF-8 BOM")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=strict_object)
    except (UnicodeDecodeError, json.JSONDecodeError, ReleaseSyncError) as exc:
        fail(f"invalid {label} JSON: {exc}")
    reject_noncanonical_numbers(value, label)
    return value


CATALOG_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")


def resolve_source_dependency(
    source_root: Path,
    package_dirs: dict[str, Path],
    manifests: dict[str, dict[str, Any]],
    catalogs: dict[str, dict[str, Any]],
    owner: str,
    name: str,
    spec: Any,
) -> str:
    """Resolve the only dependency protocols accepted in a release checkout."""
    raw = require_string(spec, f"source manifest {owner} dependency {name}")
    internal = name in manifests
    if SEMVER_RE.fullmatch(raw):
        return raw
    if raw.startswith("catalog:"):
        catalog_name = raw[len("catalog:") :]
        if catalog_name == "":
            catalog = catalogs["default"]
            catalog_label = "default catalog"
        else:
            if CATALOG_NAME_RE.fullmatch(catalog_name) is None or catalog_name not in catalogs:
                fail(f"source manifest {owner} dependency {name} references an unknown named catalog")
            catalog = catalogs[catalog_name]
            catalog_label = f"named catalog {catalog_name}"
        catalog_spec = require_string(catalog.get(name), f"{catalog_label} {name}")
        if not internal:
            if not catalog_spec or catalog_spec.startswith(("catalog:", "workspace:", "file:")):
                fail(f"{catalog_label} {name} is not an exact external package declaration")
            return catalog_spec
        return require_semver(catalog_spec, f"{catalog_label} {name}")
    if raw.startswith("workspace:"):
        if not internal:
            fail(f"source manifest {owner} external dependency {name} cannot use workspace protocol")
        selector = raw[len("workspace:") :]
        if selector in ("*", "^", "~"):
            return require_semver(manifests[name].get("version"), f"source manifest version for {name}")
        return require_semver(selector, f"source manifest {owner} workspace dependency {name}")
    if raw.startswith("file:"):
        if not internal:
            fail(f"source manifest {owner} external dependency {name} cannot use file protocol")
        target_text = raw[len("file:") :]
        if not target_text or "\\" in target_text or any(token in target_text for token in ("?", "#")):
            fail(f"source manifest {owner} dependency {name} has an invalid file target")
        target_path = Path(target_text)
        if target_path.is_absolute():
            fail(f"source manifest {owner} dependency {name} file target must be relative")
        target = require_real_child(
            source_root,
            package_dirs[owner] / target_path,
            f"source manifest {owner} dependency {name} file target",
        )
        if target != package_dirs[name]:
            fail(f"source manifest {owner} dependency {name} file target does not name that package")
        return require_semver(manifests[name].get("version"), f"source manifest version for {name}")
    if internal:
        fail(f"source manifest {owner} dependency {name} has non-release specifier {raw!r}")
    return raw


def enumerate_non_private_package_manifests(source_root: Path) -> dict[str, tuple[str, Path, dict[str, Any]]]:
    packages_root = require_real_child(source_root, source_root / "packages", "source packages directory")
    if not packages_root.is_dir():
        fail("source packages directory is not a directory")
    try:
        package_entries = sorted(packages_root.iterdir(), key=lambda path: path.name)
    except OSError as exc:
        fail(f"could not enumerate source packages directory: {exc}")

    manifests: dict[str, tuple[str, Path, dict[str, Any]]] = {}
    for entry in package_entries:
        directory = require_real_child(source_root, entry, f"source package directory {entry.name}")
        if not directory.is_dir():
            continue
        manifest_path = directory / "package.json"
        try:
            manifest_path.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            fail(f"could not inspect source manifest {entry.name}: {exc}")
        candidate = require_real_child(source_root, manifest_path, f"source manifest {entry.name}", regular=True)
        manifest = read_json_file(candidate, f"source manifest {entry.name}")
        if not isinstance(manifest, dict):
            fail(f"source manifest {entry.name} must be an object")
        private = manifest.get("private", False)
        if not isinstance(private, bool):
            fail(f"source manifest {entry.name}.private must be a boolean when present")
        if private:
            continue
        name = require_string(manifest.get("name"), f"source manifest {entry.name}.name")
        if name in manifests:
            fail(f"source non-private package manifests duplicate package name {name!r}")
        manifests[name] = (directory.relative_to(packages_root.parent).as_posix(), directory, manifest)

    actual_packages = {name: package_dir for name, (package_dir, _directory, _manifest) in manifests.items()}
    if actual_packages != EXPECTED_PACKAGES:
        fail("source non-private package manifests differ from the exact expected production package set")
    return manifests


def validate_source_manifests(source_dir: Path, evidence: dict[str, Any]) -> None:
    source_root = require_real_directory(source_dir, "source checkout")
    root_manifest = read_json_file(
        require_real_child(source_root, source_root / "package.json", "source root package.json", regular=True),
        "source root package.json",
    )
    if not isinstance(root_manifest, dict):
        fail("source root package.json must be an object")
    workspaces = root_manifest.get("workspaces")
    if not isinstance(workspaces, dict) or not isinstance(workspaces.get("catalog"), dict):
        fail("source root package.json must contain workspaces.catalog")
    named_catalogs = workspaces.get("catalogs", {})
    if not isinstance(named_catalogs, dict):
        fail("source root package.json workspaces.catalogs must be an object when present")
    catalogs: dict[str, dict[str, Any]] = {"default": workspaces["catalog"]}
    for catalog_name, catalog in named_catalogs.items():
        if (
            catalog_name == "default"
            or not isinstance(catalog_name, str)
            or CATALOG_NAME_RE.fullmatch(catalog_name) is None
            or not isinstance(catalog, dict)
        ):
            fail("source root package.json has an invalid named catalog declaration")
        catalogs[catalog_name] = catalog
    if require_semver(catalogs["default"].get("@gajae-code/coding-agent"), "source catalog coding-agent") != evidence["release_version"]:
        fail("source catalog coding-agent version differs from final evidence")

    manifests: dict[str, dict[str, Any]] = {}
    package_dirs: dict[str, Path] = {}
    discovered = enumerate_non_private_package_manifests(source_root)
    for name, package_dir in EXPECTED_PACKAGES.items():
        _discovered_dir, directory, manifest = discovered[name]
        if require_semver(manifest.get("version"), f"source manifest {name}.version") != evidence["release_version"]:
            fail(f"source manifest {package_dir} does not match final evidence")
        manifests[name] = manifest
        package_dirs[name] = directory

    for record in evidence["packages"]:
        owner = record["name"]
        manifest = manifests[owner]
        observed: dict[str, str] = {}
        declarations: dict[str, str] = {}
        for field in PACKAGE_DEPENDENCY_FIELDS:
            dependencies = manifest.get(field, {})
            if not isinstance(dependencies, dict):
                fail(f"source manifest {owner}.{field} must be an object when present")
            for dependency_name, specifier in dependencies.items():
                dependency_name = require_dependency_name(
                    dependency_name, f"source manifest {owner}.{field} dependency name"
                )
                resolved = resolve_source_dependency(
                    source_root, package_dirs, manifests, catalogs, owner, dependency_name, specifier
                )
                if dependency_name not in EXPECTED_PACKAGES:
                    continue
                previous = declarations.get(dependency_name)
                if previous is not None and previous != resolved:
                    fail(f"source manifest {owner} has conflicting dependency declarations for {dependency_name}")
                declarations[dependency_name] = resolved
                observed[dependency_name] = resolved
        if dict(sorted(observed.items())) != record["internal_dependencies"]:
            fail(f"source manifest internal dependencies differ from final evidence for {owner}")

    cargo = require_real_child(source_root, source_root / "Cargo.toml", "source Cargo.toml", regular=True)
    try:
        cargo_text = cargo.read_text(encoding="utf-8")
    except OSError as exc:
        fail(f"could not read source Cargo.toml: {exc}")
    workspace_match = re.search(r"(?ms)^\[workspace\.package\]\s*(.*?)(?=^\[|\Z)", cargo_text)
    if workspace_match is None:
        fail("source Cargo.toml is missing [workspace.package]")
    cargo_version = re.search(r'^version\s*=\s*"([^"]+)"\s*$', workspace_match.group(1), re.MULTILINE)
    if cargo_version is None or cargo_version.group(1) != evidence["release_version"]:
        fail("source Cargo workspace version differs from final evidence")


def validate_changelog_continuation(value: str, path: str, line: int) -> None:
    if value[0].isspace() or CHANGELOG_CONTINUATION_BLOCK_RE.match(value) is not None:
        fail(f"unsupported changelog continuation block syntax at {path}:{line}")


def parse_changelog(changelog_bytes: bytes, version: str, published_at: str, path: str) -> list[tuple[str, list[str]]]:
    try:
        changelog = changelog_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        fail(f"changelog is not UTF-8: {exc}")
    if "\r" in changelog:
        fail("changelog must use LF line endings")
    lines = changelog.splitlines(keepends=True)
    heading = re.compile(r"^## \[" + re.escape(version) + r"\] - (\d{4}-\d{2}-\d{2})\n?$")
    matching: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        match = heading.fullmatch(line)
        if match is not None:
            matching.append((index, match.group(1)))
    if len(matching) != 1:
        fail(f"changelog must contain exactly one section for {version}")
    start, heading_date = matching[0]
    try:
        heading_day = date.fromisoformat(heading_date)
        published_day = date.fromisoformat(published_at[:10])
    except ValueError:
        fail("changelog heading or published date is invalid")
    if heading_day > published_day:
        fail("changelog heading date must not be after the stable published date")
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("## ["):
            end = index
            break
    section = "".join(lines[start + 1 : end])
    if len(section.encode("utf-8")) > 131072:
        fail("changelog release section exceeds 131072 UTF-8 bytes")

    categories: list[tuple[str, list[str]]] = []
    current_name: str | None = None
    current_items: list[str] = []
    current_item: list[str] | None = None
    total_items = 0
    link_count = 0

    def finish_item() -> None:
        nonlocal current_item, total_items, link_count
        if current_item is None:
            return
        logical = " ".join(part.strip() for part in current_item)
        if len(logical.encode("utf-8")) > 8192:
            fail("changelog logical item exceeds 8192 UTF-8 bytes")
        rendered, links = render_inline(logical, path, start + 1)
        link_count += links
        if link_count > 64:
            fail("changelog section exceeds 64 links")
        current_items.append(rendered)
        total_items += 1
        if total_items > 200:
            fail("changelog section exceeds 200 items")
        current_item = None

    def finish_category() -> None:
        nonlocal current_name, current_items
        finish_item()
        if current_name is not None:
            if not current_items:
                fail(f"changelog category {current_name!r} has no items")
            categories.append((current_name, current_items))
        current_name = None
        current_items = []

    for offset, line_with_end in enumerate(lines[start + 1 : end], start=start + 2):
        line = line_with_end[:-1] if line_with_end.endswith("\n") else line_with_end
        if line.startswith("### "):
            finish_category()
            category = line[4:]
            if not 1 <= len(category) <= 80 or category.strip() != category:
                fail(f"invalid changelog category at {path}:{offset}")
            if any(token in category for token in ("*", "`", "[", "]", "<", ">", "&", "#", "\\")):
                fail(f"changelog category must be plain text at {path}:{offset}")
            current_name = category
            if len(categories) >= 16:
                fail("changelog section exceeds 16 categories")
            continue
        if line.startswith("- "):
            if current_name is None:
                fail(f"changelog item outside a category at {path}:{offset}")
            finish_item()
            item = line[2:]
            if not item:
                fail(f"empty changelog item at {path}:{offset}")
            current_item = [item]
            continue
        if line.startswith("  "):
            if current_item is None:
                fail(f"changelog continuation without an item at {path}:{offset}")
            continuation = line[2:]
            if not continuation.strip():
                fail(f"blank changelog continuation at {path}:{offset}")
            validate_changelog_continuation(continuation, path, offset)
            current_item.append(continuation)
            continue
        if not line:
            # A blank line terminates the current item. Release sections merged
            # from an [Unreleased] block legitimately separate sibling items
            # with blank lines (observed v0.11.0); multi-line continuations
            # still cannot contain blanks (rejected above), so this cannot
            # silently join or split continuation content.
            finish_item()
            continue
        fail(f"unsupported changelog block syntax at {path}:{offset}")
    finish_category()
    if not categories:
        fail("changelog section must contain at least one category")
    return categories


def validate_changelog_url(url: str, path: str, line: int) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.fragment or parsed.query:
        fail(f"unsupported changelog URL at {path}:{line}")
    if parsed.netloc == "github.com" and re.fullmatch(
        r"/Yeachan-Heo/gajae-code/(?:issues|pull|releases)/[^/]+(?:/[^/]+)*", parsed.path
    ):
        return url
    if parsed.netloc == "gajae-code.com" and parsed.path.startswith("/") and parsed.path != "/":
        return url
    fail(f"unsupported changelog URL at {path}:{line}")


def render_inline(text: str, path: str, line: int, *, nested: bool = False) -> tuple[str, int]:
    if not text or ENTITY_RE.search(text) or "\\" in text or "![" in text:
        fail(f"unsupported changelog inline syntax at {path}:{line}")
    output: list[str] = []
    links = 0
    index = 0
    plain_start = 0

    def flush_plain(end: int) -> None:
        nonlocal plain_start
        plain = text[plain_start:end]
        if not plain:
            return
        if any(character in plain for character in ("*", "`", "[", "]", "<", ">")):
            fail(f"unsupported changelog inline syntax at {path}:{line}")
        cursor = 0
        if nested:
            output.append(html.escape(plain, quote=False))
        else:
            for match in ISSUE_RE.finditer(plain):
                output.append(html.escape(plain[cursor : match.start()], quote=False))
                number = match.group(1)
                output.append(
                    f'<a href="https://github.com/{SOURCE_REPOSITORY}/issues/{number}" target="_blank" rel="noopener noreferrer">#{number}</a>'
                )
                cursor = match.end()
                nonlocal_links[0] += 1
            output.append(html.escape(plain[cursor:], quote=False))
        plain_start = end

    # A tiny mutable box avoids making every plain-text flush return a tuple.
    nonlocal_links = [0]
    while index < len(text):
        if text.startswith("**", index):
            flush_plain(index)
            end = text.find("**", index + 2)
            if end <= index + 2 or "**" in text[index + 2 : end]:
                fail(f"unsupported changelog inline syntax at {path}:{line}")
            inner, nested_links = render_inline(text[index + 2 : end], path, line, nested=True)
            if nested_links:
                fail(f"unsupported changelog inline syntax at {path}:{line}")
            output.append(f"<strong>{inner}</strong>")
            index = end + 2
            plain_start = index
            continue
        if text[index] == "*":
            flush_plain(index)
            end = text.find("*", index + 1)
            if end <= index + 1 or "*" in text[index + 1 : end]:
                fail(f"unsupported changelog inline syntax at {path}:{line}")
            inner, nested_links = render_inline(text[index + 1 : end], path, line, nested=True)
            if nested_links:
                fail(f"unsupported changelog inline syntax at {path}:{line}")
            output.append(f"<em>{inner}</em>")
            index = end + 1
            plain_start = index
            continue
        if text[index] == "`":
            flush_plain(index)
            end = text.find("`", index + 1)
            if end <= index + 1 or "\n" in text[index + 1 : end]:
                fail(f"unsupported changelog inline syntax at {path}:{line}")
            output.append(f"<code>{html.escape(text[index + 1 : end], quote=False)}</code>")
            index = end + 1
            plain_start = index
            continue
        if text[index] == "[":
            flush_plain(index)
            close_label = text.find("](", index + 1)
            if close_label <= index + 1:
                fail(f"unsupported changelog inline syntax at {path}:{line}")
            close_url = text.find(")", close_label + 2)
            if close_url <= close_label + 2:
                fail(f"unsupported changelog inline syntax at {path}:{line}")
            label = text[index + 1 : close_label]
            if any(character in label for character in ("*", "`", "[", "]", "<", ">", "&", "#", "\\")):
                fail(f"unsupported changelog inline syntax at {path}:{line}")
            url = validate_changelog_url(text[close_label + 2 : close_url], path, line)
            output.append(f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">{html.escape(label, quote=False)}</a>')
            nonlocal_links[0] += 1
            index = close_url + 1
            plain_start = index
            continue
        if text[index] == "<":
            flush_plain(index)
            close = text.find(">", index + 1)
            if close <= index + 1:
                fail(f"unsupported changelog inline syntax at {path}:{line}")
            url = validate_changelog_url(text[index + 1 : close], path, line)
            output.append(f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">{html.escape(url, quote=False)}</a>')
            nonlocal_links[0] += 1
            index = close + 1
            plain_start = index
            continue
        index += 1
    flush_plain(len(text))
    links += nonlocal_links[0]
    return "".join(output), links

class RenderedChangelogInlineParser(HTMLParser):
    """Accept only the inline HTML emitted by ``render_inline``."""

    def __init__(self, path: str, line: int) -> None:
        super().__init__(convert_charrefs=False)
        self.path = path
        self.line = line
        self.open_tags: list[tuple[str, bool]] = []
        self.saw_content = False
        self.link_count = 0

    def reject(self) -> None:
        fail(f"invalid rendered changelog inline HTML at {self.path}:{self.line}")

    def mark_content(self) -> None:
        self.saw_content = True
        if self.open_tags:
            tag, _has_content = self.open_tags[-1]
            self.open_tags[-1] = (tag, True)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        raw = self.get_starttag_text()
        if tag in {"strong", "em", "code"}:
            if raw != f"<{tag}>" or attrs or (self.open_tags and self.open_tags[-1][0] in {"a", "code"}):
                self.reject()
            self.open_tags.append((tag, False))
            return
        if tag != "a" or self.open_tags or len(attrs) != 3:
            self.reject()
        href, target, rel = attrs
        if href[0] != "href" or target != ("target", "_blank") or rel != ("rel", "noopener noreferrer"):
            self.reject()
        if not isinstance(href[1], str) or ENTITY_RE.search(href[1]) is not None:
            self.reject()
        validate_changelog_url(href[1], self.path, self.line)
        expected = f'<a href="{html.escape(href[1], quote=True)}" target="_blank" rel="noopener noreferrer">'
        if raw != expected:
            self.reject()
        self.open_tags.append((tag, False))
        self.link_count += 1

    def handle_endtag(self, tag: str) -> None:
        if not self.open_tags or self.open_tags[-1][0] != tag:
            self.reject()
        _tag, has_content = self.open_tags.pop()
        if not has_content:
            self.reject()
        self.mark_content()

    def handle_startendtag(self, _tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        self.reject()

    def handle_data(self, data: str) -> None:
        if any(character in data for character in ("\r", "\n", "<", ">", "&")):
            self.reject()
        if data:
            self.mark_content()

    def handle_entityref(self, name: str) -> None:
        if name not in {"amp", "lt", "gt"}:
            self.reject()
        self.mark_content()

    def handle_charref(self, _name: str) -> None:
        self.reject()

    def handle_comment(self, _data: str) -> None:
        self.reject()

    def handle_decl(self, _decl: str) -> None:
        self.reject()

    def unknown_decl(self, _data: str) -> None:
        self.reject()

    def handle_pi(self, _data: str) -> None:
        self.reject()

    def validate(self) -> None:
        if self.open_tags or not self.saw_content:
            self.reject()



def validate_rendered_changelog_item(markup: str, path: str, line: int) -> int:
    if not markup or len(markup.encode("utf-8")) > MAX_RENDERED_CHANGELOG_ITEM_BYTES:
        fail(f"invalid rendered changelog item at {path}:{line}")
    for closing_tag in re.findall(r"</[^>]*>", markup):
        if closing_tag not in {"</strong>", "</em>", "</code>", "</a>"}:
            fail(f"invalid rendered changelog inline HTML at {path}:{line}")
    parser = RenderedChangelogInlineParser(path, line)
    parser.feed(markup)
    parser.close()
    parser.validate()
    return parser.link_count


def validate_whats_new_body_template(snapshot: dict[str, Any], body: str) -> None:
    if len(body.encode("utf-8")) > MAX_RENDERED_CHANGELOG_BODY_BYTES:
        fail("docs/whats-new.html whats-new-body exceeds the rendered changelog byte limit")
    release = snapshot["release"]
    version = release["tag"][1:]
    prefix = f'      <div class="release-notes" data-release-id="{release["id"]}" data-release-version="{version}">\n'
    suffix = (
        "        <section class=\"docs-section\">\n"
        "          <h2>Upgrade</h2>\n"
        "          <pre><code>bun install -g gajae-code\n"
        "# or: bun install -g @gajae-code/coding-agent\n"
        "gjc --version &amp;&amp; gjc --smoke-test</code></pre>\n"
        f"          <p>See the full <a href=\"{release['html_url']}\" target=\"_blank\" rel=\"noopener noreferrer\">v{version} release</a> on GitHub.</p>\n"
        "        </section>\n"
        "      </div>\n"
    )
    if not body.startswith(prefix) or not body.endswith(suffix):
        fail("docs/whats-new.html whats-new-body has invalid fixed release template bytes")

    middle = body[len(prefix) : len(body) - len(suffix)]
    cursor = 0
    category_count = 0
    item_count = 0
    link_count = 0
    section_open = "        <section class=\"docs-section\">\n"
    section_close = "          </ul>\n        </section>\n"
    while cursor < len(middle):
        if not middle.startswith(section_open, cursor):
            fail("docs/whats-new.html whats-new-body has invalid changelog section grammar")
        cursor += len(section_open)
        heading_open = "          <h2>"
        if not middle.startswith(heading_open, cursor):
            fail("docs/whats-new.html whats-new-body has invalid changelog section grammar")
        cursor += len(heading_open)
        heading_end = middle.find("</h2>\n", cursor)
        if heading_end < 0:
            fail("docs/whats-new.html whats-new-body has invalid changelog section grammar")
        category = middle[cursor:heading_end]
        if (
            not 1 <= len(category) <= 80
            or category.strip() != category
            or any(token in category for token in ("*", "`", "[", "]", "<", ">", "&", "#", "\\"))
        ):
            fail("docs/whats-new.html whats-new-body has invalid changelog category grammar")
        cursor = heading_end + len("</h2>\n")
        if not middle.startswith("          <ul>\n", cursor):
            fail("docs/whats-new.html whats-new-body has invalid changelog section grammar")
        cursor += len("          <ul>\n")
        section_items = 0
        while middle.startswith("            <li>", cursor):
            cursor += len("            <li>")
            item_end = middle.find("</li>\n", cursor)
            if item_end < 0:
                fail("docs/whats-new.html whats-new-body has invalid changelog item grammar")
            item = middle[cursor:item_end]
            if "\n" in item or "\r" in item:
                fail("docs/whats-new.html whats-new-body has invalid changelog item grammar")
            link_count += validate_rendered_changelog_item(item, "docs/whats-new.html", category_count + 1)
            if link_count > 64:
                fail("docs/whats-new.html whats-new-body exceeds 64 changelog links")
            cursor = item_end + len("</li>\n")
            section_items += 1
            item_count += 1
            if item_count > 200:
                fail("docs/whats-new.html whats-new-body exceeds 200 changelog items")
        if not section_items or not middle.startswith(section_close, cursor):
            fail("docs/whats-new.html whats-new-body has invalid changelog section grammar")
        cursor += len(section_close)
        category_count += 1
        if category_count > 16:
            fail("docs/whats-new.html whats-new-body exceeds 16 changelog categories")
    if not category_count:
        fail("docs/whats-new.html whats-new-body requires at least one changelog category")


class StaticHrefParser(HTMLParser):
    """Collect real href attributes and reject duplicates or valueless hrefs."""

    def __init__(self, label: str) -> None:
        super().__init__(convert_charrefs=False)
        self.label = label
        self.start_tags: list[str] = []
        self.hrefs: list[str] = []

    def record(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.start_tags.append(tag)
        hrefs = [value for name, value in attrs if name == "href"]
        if len(hrefs) > 1 or (hrefs and not isinstance(hrefs[0], str)):
            fail(f"{self.label} has an invalid href attribute")
        if hrefs:
            self.hrefs.append(hrefs[0])

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.record(tag, attrs)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.record(tag, attrs)


def parse_static_hrefs(text: str, label: str) -> StaticHrefParser:
    parser = StaticHrefParser(label)
    parser.feed(text)
    parser.close()
    return parser

class DocsNavMarkerContextParser(HTMLParser):
    """Require the docs-nav marker pair to be the sole content of one real anchor."""

    START = "release-sync:docs-nav-release-label:start"
    END = "release-sync:docs-nav-release-label:end"

    def __init__(self, path: str) -> None:
        super().__init__(convert_charrefs=False)
        self.path = path
        self.in_anchor = False
        self.anchor_href: str | None = None
        self.marker_state = "none"
        self.unexpected_content = False
        self.pairs = 0

    def reject(self) -> None:
        fail(f"{self.path} docs-nav release marker must belong to one real whats-new anchor")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.in_anchor:
            self.unexpected_content = True
            return
        if tag != "a":
            return
        hrefs = [value for name, value in attrs if name == "href"]
        if len(hrefs) > 1 or (hrefs and not isinstance(hrefs[0], str)):
            self.reject()
        self.in_anchor = True
        self.anchor_href = hrefs[0] if hrefs else None
        self.marker_state = "none"
        self.unexpected_content = False

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag == "a" and self.in_anchor:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or not self.in_anchor:
            return
        if self.marker_state == "inside" or (self.marker_state == "after" and self.unexpected_content):
            self.reject()
        self.in_anchor = False
        self.anchor_href = None
        self.marker_state = "none"
        self.unexpected_content = False

    def handle_comment(self, data: str) -> None:
        marker = data.strip()
        if marker == self.START:
            if (
                not self.in_anchor
                or self.anchor_href != "whats-new.html"
                or self.marker_state != "none"
                or self.unexpected_content
            ):
                self.reject()
            self.marker_state = "inside"
            return
        if marker == self.END:
            if not self.in_anchor or self.anchor_href != "whats-new.html" or self.marker_state != "inside":
                self.reject()
            self.marker_state = "after"
            self.pairs += 1
            return
        if self.in_anchor:
            self.unexpected_content = True

    def handle_data(self, data: str) -> None:
        if self.in_anchor and self.marker_state != "inside" and data:
            self.unexpected_content = True

    def validate(self) -> None:
        if self.pairs != 1 or self.marker_state == "inside":
            self.reject()


def validate_docs_nav_marker_context(path: str, text: str) -> None:
    parser = DocsNavMarkerContextParser(path)
    parser.feed(text)
    parser.close()
    parser.validate()


@dataclass(frozen=True)
class Region:
    path: str
    identifier: str
    inner_start: int
    inner_end: int
    inner: str


def extract_regions(path: str, text: str) -> dict[str, Region]:
    if "\r" in text or text.startswith("\ufeff"):
        fail(f"{path} must be UTF-8 LF text without a BOM")
    expected = set(REQUIRED_REGIONS[path])
    matches = list(MARKER_RE.finditer(text))
    if text.count("<!-- release-sync:") != len(matches):
        fail(f"{path} has malformed release-sync marker syntax")
    stack: list[tuple[str, re.Match[str]]] = []
    regions: dict[str, Region] = {}
    for match in matches:
        identifier, boundary = match.group(1), match.group(2)
        if identifier not in expected:
            fail(f"{path} has an unknown release-sync marker {identifier}")
        if boundary == "start":
            if stack:
                fail(f"{path} has nested release-sync markers")
            if identifier in regions or any(item[0] == identifier for item in stack):
                fail(f"{path} has duplicate release-sync marker {identifier}")
            stack.append((identifier, match))
            continue
        if not stack:
            fail(f"{path} has an end marker without a start marker for {identifier}")
        start_identifier, start_match = stack.pop()
        if start_identifier != identifier:
            fail(f"{path} has mismatched release-sync marker boundaries")
        if identifier == "docs-nav-release-label":
            inner_start, inner_end = start_match.end(), match.start()
            inner = text[inner_start:inner_end]
            if "\n" in inner or inner != inner.strip():
                fail(f"{path} docs-nav release marker must have inline whitespace-free content")
            anchor_start = text.rfind("<a", 0, start_match.start())
            anchor_open_end = text.find(">", anchor_start, start_match.start())
            anchor_close = text.find("</a>", match.end())
            anchor_parser = parse_static_hrefs(
                text[anchor_start : anchor_open_end + 1] if anchor_start >= 0 and anchor_open_end >= 0 else "",
                f"{path} docs-nav anchor",
            )
            if (
                anchor_start < 0
                or anchor_open_end < 0
                or anchor_close < 0
                or text[anchor_open_end + 1 : start_match.start()]
                or text[match.end() : anchor_close]
                or anchor_parser.start_tags != ["a"]
                or anchor_parser.hrefs != ["whats-new.html"]
            ):
                fail(f"{path} docs-nav release marker must be the complete existing whats-new anchor content")
        else:
            start_line = text.rfind("\n", 0, start_match.start()) + 1
            start_line_end = text.find("\n", start_match.end())
            end_line = text.rfind("\n", 0, match.start()) + 1
            end_line_end = text.find("\n", match.end())
            if start_line_end < 0 or end_line_end < 0:
                fail(f"{path} non-inline release markers must end with LF")
            start_prefix = text[start_line:start_match.start()]
            end_prefix = text[end_line:match.start()]
            if (
                text[start_match.end() : start_line_end] != ""
                or text[match.end() : end_line_end] != ""
                or start_prefix.strip()
                or end_prefix.strip()
                or start_prefix != end_prefix
            ):
                fail(f"{path} non-inline release markers must occupy matching own lines")
            inner_start, inner_end = start_line_end + 1, end_line
            inner = text[inner_start:inner_end]
            if not inner.endswith("\n"):
                fail(f"{path} non-inline release marker content must end with LF")
        regions[identifier] = Region(path, identifier, inner_start, inner_end, inner)
    if stack:
        fail(f"{path} has an unclosed release-sync marker")
    if "docs-nav-release-label" in expected:
        validate_docs_nav_marker_context(path, text)
    if set(regions) != expected:
        fail(f"{path} markers do not match declared ownership (found={sorted(regions)}, expected={sorted(expected)})")
    return regions


def strip_owned_regions(path: str, text: str) -> str:
    regions = extract_regions(path, text)
    result = text
    for region in sorted(regions.values(), key=lambda item: item.inner_start, reverse=True):
        result = result[: region.inner_start] + result[region.inner_end :]
    return result


def render_regions(snapshot: dict[str, Any], categories: list[tuple[str, list[str]]]) -> dict[tuple[str, str], str]:
    release = snapshot["release"]
    version = release["tag"][1:]
    release_id = release["id"]
    commit_sha = release["peeled_commit_sha"]
    published_date = release["published_at"][:10]
    url = release["html_url"]
    nav = f"What's new (v{version})"
    rendered: dict[tuple[str, str], str] = {}
    rendered[("index.html", "public-release-meta")] = (
        f'  <meta name="gajae-release" content="{release_id}:v{version}:{commit_sha}" />\n'
    )
    rendered[("index.html", "homepage-hero-badge")] = f"        <span class=\"hero__badge\">🦀 v{version} · beta · MIT licensed</span>\n"
    rendered[("index.html", "homepage-release-strip")] = (
        "  <section class=\"section section--tight\" id=\"latest-release\">\n"
        "    <div class=\"section__header reveal\">\n"
        f"      <span class=\"section__eyebrow\">Latest stable · v{version}</span>\n"
        f"      <h2 class=\"section__title\">Gajae Code v{version}</h2>\n"
        f"      <p class=\"section__subtitle\">Published {published_date}. Release binaries and npm packages are available.</p>\n"
        "      <div class=\"hero__cta\">\n"
        "        <a href=\"docs/whats-new.html\" class=\"btn btn--primary\">Read what’s new</a>\n"
        f"        <a href=\"{url}\" class=\"btn btn--secondary\" target=\"_blank\" rel=\"noopener noreferrer\">GitHub Release</a>\n"
        "      </div>\n"
        "    </div>\n"
        "  </section>\n"
    )
    for path, identifiers in REQUIRED_REGIONS.items():
        if "docs-nav-release-label" in identifiers:
            rendered[(path, "docs-nav-release-label")] = nav
    rendered[("docs/index.html", "docs-latest-release-card")] = (
        "            <a class=\"card\" href=\"whats-new.html\">\n"
        "              <div class=\"card__icon\" aria-hidden=\"true\">✨</div>\n"
        f"              <h3 class=\"card__title\">What’s new (v{version})</h3>\n"
        "              <p class=\"card__text\">Read release highlights and upgrade guidance.</p>\n"
        "            </a>\n"
    )
    rendered[("docs/whats-new.html", "whats-new-meta-description")] = (
        f"  <meta name=\"description\" content=\"What’s new in Gajae Code v{version}, published {published_date}: release highlights and upgrade guidance.\" />\n"
    )
    rendered[("docs/whats-new.html", "whats-new-title")] = f"  <title>What’s new (v{version}) · Gajae Code Docs</title>\n"
    rendered[("docs/whats-new.html", "whats-new-hero")] = (
        "      <section class=\"docs-hero\">\n"
        "        <p class=\"eyebrow\">Documentation</p>\n"
        f"        <h1>What’s new in v{version}</h1>\n"
        f"        <p>Published {published_date}. This page is generated from the immutable release changelog.</p>\n"
        "      </section>\n"
    )
    category_parts: list[str] = []
    for category, items in categories:
        category_parts.append("        <section class=\"docs-section\">\n")
        category_parts.append(f"          <h2>{html.escape(category, quote=False)}</h2>\n")
        category_parts.append("          <ul>\n")
        for item in items:
            category_parts.append(f"            <li>{item}</li>\n")
        category_parts.append("          </ul>\n")
        category_parts.append("        </section>\n")
    rendered[("docs/whats-new.html", "whats-new-body")] = (
        f"      <div class=\"release-notes\" data-release-id=\"{release_id}\" data-release-version=\"{version}\">\n"
        + "".join(category_parts)
        + "        <section class=\"docs-section\">\n"
        + "          <h2>Upgrade</h2>\n"
        + "          <pre><code>bun install -g gajae-code\n"
        + "# or: bun install -g @gajae-code/coding-agent\n"
        + "gjc --version &amp;&amp; gjc --smoke-test</code></pre>\n"
        + f"          <p>See the full <a href=\"{url}\" target=\"_blank\" rel=\"noopener noreferrer\">v{version} release</a> on GitHub.</p>\n"
        + "        </section>\n"
        + "      </div>\n"
    )
    return rendered


def digest_regions(regions: Iterable[Region]) -> str:
    records = [
        {
            "content_sha256": hashlib.sha256(region.inner.encode("utf-8")).hexdigest(),
            "id": region.identifier,
            "path": region.path,
        }
        for region in regions
    ]
    records.sort(key=lambda item: (item["path"], item["id"]))
    return hashlib.sha256(compact_canonical_json({"schema_version": 1, "regions": records})).hexdigest()


def build_state(snapshot: dict[str, Any], digest: str) -> dict[str, Any]:
    release = snapshot["release"]
    return {
        "generated_content_sha256": digest,
        "release": {
            "id": release["id"],
            "published_at": release["published_at"],
            "tag": release["tag"],
            "url": release["html_url"],
            "version": release["tag"][1:],
        },
        "schema_version": 1,
        "source": {
            "changelog_path": snapshot["source_checkout"]["changelog_path"],
            "commit_sha": release["peeled_commit_sha"],
            "repository": SOURCE_REPOSITORY,
        },
    }


def substitute_regions(path: str, text: str, rendered: dict[tuple[str, str], str]) -> str:
    regions = extract_regions(path, text)
    result = text
    for identifier, region in sorted(regions.items(), key=lambda item: item[1].inner_start, reverse=True):
        result = result[: region.inner_start] + rendered[(path, identifier)] + result[region.inner_end :]
    if strip_owned_regions(path, text) != strip_owned_regions(path, result):
        fail(f"{path} generation changed bytes outside declared release markers")
    return result


def read_html_files(root: Path) -> dict[str, tuple[bytes, int]]:
    website_root = require_real_directory(root, "website root")
    files: dict[str, tuple[bytes, int]] = {}
    for relative_path in REQUIRED_REGIONS:
        path = require_real_child(
            website_root,
            website_root / relative_path,
            f"declared release HTML file {relative_path}",
            regular=True,
        )
        try:
            info = path.lstat()
            raw = path.read_bytes()
        except OSError as exc:
            fail(f"could not read declared release HTML file {relative_path}: {exc}")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            fail(f"{relative_path} is not UTF-8: {exc}")
        extract_regions(relative_path, text)
        files[relative_path] = (raw, stat.S_IMODE(info.st_mode))
    return files


def validate_static_template_regions(snapshot: dict[str, Any], files: dict[str, bytes]) -> list[Region]:
    # Static validation cannot recover the immutable changelog, so it validates
    # the complete rendered body grammar while source-backed drift validation
    # compares every deterministic byte against that changelog.
    rendered = render_regions(snapshot, [("Validation", ["Static validation only."])])
    all_regions: list[Region] = []
    for relative_path, raw in files.items():
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            fail(f"{relative_path} is not UTF-8: {exc}")
        regions = extract_regions(relative_path, text)
        all_regions.extend(regions.values())
        for identifier, region in regions.items():
            if identifier == "whats-new-body":
                validate_whats_new_body_template(snapshot, region.inner)
            elif region.inner != rendered[(relative_path, identifier)]:
                fail(f"{relative_path} {identifier} differs from the required static release template")
    return all_regions


def validate_html_links(root: Path, files: dict[str, bytes]) -> None:
    for relative_path, raw in files.items():
        text = raw.decode("utf-8")
        if "</html>" not in text.lower() or "<title>" not in text.lower():
            fail(f"{relative_path} is missing required HTML structure")
        hrefs = parse_static_hrefs(text, relative_path).hrefs
        for href in hrefs:
            if href.startswith(("https://", "http://", "mailto:", "#", "data:")):
                continue
            if "?" in href:
                fail(f"{relative_path} has a local link query {href}")
            normalized = href.split("#", 1)[0]
            if not normalized:
                continue
            target = require_real_child(
                root,
                (root / relative_path).parent / normalized,
                f"{relative_path} local link {href}",
            )
            if not target.exists():
                fail(f"{relative_path} has broken local link {href}")


def validate_static_release_site(root: Path) -> dict[str, Any]:
    website_root = require_real_directory(root, "website root")
    control_path = require_real_child(website_root, website_root / CONTROL_NAME, "release control", regular=True)
    state_path = require_real_child(website_root, website_root / STATE_NAME, "release state", regular=True)
    control = validate_control(read_canonical_json(control_path, "release control"))
    if control["mode"] == "hold":
        # A held site is still structurally valid.  Generators reject hold
        # before rendering; validation reports the durable state faithfully.
        pass
    state = validate_state(read_canonical_json(state_path, "release state"))
    snapshot = {
        "release": {
            "id": state["release"]["id"],
            "tag": state["release"]["tag"],
            "html_url": state["release"]["url"],
            "published_at": state["release"]["published_at"],
            "peeled_commit_sha": state["source"]["commit_sha"],
        }
    }
    file_modes = read_html_files(website_root)
    files = {path: raw for path, (raw, _mode) in file_modes.items()}
    regions = validate_static_template_regions(snapshot, files)
    validate_html_links(website_root, files)
    actual_digest = digest_regions(regions)
    if actual_digest != state["generated_content_sha256"]:
        fail("release state generated_content_sha256 does not match declared marker content")
    meta = extract_regions("index.html", files["index.html"].decode("utf-8"))["public-release-meta"].inner
    expected_meta = f'  <meta name="gajae-release" content="{state["release"]["id"]}:{state["release"]["tag"]}:{state["source"]["commit_sha"]}" />\n'
    if meta != expected_meta:
        fail("index.html public release metadata is not canonical")
    return state


def load_verified_inputs(snapshot_path: Path, source_dir: Path) -> tuple[dict[str, Any], list[tuple[str, list[str]]]]:
    snapshot_path = snapshot_path.absolute()
    snapshot_root = require_real_directory(snapshot_path.parent, "resolver workspace")
    snapshot_file = require_real_child(snapshot_root, snapshot_path, "resolver snapshot", regular=True)
    snapshot = validate_snapshot(read_canonical_json(snapshot_file, "resolver snapshot"))
    expected_source = require_real_child(snapshot_root, snapshot_root / "source", "resolver source sidecar")
    source_root = require_real_directory(source_dir, "source sidecar")
    if source_root.resolve(strict=True) != expected_source or source_dir.absolute() != snapshot_root / "source":
        fail("source-dir must be the exact real resolver snapshot sibling source sidecar")
    checkout = snapshot["source_checkout"]
    head = git(source_root, "rev-parse", "HEAD").strip()
    if head != checkout["peeled_commit_sha"]:
        fail("source sidecar HEAD differs from snapshot peeled commit SHA")
    if not source_status_is_clean(source_root):
        fail("source sidecar has tracked, untracked, or ignored modifications")
    tag = snapshot["release"]["tag"]
    peeled = git(source_root, "rev-parse", f"refs/tags/{tag}^{{}}").strip()
    if peeled != head:
        fail("source sidecar tag no longer peels to its detached HEAD")

    expected_path = require_real_child(
        snapshot_root,
        snapshot_root / EXPECTED_EVIDENCE_NAME,
        "expected evidence",
        regular=True,
    )
    final_path = require_real_child(
        snapshot_root,
        snapshot_root / FINAL_EVIDENCE_NAME,
        "final evidence",
        regular=True,
    )
    raw_expected = expected_path.read_bytes()
    raw_final = final_path.read_bytes()
    if hashlib.sha256(raw_final).hexdigest() != checkout["package_evidence_asset_sha256"]:
        fail("source sidecar final evidence asset digest differs from snapshot")
    expected, final = validate_evidence_pair(
        read_canonical_json(expected_path, "expected evidence"),
        read_canonical_json(final_path, "final evidence"),
    )
    if hashlib.sha256(raw_expected).hexdigest() != final["expected_evidence_sha256"]:
        fail("source sidecar expected evidence asset digest differs from final evidence")
    if expected != snapshot["expected_evidence"]:
        fail("snapshot expected_evidence differs from source sidecar expected evidence")
    if final != snapshot["final_evidence"]:
        fail("snapshot final_evidence differs from source sidecar final evidence")
    if final["source_commit"] != head or final["release_version"] != tag[1:]:
        fail("source sidecar final evidence does not match release tag and commit")
    validate_source_manifests(source_root, final)

    changelog_path = require_real_child(
        source_root,
        source_root / checkout["changelog_path"],
        "source changelog",
        regular=True,
    )
    try:
        changelog = changelog_path.read_bytes()
    except OSError as exc:
        fail(f"could not read source changelog: {exc}")
    if hashlib.sha256(changelog).hexdigest() != checkout["changelog_sha256"]:
        fail("source changelog bytes differ from snapshot digest")
    categories = parse_changelog(changelog, tag[1:], snapshot["release"]["published_at"], checkout["changelog_path"])
    return snapshot, categories


def validate_output_path(website_root: Path, path: Path) -> None:
    root = require_real_directory(website_root, "website root")
    candidate = path.absolute()
    try:
        candidate.relative_to(root)
    except ValueError:
        fail(f"release output is outside website root: {candidate}")
    require_real_child(root, candidate.parent, "release output parent")
    try:
        info = candidate.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        fail(f"could not inspect release output {candidate}: {exc}")
    if candidate.is_symlink() or not stat.S_ISREG(info.st_mode):
        fail(f"release output is not a regular non-symlink file: {candidate}")
    require_real_child(root, candidate, "release output", regular=True)


def fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def cleanup_temporary(website_root: Path, path: Path, failures: list[str]) -> None:
    try:
        require_real_child(website_root, path.parent, "temporary cleanup parent")
    except ReleaseSyncError as exc:
        failures.append(f"temporary cleanup {path}: {exc}")
        return
    try:
        path.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        failures.append(f"temporary inspection {path}: {exc}")
        return
    try:
        path.unlink()
    except OSError as exc:
        failures.append(f"temporary cleanup {path}: {exc}")


def write_atomically(
    changes: dict[Path, tuple[bytes, int]],
    state_path: Path,
    website_root: Path,
    *,
    fault: Callable[[str, Path], None] | None = None,
) -> None:
    if not changes:
        return
    root = require_real_directory(website_root, "website root")
    ordered = sorted(changes, key=lambda path: (path == state_path, os.fspath(path)))
    originals: dict[Path, tuple[bytes, int] | None] = {}
    staged: dict[Path, Path] = {}
    replaced: list[Path] = []
    try:
        for path in ordered:
            validate_output_path(root, path)
            if path.exists():
                info = path.lstat()
                originals[path] = (path.read_bytes(), stat.S_IMODE(info.st_mode))
            else:
                originals[path] = None
            if fault is not None:
                fault("before-stage", path)
            descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.release-sync-", dir=path.parent)
            temp_path = Path(temporary)
            staged[path] = temp_path
            with os.fdopen(descriptor, "wb") as handle:
                os.fchmod(handle.fileno(), changes[path][1])
                handle.write(changes[path][0])
                handle.flush()
                os.fsync(handle.fileno())
        for path in ordered:
            if fault is not None:
                fault("before-replace", path)
            # Re-check immediately before replacement so no path component can
            # be switched to a symlink after staging.
            validate_output_path(root, path)
            os.replace(staged[path], path)
            replaced.append(path)
            fsync_directory(path.parent)
    except Exception as exc:
        restoration_failures: list[str] = []
        cleanup_failures: list[str] = []
        for path in reversed(replaced):
            temporary: Path | None = None
            try:
                validate_output_path(root, path)
                original = originals[path]
                if original is None:
                    if fault is not None:
                        fault("before-remove-new", path)
                    path.unlink()
                    fsync_directory(path.parent)
                    continue
                original_bytes, mode = original
                descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.release-restore-", dir=path.parent)
                temporary = Path(temporary_name)
                with os.fdopen(descriptor, "wb") as handle:
                    os.fchmod(handle.fileno(), mode)
                    handle.write(original_bytes)
                    handle.flush()
                    os.fsync(handle.fileno())
                validate_output_path(root, path)
                if fault is not None:
                    fault("before-restore", path)
                os.replace(temporary, path)
                temporary = None
                fsync_directory(path.parent)
            except Exception as restore_exc:
                restoration_failures.append(f"{path}: {restore_exc}")
            finally:
                if temporary is not None:
                    cleanup_temporary(root, temporary, cleanup_failures)
        for temporary in staged.values():
            cleanup_temporary(root, temporary, cleanup_failures)
        details: list[str] = []
        if restoration_failures:
            details.append("restoration failures: " + "; ".join(restoration_failures))
        if cleanup_failures:
            details.append("temporary cleanup failures: " + "; ".join(cleanup_failures))
        suffix = "; " + "; ".join(details) if details else ""
        fail(f"atomic release generation failed: {exc}{suffix}")


def fail_on_drift(messages: list[str]) -> None:
    if messages:
        fail("release synchronization drift:\n" + "\n".join(messages))


def synchronize(snapshot_path: Path, source_dir: Path, website_root: Path, *, check: bool) -> list[str]:
    root = require_real_directory(website_root, "website root")
    snapshot, categories = load_verified_inputs(snapshot_path, source_dir)
    control_path = require_real_child(root, root / CONTROL_NAME, "release control", regular=True)
    control = validate_control(read_canonical_json(control_path, "release control"))
    if control["mode"] != "active":
        fail("release synchronization is blocked by release-sync-control.json hold")
    if snapshot["release"]["id"] in control["blocked_release_ids"]:
        fail("release synchronization is blocked for this release id")
    state_path = root / STATE_NAME
    try:
        state_path.lstat()
        state_exists = True
    except FileNotFoundError:
        state_exists = False
    except OSError as exc:
        fail(f"could not inspect existing release state: {exc}")
    if state_exists:
        state_path = require_real_child(root, state_path, "existing release state", regular=True)
        validate_state(read_canonical_json(state_path, "existing release state"))

    original_files = read_html_files(root)
    rendered = render_regions(snapshot, categories)
    candidate_files: dict[str, tuple[bytes, int]] = {}
    candidate_regions: list[Region] = []
    changed_regions: dict[str, list[str]] = {}
    for relative_path, (raw, mode) in original_files.items():
        text = raw.decode("utf-8")
        candidate = substitute_regions(relative_path, text, rendered)
        candidate_regions.extend(extract_regions(relative_path, candidate).values())
        candidate_raw = candidate.encode("utf-8")
        candidate_files[relative_path] = (candidate_raw, mode)
        regions = extract_regions(relative_path, text)
        changed = [identifier for identifier, region in regions.items() if region.inner != rendered[(relative_path, identifier)]]
        if changed:
            changed_regions[relative_path] = sorted(changed)
    digest = digest_regions(candidate_regions)
    state = build_state(snapshot, digest)
    validate_state(state)
    state_raw = canonical_json(state)

    # Validate the complete generated content before writing a single file.
    for relative_path, (raw, _mode) in candidate_files.items():
        text = raw.decode("utf-8")
        for identifier, region in extract_regions(relative_path, text).items():
            if region.inner != rendered[(relative_path, identifier)]:
                fail(f"generated {relative_path} {identifier} did not match its exact template")
    validate_html_links(root, {path: raw for path, (raw, _mode) in candidate_files.items()})

    changes: dict[Path, tuple[bytes, int]] = {}
    for relative_path, candidate in candidate_files.items():
        if candidate[0] != original_files[relative_path][0]:
            changes[root / relative_path] = candidate
    if state_exists:
        state_mode = stat.S_IMODE(state_path.lstat().st_mode)
        state_before = state_path.read_bytes()
    else:
        state_mode = 0o644
        state_before = b""
    if state_before != state_raw:
        changes[state_path] = (state_raw, state_mode)
    messages = [
        f"{path}: {', '.join(changed_regions[path])}" for path in sorted(changed_regions)
    ]
    if state_before != state_raw:
        messages.append(STATE_NAME)
    if check:
        fail_on_drift(messages)
        return []
    write_atomically(changes, state_path, root)
    return messages


def self_test() -> None:
    control = {
        "blocked_release_ids": [1, 2],
        "mode": "active",
        "reason": "",
        "schema_version": 1,
    }
    validate_control(control)
    digest = digest_regions([Region("docs/index.html", "docs-nav-release-label", 0, 0, "What's new (v1.2.3)")])
    if SHA256_RE.fullmatch(digest) is None:
        fail("self-test could not create a region digest")
    rendered, links = render_inline("Fixed #12 with `gjc`", "CHANGELOG.md", 1)
    if links != 1 or "<code>gjc</code>" not in rendered:
        fail("self-test inline rendering failed")
    try:
        fail_on_drift(["self-test drift"])
    except ReleaseSyncError:
        pass
    else:
        fail("self-test drift branch did not fail closed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate marker-scoped website release content from a resolver sidecar.")
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--source-dir", type=Path)
    parser.add_argument("--website-root", type=Path)
    parser.add_argument("--check", action="store_true", help="fail when generated bytes differ without writing")
    parser.add_argument("--self-test", action="store_true", help="run isolated parser and schema smoke checks")
    args = parser.parse_args()
    if args.self_test:
        if any(value is not None for value in (args.snapshot, args.source_dir, args.website_root)) or args.check:
            parser.error("--self-test cannot be combined with release inputs")
    elif any(value is None for value in (args.snapshot, args.source_dir, args.website_root)):
        parser.error("--snapshot, --source-dir, and --website-root are required")
    return args


def main() -> None:
    args = parse_args()
    try:
        if args.self_test:
            self_test()
            print("sync-release self-test passed")
            return
        changed = synchronize(args.snapshot, args.source_dir, args.website_root, check=args.check)
    except ReleaseSyncError as exc:
        raise SystemExit(f"release sync failed: {exc}") from None
    if args.check:
        print("release synchronization is current")
    elif changed:
        print("release synchronization updated:")
        for item in changed:
            print(f"- {item}")
    else:
        print("release synchronization already current")


if __name__ == "__main__":
    main()
