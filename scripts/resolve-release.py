#!/usr/bin/env python3
"""Resolve the latest complete production release into a detached local sidecar.

The resolver is deliberately the sole networked website release component.  It
uses immutable release/tag/package evidence and emits a closed canonical
snapshot for sync-release.py; it never accepts a repository, registry, or
credential override.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

SCRIPT_DIR = Path(__file__).resolve().parent
SYNC_PATH = SCRIPT_DIR / "sync-release.py"
spec = importlib.util.spec_from_file_location("release_sync_contract", SYNC_PATH)
if spec is None or spec.loader is None:
    raise SystemExit(f"could not load release synchronization contract from {SYNC_PATH}")
sync = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = sync
spec.loader.exec_module(sync)

SOURCE_REPOSITORY = sync.SOURCE_REPOSITORY
API_ROOT = f"https://api.github.com/repos/{SOURCE_REPOSITORY}"
SOURCE_GIT_URL = f"https://github.com/{SOURCE_REPOSITORY}.git"
REGISTRY_ROOT = "https://registry.npmjs.org"
REQUIRED_BINARY_ASSETS = sync.REQUIRED_BINARY_ASSET_NAMES
EXPECTED_ASSETS = (sync.EXPECTED_EVIDENCE_NAME, sync.FINAL_EVIDENCE_NAME)


class ResolverError(RuntimeError):
    pass


def fail(message: str) -> None:
    raise ResolverError(message)


def strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            fail(f"duplicate JSON key: {key}")
        result[key] = value
    return result


class RestrictedRedirectHandler(HTTPRedirectHandler):
    """Permit only known production origins while following download redirects."""

    def __init__(self, allowed_hosts: set[str]) -> None:
        super().__init__()
        self.allowed_hosts = allowed_hosts

    def redirect_request(self, request: Request, fp: Any, code: int, message: str, headers: Any, new_url: str) -> Request | None:
        parsed = urlparse(new_url)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in self.allowed_hosts
            or parsed.port not in (None, 443)
            or parsed.username
            or parsed.password
            or parsed.fragment
        ):
            fail("HTTP redirect left the allowlisted production origin")
        return super().redirect_request(request, fp, code, message, headers, new_url)


def allowed_request_hosts(url: str) -> set[str]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.port not in (None, 443) or parsed.username or parsed.password or parsed.query or parsed.fragment:
        fail("release retrieval URL is not a canonical HTTPS production input")
    if parsed.hostname == "api.github.com":
        return {"api.github.com"}
    if parsed.hostname == "github.com":
        return {"github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"}
    if parsed.hostname == "registry.npmjs.org":
        return {"registry.npmjs.org"}
    fail("release retrieval URL is outside the production allowlist")


def request_bytes(url: str, label: str) -> bytes:
    # An empty proxy map and a restrictive redirect handler keep credentials,
    # headers, proxy overrides, and cross-origin redirects out of this path.
    allowed_hosts = allowed_request_hosts(url)
    opener = build_opener(ProxyHandler({}), RestrictedRedirectHandler(allowed_hosts))
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json, application/json",
            "User-Agent": "gajae-code-website-release-resolver",
        },
        method="GET",
    )
    try:
        with opener.open(request, timeout=30) as response:
            final = urlparse(response.geturl())
            if final.scheme != "https" or final.hostname not in allowed_hosts or final.port not in (None, 443) or final.username or final.password or final.fragment:
                fail(f"{label} redirected outside the production allowlist")
            if response.status != 200:
                fail(f"{label} returned HTTP {response.status}")
            return response.read()
    except ResolverError:
        raise
    except Exception as exc:
        fail(f"could not retrieve {label}: {exc}")


def request_json(url: str, label: str) -> dict[str, Any]:
    raw = request_bytes(url, label)
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=strict_object)
    except (UnicodeDecodeError, json.JSONDecodeError, ResolverError) as exc:
        fail(f"{label} did not return a valid JSON object: {exc}")
    if not isinstance(value, dict):
        fail(f"{label} did not return a JSON object")
    sync.reject_noncanonical_numbers(value, label)
    return value


def require(value: Any, label: str, expected_type: type) -> Any:
    if not isinstance(value, expected_type) or (expected_type is int and isinstance(value, bool)):
        fail(f"{label} has the wrong type")
    return value


def normalize_timestamp(value: Any) -> str:
    timestamp = require(value, "GitHub release published_at", str)
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        fail("GitHub release published_at is invalid")
    if parsed.tzinfo is None:
        fail("GitHub release published_at is not timezone-aware")
    parsed = parsed.astimezone(timezone.utc).replace(microsecond=0)
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_assets(value: Any, tag: str) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    if not isinstance(value, list):
        fail("GitHub release assets must be an array")
    assets: list[dict[str, Any]] = []
    by_name: dict[str, dict[str, Any]] = {}
    prefix = f"https://github.com/{SOURCE_REPOSITORY}/releases/download/{tag}/"
    for index, raw_asset in enumerate(value):
        if not isinstance(raw_asset, dict):
            fail(f"GitHub release asset {index} is not an object")
        asset_id = require(raw_asset.get("id"), f"GitHub release asset {index}.id", int)
        name = require(raw_asset.get("name"), f"GitHub release asset {index}.name", str)
        size = require(raw_asset.get("size"), f"GitHub release asset {index}.size", int)
        url = require(raw_asset.get("browser_download_url"), f"GitHub release asset {index}.browser_download_url", str)
        api_url = require(raw_asset.get("url"), f"GitHub release asset {index}.url", str)
        digest = require(raw_asset.get("digest"), f"GitHub release asset {index}.digest", str)
        expected_url = f"{prefix}{quote(name, safe='')}"
        expected_api_url = f"{API_ROOT}/releases/assets/{asset_id}"
        if (
            asset_id <= 0
            or size <= 0
            or url != expected_url
            or api_url != expected_api_url
            or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None
        ):
            fail(f"GitHub release asset {name!r} lacks canonical immutable identity or SHA-256 digest")
        if name in by_name:
            fail(f"GitHub release has duplicate asset {name!r}")
        asset = {
            "api_url": api_url,
            "browser_download_url": url,
            "digest": digest,
            "id": asset_id,
            "name": name,
            "size": size,
        }
        assets.append(asset)
        by_name[name] = asset
    assets.sort(key=lambda asset: asset["name"])
    for name in (*REQUIRED_BINARY_ASSETS, *EXPECTED_ASSETS):
        if name not in by_name:
            fail(f"GitHub release is missing required asset {name}")
    return assets, by_name


def latest_release() -> dict[str, Any]:
    raw = request_json(f"{API_ROOT}/releases/latest", "latest production release")
    release_id = require(raw.get("id"), "GitHub release id", int)
    if release_id <= 0:
        fail("GitHub release id must be positive")
    tag = require(raw.get("tag_name"), "GitHub release tag_name", str)
    if sync.TAG_RE.fullmatch(tag) is None:
        fail("latest GitHub release tag is not an exact stable production tag")
    if raw.get("draft") is not False or raw.get("prerelease") is not False:
        fail("latest GitHub release is not finalized stable")
    version = tag[1:]
    html_url = require(raw.get("html_url"), "GitHub release html_url", str)
    if html_url != sync.release_url(version):
        fail("latest GitHub release URL is not canonical")
    target_commitish = require(raw.get("target_commitish"), "GitHub release target_commitish", str)
    assets, by_name = normalize_assets(raw.get("assets"), tag)
    return {
        "assets": assets,
        "asset_map": by_name,
        "draft": False,
        "html_url": html_url,
        "id": release_id,
        # The title is not a provenance input; normalize it to the immutable
        # tag so the closed snapshot has one representation of the release.
        "name": tag,
        "prerelease": False,
        "published_at": normalize_timestamp(raw.get("published_at")),
        "tag": tag,
        "target_commitish": target_commitish,
    }


def resolve_tag(tag: str) -> str:
    ref = request_json(f"{API_ROOT}/git/ref/tags/{quote(tag, safe='')}", "production tag ref")
    object_value = ref.get("object")
    if not isinstance(object_value, dict):
        fail("production tag ref has no object")
    object_type = object_value.get("type")
    object_sha = object_value.get("sha")
    if object_type not in ("tag", "commit") or not isinstance(object_sha, str) or sync.SHA_RE.fullmatch(object_sha) is None:
        fail("production tag ref has an invalid object")
    seen: set[str] = set()
    tag_depth = 0
    while object_type == "tag":
        if object_sha in seen or tag_depth >= 4:
            fail("production annotated tag chain is cyclic or exceeds four levels")
        seen.add(object_sha)
        tag_depth += 1
        tag_object = request_json(f"{API_ROOT}/git/tags/{object_sha}", "production annotated tag object")
        nested = tag_object.get("object")
        if not isinstance(nested, dict):
            fail("production annotated tag object has no target")
        object_type = nested.get("type")
        object_sha = nested.get("sha")
        if object_type not in ("tag", "commit") or not isinstance(object_sha, str) or sync.SHA_RE.fullmatch(object_sha) is None:
            fail("production annotated tag target is invalid")
    if object_type != "commit":
        fail("production tag did not peel to a commit")
    return object_sha


def run_git(workspace: Path, *arguments: str) -> str:
    root = sync.require_real_directory(workspace, "resolver workspace")
    result = subprocess.run(
        ["git", *arguments],
        cwd=root,
        env=sync.git_environment(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        fail(f"git {' '.join(arguments)} failed: {result.stderr.strip()}")
    return result.stdout


def create_detached_sidecar(workspace: Path, source_dir: Path, tag: str, peeled_sha: str) -> None:
    if source_dir != workspace / "source":
        fail("source-dir must be the exact workspace/source sidecar path")
    try:
        source_dir.lstat()
    except FileNotFoundError:
        pass
    except OSError as exc:
        fail(f"could not inspect detached source destination: {exc}")
    else:
        fail("detached source destination already exists")
    sync.require_real_child(workspace, workspace, "resolver workspace")
    run_git(
        workspace,
        "-c",
        "credential.helper=",
        "clone",
        "--no-checkout",
        "--filter=blob:none",
        SOURCE_GIT_URL,
        os.fspath(source_dir),
    )
    source_root = sync.require_real_directory(source_dir, "detached source checkout")
    sync.require_real_child(workspace, source_root, "detached source checkout")
    source_git = sync.require_real_child(source_root, source_root / ".git", "detached source Git directory")
    if not source_git.is_dir():
        fail("detached source Git directory must be a real directory")
    run_git(
        workspace,
        "-C",
        os.fspath(source_root),
        "-c",
        "credential.helper=",
        "fetch",
        "--no-tags",
        "origin",
        f"refs/tags/{tag}:refs/tags/{tag}",
    )
    run_git(workspace, "-C", os.fspath(source_root), "checkout", "--detach", peeled_sha)
    head = run_git(workspace, "-C", os.fspath(source_root), "rev-parse", "HEAD").strip()
    if head != peeled_sha:
        fail("detached source checkout HEAD differs from peeled production tag")
    local_peeled = run_git(workspace, "-C", os.fspath(source_root), "rev-parse", f"refs/tags/{tag}^{{}}").strip()
    if local_peeled != peeled_sha:
        fail("detached source checkout tag does not peel to the resolved production commit")
    if not sync.source_status_is_clean(source_root):
        fail("detached source checkout has tracked, untracked, or ignored modifications")


def downloaded_asset(asset: dict[str, Any], label: str) -> bytes:
    data = request_bytes(asset["browser_download_url"], label)
    if len(data) != asset["size"]:
        fail(f"{label} size does not match GitHub release asset metadata")
    if hashlib.sha256(data).hexdigest() != asset["digest"].removeprefix("sha256:"):
        fail(f"{label} SHA-256 differs from immutable GitHub release asset digest")
    return data


def write_verified_evidence(workspace: Path, name: str, raw: bytes) -> None:
    destination = workspace / name
    try:
        destination.lstat()
    except FileNotFoundError:
        pass
    except OSError as exc:
        fail(f"could not inspect verified evidence destination: {exc}")
    else:
        fail("verified evidence destination already exists")
    descriptor, temporary_name = tempfile.mkstemp(prefix=".verified-evidence-", dir=workspace)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        sync.require_real_child(workspace, temporary, "verified evidence temporary copy", regular=True)
        sync.require_real_child(workspace, workspace, "resolver workspace")
        os.replace(temporary, destination)
    except OSError as exc:
        cleanup_error = ""
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        except OSError as cleanup_exc:
            cleanup_error = f"; verified evidence cleanup failed: {cleanup_exc}"
        fail(f"could not atomically write verified evidence: {exc}{cleanup_error}")


def evidence_from_release(release: dict[str, Any], peeled_sha: str, workspace: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    assets = release["asset_map"]
    expected_raw = downloaded_asset(assets[sync.EXPECTED_EVIDENCE_NAME], "expected package evidence")
    final_raw = downloaded_asset(assets[sync.FINAL_EVIDENCE_NAME], "final package evidence")
    try:
        expected = json.loads(expected_raw.decode("utf-8"), object_pairs_hook=strict_object)
        final = json.loads(final_raw.decode("utf-8"), object_pairs_hook=strict_object)
    except (UnicodeDecodeError, json.JSONDecodeError, ResolverError) as exc:
        fail(f"release package evidence is invalid JSON: {exc}")
    if expected_raw != sync.canonical_json(expected) or final_raw != sync.canonical_json(final):
        fail("release package evidence must be canonical sorted UTF-8 JSON")
    expected, final = sync.validate_evidence_pair(expected, final)
    version = release["tag"][1:]
    if expected["source_commit"] != peeled_sha or final["source_commit"] != peeled_sha:
        fail("package evidence source commit differs from peeled production tag")
    if expected["release_version"] != version or final["release_version"] != version:
        fail("package evidence release version differs from production release tag")
    write_verified_evidence(workspace, sync.EXPECTED_EVIDENCE_NAME, expected_raw)
    write_verified_evidence(workspace, sync.FINAL_EVIDENCE_NAME, final_raw)
    return expected, final


def read_tar_manifest(tarball: bytes, label: str) -> bytes:
    try:
        with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as archive:
            members = archive.getmembers()
            matching = [member for member in members if member.name == "package/package.json"]
            if len(matching) != 1 or not matching[0].isfile() or matching[0].issym() or matching[0].islnk():
                fail(f"{label} does not contain one safe package/package.json member")
            handle = archive.extractfile(matching[0])
            if handle is None:
                fail(f"{label} could not read package/package.json")
            return handle.read()
    except ResolverError:
        raise
    except (tarfile.TarError, OSError) as exc:
        fail(f"{label} is not a safe gzip tarball: {exc}")


def manifest_internal_dependencies(manifest: dict[str, Any], label: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for field in sync.PACKAGE_DEPENDENCY_FIELDS:
        dependencies = manifest.get(field, {})
        if not isinstance(dependencies, dict):
            fail(f"{label}.{field} must be an object when present")
        for name, value in dependencies.items():
            if not isinstance(name, str):
                fail(f"{label}.{field} has a non-string dependency name")
            if sync.is_reserved_package_name(name) and name not in sync.EXPECTED_PACKAGES:
                fail(f"{label}.{field} contains unknown reserved package {name!r}")
            if name in sync.EXPECTED_PACKAGES:
                if not isinstance(value, str):
                    fail(f"{label}.{field}.{name} must be a string")
                previous = result.get(name)
                if previous is not None and previous != value:
                    fail(f"{label} has conflicting dependency declarations for {name}")
                result[name] = value
    return dict(sorted(result.items()))


def verify_registry_record(record: dict[str, Any]) -> None:
    name = record["name"]
    version = record["version"]
    registry_url = f"{REGISTRY_ROOT}/{quote(name, safe='')}/{quote(version, safe='')}"
    metadata = request_json(registry_url, f"npm registry metadata for {name}@{version}")
    if metadata.get("name") != name or metadata.get("version") != version:
        fail(f"npm registry metadata identity differs for {name}@{version}")
    dist = metadata.get("dist")
    if not isinstance(dist, dict) or dist.get("integrity") != record["registry_sri"]:
        fail(f"npm registry integrity differs from final evidence for {name}")
    tarball_url = dist.get("tarball")
    if not isinstance(tarball_url, str):
        fail(f"npm registry tarball URL is missing for {name}")
    parsed = urlparse(tarball_url)
    if parsed.scheme != "https" or parsed.netloc != "registry.npmjs.org" or parsed.username or parsed.password or parsed.query or parsed.fragment:
        fail(f"npm registry tarball URL is not canonical production registry input for {name}")
    tarball = request_bytes(tarball_url, f"npm registry tarball for {name}@{version}")
    if hashlib.sha512(tarball).hexdigest() != record["registry_tarball_sha512"]:
        fail(f"npm registry tarball SHA-512 differs from final evidence for {name}")
    manifest_bytes = read_tar_manifest(tarball, f"npm registry tarball for {name}")
    if hashlib.sha256(manifest_bytes).hexdigest() != record["registry_manifest_sha256"]:
        fail(f"npm registry package manifest SHA-256 differs from final evidence for {name}")
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"), object_pairs_hook=strict_object)
    except (UnicodeDecodeError, json.JSONDecodeError, ResolverError) as exc:
        fail(f"npm registry package manifest is invalid for {name}: {exc}")
    if not isinstance(manifest, dict) or manifest.get("name") != name or manifest.get("version") != version:
        fail(f"npm registry package manifest identity differs for {name}")
    if manifest_internal_dependencies(manifest, f"npm registry package manifest {name}") != record["registry_internal_dependencies"]:
        fail(f"npm registry internal dependencies differ from final evidence for {name}")


def verify_release_assets(release: dict[str, Any]) -> None:
    for name in REQUIRED_BINARY_ASSETS:
        data = downloaded_asset(release["asset_map"][name], f"required binary asset {name}")
        if not data:
            fail(f"required binary asset {name} is empty")


def verify_source_sidecar(source_dir: Path, release: dict[str, Any], peeled_sha: str, evidence: dict[str, Any]) -> bytes:
    source_root = sync.require_real_directory(source_dir, "detached source checkout")
    changelog_path = sync.require_real_child(
        source_root,
        source_root / sync.CHANGELOG_PATH,
        "detached source changelog",
        regular=True,
    )
    try:
        changelog = changelog_path.read_bytes()
    except OSError as exc:
        fail(f"could not read detached source changelog: {exc}")
    sync.validate_source_manifests(source_root, evidence)
    sync.parse_changelog(changelog, release["tag"][1:], release["published_at"], sync.CHANGELOG_PATH)
    return changelog


def prepare_workspace(workspace: Path, snapshot_path: Path, source_dir: Path) -> tuple[Path, Path, Path]:
    candidate = workspace.absolute()
    if candidate.exists():
        if candidate.is_symlink() or not candidate.is_dir():
            fail("workspace must be a real directory")
        if any(candidate.iterdir()):
            fail("workspace must be initially empty")
    else:
        candidate.mkdir(mode=0o700, parents=True)
    workspace_root = sync.require_real_directory(candidate, "resolver workspace")
    os.chmod(workspace_root, 0o700)
    if stat.S_IMODE(workspace_root.stat().st_mode) != 0o700:
        fail("workspace mode must be 0700")
    expected_source = workspace_root / "source"
    expected_snapshot = workspace_root / "snapshot.json"
    if source_dir.absolute() != expected_source or snapshot_path.absolute() != expected_snapshot:
        fail("source-dir and snapshot must be the exact workspace/source and workspace/snapshot.json paths")
    for path, label in ((source_dir, "source-dir"), (snapshot_path, "snapshot")):
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            fail(f"could not inspect {label}: {exc}")
        if path.is_symlink() or not stat.S_ISREG(info.st_mode):
            fail(f"{label} must not be a symlink or non-regular pre-existing sidecar path")
    return workspace_root, expected_snapshot, expected_source


def resolve(mode: str, workspace: Path, snapshot_path: Path, source_dir: Path) -> dict[str, Any]:
    workspace, snapshot_path, source_dir = prepare_workspace(workspace, snapshot_path, source_dir)
    release = latest_release()
    peeled_sha = resolve_tag(release["tag"])
    release["peeled_commit_sha"] = peeled_sha
    create_detached_sidecar(workspace, source_dir, release["tag"], peeled_sha)
    verify_release_assets(release)
    expected_evidence, final_evidence = evidence_from_release(release, peeled_sha, workspace)
    for record in final_evidence["packages"]:
        verify_registry_record(record)
    changelog = verify_source_sidecar(source_dir, release, peeled_sha, final_evidence)
    snapshot = {
        "expected_evidence": expected_evidence,
        "final_evidence": final_evidence,
        "release": {
            "assets": release["assets"],
            "draft": release["draft"],
            "html_url": release["html_url"],
            "id": release["id"],
            "name": release["name"],
            "peeled_commit_sha": peeled_sha,
            "prerelease": release["prerelease"],
            "published_at": release["published_at"],
            "tag": release["tag"],
            "target_commitish": release["target_commitish"],
        },
        "requested": {"hint_tag": "", "mode": mode, "source_run_url": ""},
        "schema_version": 1,
        "source_checkout": {
            "changelog_path": sync.CHANGELOG_PATH,
            "changelog_sha256": hashlib.sha256(changelog).hexdigest(),
            "package_evidence_asset_sha256": hashlib.sha256(
                sync.require_real_child(
                    workspace,
                    workspace / sync.FINAL_EVIDENCE_NAME,
                    "verified final evidence copy",
                    regular=True,
                ).read_bytes()
            ).hexdigest(),
            "path": "source",
            "peeled_commit_sha": peeled_sha,
        },
    }
    sync.validate_snapshot(snapshot)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".snapshot-", dir=workspace)
    temp_snapshot = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(sync.canonical_json(snapshot))
            handle.flush()
            os.fsync(handle.fileno())
        sync.require_real_child(workspace, temp_snapshot, "resolver snapshot temporary", regular=True)
        try:
            snapshot_path.lstat()
        except FileNotFoundError:
            pass
        except OSError as exc:
            fail(f"could not inspect resolver snapshot destination: {exc}")
        else:
            fail("resolver snapshot destination appeared before replacement")
        sync.require_real_child(workspace, workspace, "resolver workspace")
        os.replace(temp_snapshot, snapshot_path)
    except Exception as exc:
        cleanup_error = ""
        try:
            temp_snapshot.unlink()
        except FileNotFoundError:
            pass
        except OSError as cleanup_exc:
            cleanup_error = f"; resolver snapshot cleanup failed: {cleanup_exc}"
        fail(f"could not atomically write resolver snapshot: {exc}{cleanup_error}")
    return snapshot


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Resolve the latest complete stable Gajae Code release into a detached sidecar.")
    parser.add_argument("--mode", required=True, choices=("latest", "verify-only"))
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--source-dir", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        snapshot = resolve(args.mode, args.workspace, args.snapshot, args.source_dir)
    except (ResolverError, sync.ReleaseSyncError) as exc:
        raise SystemExit(f"release resolution failed: {exc}") from None
    print(
        "resolved complete production release "
        f"{snapshot['release']['tag']} ({snapshot['release']['id']}) at {snapshot['release']['peeled_commit_sha']}"
    )


if __name__ == "__main__":
    main()
