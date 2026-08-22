#!/usr/bin/env python3
"""Validate generated release-sync changes from trusted code only.

This program intentionally reads candidate revisions only through Git object commands.  It
never imports, executes, or trusts files from the candidate revision.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

CANONICAL_REPOSITORY = "Yeachan-Heo/gajae-code-website"
SOURCE_REPOSITORY = "Yeachan-Heo/gajae-code"
CHANGELOG_PATH = "packages/coding-agent/CHANGELOG.md"
STATE_PATH = "release-sync.json"
CONTROL_PATH = "release-sync-control.json"
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
SHA1_RE = re.compile(r"[0-9a-f]{40}\Z")
SEMVER_RE = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")
TIMESTAMP_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z")
MARKER_RE = re.compile(r"<!-- release-sync:([a-z0-9]+(?:-[a-z0-9]+)*):(start|end) -->")
MARKER_COMMENT_RE = re.compile(r"<!--\s*release-sync:.*?-->")

NAV_PATHS = (
    "docs/architecture.html",
    "docs/bridge-rpc.html",
    "docs/browser-use.html",
    "docs/computer-use.html",
    "docs/gajae-remote.html",
    "docs/getting-started.html",
    "docs/harness.html",
    "docs/hermes-mcp-bridge.html",
    "docs/receipts.html",
    "docs/rlm.html",
    "docs/skills.html",
    "docs/telegram-onboarding.html",
    "docs/troubleshooting.html",
)
OWNED_REGIONS: dict[str, tuple[str, ...]] = {
    "index.html": (
        "public-release-meta",
        "homepage-hero-badge",
        "homepage-release-strip",
    ),
    "docs/index.html": ("docs-nav-release-label", "docs-latest-release-card"),
    "docs/whats-new.html": (
        "docs-nav-release-label",
        "whats-new-meta-description",
        "whats-new-title",
        "whats-new-hero",
        "whats-new-body",
    ),
    **{path: ("docs-nav-release-label",) for path in NAV_PATHS},
}
GENERATED_PATHS = frozenset((*OWNED_REGIONS, STATE_PATH))


class ProtocolError(ValueError):
    """A closed release-sync contract was not met."""


class CandidateError(ProtocolError):
    """The candidate cannot receive automated review but may receive human review."""




def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _no_float(value: str) -> None:
    raise ProtocolError("JSON floats are forbidden")


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_json_bytes(raw: bytes, description: str) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_pairs, parse_float=_no_float, parse_constant=_no_float
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ProtocolError) as exc:
        raise ProtocolError(f"invalid {description} JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ProtocolError(f"{description} must be a JSON object")
    if value != _reject_null(value):
        raise ProtocolError(f"{description} contains null")
    if raw != canonical_json(value):
        raise ProtocolError(f"{description} is not canonical JSON")
    return value


def _reject_null(value: Any) -> Any:
    if value is None:
        return object()
    if isinstance(value, dict):
        return {key: _reject_null(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_reject_null(item) for item in value]
    return value


def _require_keys(value: dict[str, Any], expected: set[str], description: str) -> None:
    if set(value) != expected:
        missing = sorted(expected - set(value))
        extra = sorted(set(value) - expected)
        raise ProtocolError(f"{description} keys must be exact; missing={missing}, extra={extra}")


def _require_string(value: Any, description: str, pattern: re.Pattern[str] | None = None) -> str:
    if not isinstance(value, str):
        raise ProtocolError(f"{description} must be a string")
    if pattern is not None and pattern.fullmatch(value) is None:
        raise ProtocolError(f"invalid {description}")
    return value


def _require_positive_int(value: Any, description: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ProtocolError(f"{description} must be a positive integer")
    return value


def _require_schema_version(value: Any, description: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value != 1:
        raise ProtocolError(f"{description}.schema_version must be the integer 1")
    return value




def validate_release_state(raw: bytes) -> dict[str, Any]:
    state = parse_json_bytes(raw, STATE_PATH)
    _require_keys(state, {"generated_content_sha256", "release", "schema_version", "source"}, STATE_PATH)
    _require_schema_version(state["schema_version"], STATE_PATH)
    _require_string(state["generated_content_sha256"], "generated_content_sha256", SHA256_RE)

    release = state["release"]
    if not isinstance(release, dict):
        raise ProtocolError("release must be an object")
    _require_keys(release, {"id", "published_at", "tag", "url", "version"}, "release")
    _require_positive_int(release["id"], "release.id")
    version = _require_string(release["version"], "release.version", SEMVER_RE)
    if release["tag"] != f"v{version}":
        raise ProtocolError("release.tag must be the exact v-prefixed release.version")
    _require_string(release["published_at"], "release.published_at", TIMESTAMP_RE)
    try:
        datetime.strptime(release["published_at"], "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ProtocolError("release.published_at is not a valid UTC timestamp") from exc
    expected_url = f"https://github.com/{SOURCE_REPOSITORY}/releases/tag/v{version}"
    if release["url"] != expected_url:
        raise ProtocolError("release.url is not the canonical GitHub release URL")

    source = state["source"]
    if not isinstance(source, dict):
        raise ProtocolError("source must be an object")
    _require_keys(source, {"changelog_path", "commit_sha", "repository"}, "source")
    if source["repository"] != SOURCE_REPOSITORY:
        raise ProtocolError("source.repository is not the production repository")
    if source["changelog_path"] != CHANGELOG_PATH:
        raise ProtocolError("source.changelog_path is not the production changelog")
    _require_string(source["commit_sha"], "source.commit_sha", SHA1_RE)
    return state


def validate_control(raw: bytes) -> dict[str, Any]:
    control = parse_json_bytes(raw, CONTROL_PATH)
    _require_keys(control, {"blocked_release_ids", "mode", "reason", "schema_version"}, CONTROL_PATH)
    _require_schema_version(control["schema_version"], CONTROL_PATH)
    if control["mode"] not in {"active", "hold"}:
        raise ProtocolError("release-sync-control mode must be active or hold")
    if not isinstance(control["reason"], str):
        raise ProtocolError("release-sync-control reason must be a string")
    if control["mode"] == "hold" and not control["reason"].strip():
        raise ProtocolError("held release-sync-control requires a reason")
    blocked = control["blocked_release_ids"]
    if not isinstance(blocked, list):
        raise ProtocolError("blocked_release_ids must be an array")
    if any(isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in blocked):
        raise ProtocolError("blocked_release_ids must contain positive integers")
    if blocked != sorted(set(blocked)):
        raise ProtocolError("blocked_release_ids must be sorted and unique")
    return control



def _strictly_equal(left: Any, right: Any) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return set(left) == set(right) and all(_strictly_equal(value, right[key]) for key, value in left.items())
    if isinstance(left, list):
        return len(left) == len(right) and all(_strictly_equal(first, second) for first, second in zip(left, right))
    return left == right


def compare_release_states(base: dict[str, Any], candidate: dict[str, Any]) -> None:
    base_version = tuple(int(part) for part in base["release"]["version"].split("."))
    candidate_version = tuple(int(part) for part in candidate["release"]["version"].split("."))
    if candidate_version < base_version:
        raise CandidateError("candidate release would downgrade committed release state")
    if candidate_version == base_version:
        base_identity = (
            base["release"]["id"],
            base["release"]["tag"],
            base["source"]["commit_sha"],
        )
        candidate_identity = (
            candidate["release"]["id"],
            candidate["release"]["tag"],
            candidate["source"]["commit_sha"],
        )
        if not _strictly_equal(candidate_identity, base_identity):
            raise CandidateError("equal release version has a different immutable release identity")
        if not _strictly_equal(candidate, base):
            raise CandidateError("the same immutable release must be a no-op")


def _read_markers(text: str, path: str, version: str) -> dict[str, tuple[int, int, int, int, str]]:
    comments = MARKER_COMMENT_RE.findall(text)
    markers = list(MARKER_RE.finditer(text))
    if len(comments) != len(markers):
        raise ProtocolError(f"{path} has malformed release-sync marker comments")
    stack: list[tuple[str, re.Match[str]]] = []
    regions: dict[str, tuple[int, int, int, int, str]] = {}
    for marker in markers:
        region_id, kind = marker.groups()
        if kind == "start":
            if stack:
                raise ProtocolError(f"{path} has nested release-sync markers")
            stack.append((region_id, marker))
            continue
        if not stack:
            raise ProtocolError(f"{path} has a release-sync end marker without a start marker")
        start_id, start_marker = stack.pop()
        if start_id != region_id:
            raise ProtocolError(f"{path} has mismatched release-sync marker ids")
        if region_id in regions:
            raise ProtocolError(f"{path} has duplicate release-sync marker id {region_id}")
        if region_id == "docs-nav-release-label":
            inner_start, inner_end = start_marker.end(), marker.start()
            inner = text[inner_start:inner_end]
            if "\n" in inner or "\r" in inner or inner != inner.strip():
                raise ProtocolError(f"{path} docs nav marker must have inline whitespace-free content")
            anchor_start = text.rfind("<a", 0, start_marker.start())
            anchor_open_end = text.find(">", anchor_start, start_marker.start())
            anchor_close = text.find("</a>", marker.end())
            if (
                anchor_start < 0
                or anchor_open_end < 0
                or anchor_close < 0
                or text[anchor_open_end + 1 : start_marker.start()]
                or text[marker.end() : anchor_close]
                or 'href="whats-new.html"' not in text[anchor_start:anchor_open_end]
            ):
                raise ProtocolError(f"{path} docs nav marker must be the complete whats-new anchor content")
        else:
            start_line = text.rfind("\n", 0, start_marker.start()) + 1
            start_line_end = text.find("\n", start_marker.end())
            end_line = text.rfind("\n", 0, marker.start()) + 1
            end_line_end = text.find("\n", marker.end())
            if start_line_end < 0 or end_line_end < 0:
                raise ProtocolError(f"{path} non-inline release markers must end with LF")
            start_prefix = text[start_line:start_marker.start()]
            end_prefix = text[end_line:marker.start()]
            if (
                text[start_marker.end() : start_line_end]
                or text[marker.end() : end_line_end]
                or start_prefix.strip()
                or end_prefix.strip()
                or start_prefix != end_prefix
            ):
                raise ProtocolError(f"{path} non-inline release markers must occupy matching own lines")
            inner_start, inner_end = start_line_end + 1, end_line
            inner = text[inner_start:inner_end]
            if not inner.endswith("\n"):
                raise ProtocolError(f"{path} non-inline release marker content must end with LF")
        regions[region_id] = (start_marker.start(), marker.end(), inner_start, inner_end, inner)
    if stack:
        raise ProtocolError(f"{path} has an unclosed release-sync marker")

    expected = set(OWNED_REGIONS[path])
    if set(regions) != expected:
        raise ProtocolError(f"{path} marker ids must be {sorted(expected)}")
    for region_id, (_start, _end, _inner_start, _inner_end, inner) in regions.items():
        if region_id == "docs-nav-release-label" and inner != f"What's new (v{version})":
            raise ProtocolError(f"{path} docs nav label does not match release state")
    return regions


def generated_content_sha256(tree: dict[str, bytes], state: dict[str, Any]) -> str:
    records: list[dict[str, str]] = []
    version = state["release"]["version"]
    for path in sorted(OWNED_REGIONS):
        try:
            text = tree[path].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProtocolError(f"{path} is not UTF-8") from exc
        if "\r" in text or text.startswith("\ufeff"):
            raise ProtocolError(f"{path} must use UTF-8 LF text without a BOM")
        regions = _read_markers(text, path, version)
        for region_id in sorted(regions):
            records.append(
                {
                    "content_sha256": hashlib.sha256(regions[region_id][4].encode("utf-8")).hexdigest(),
                    "id": region_id,
                    "path": path,
                }
            )
    payload = {"schema_version": 1, "regions": records}
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def strip_owned_regions(tree: dict[str, bytes], state: dict[str, Any]) -> dict[str, bytes]:
    stripped: dict[str, bytes] = {}
    version = state["release"]["version"]
    for path, raw in tree.items():
        if path not in OWNED_REGIONS:
            stripped[path] = raw
            continue
        text = raw.decode("utf-8")
        regions = _read_markers(text, path, version)
        for _region_id, (_start, _end, inner_start, inner_end, _inner) in sorted(
            regions.items(), key=lambda item: item[1][2], reverse=True
        ):
            text = text[:inner_start] + text[inner_end:]
        stripped[path] = text.encode("utf-8")
    return stripped


def _run_git(repository: Path, *arguments: str, text: bool = False) -> bytes | str:
    completed = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode:
        message = completed.stderr.decode("utf-8", "replace").strip()
        raise ProtocolError(f"git {' '.join(arguments)} failed: {message}")
    return completed.stdout.decode("utf-8") if text else completed.stdout


def _validate_sha(value: str, name: str) -> None:
    if SHA1_RE.fullmatch(value) is None:
        raise ProtocolError(f"{name} must be a lowercase 40-character commit SHA")


def git_file(repository: Path, sha: str, path: str) -> bytes:
    return _run_git(repository, "show", f"{sha}:{path}")  # type: ignore[return-value]



def _validate_tree(tree: dict[str, bytes], state: dict[str, Any], sha: str) -> None:
    expected_digest = generated_content_sha256(tree, state)
    if state["generated_content_sha256"] != expected_digest:
        raise ProtocolError(f"{sha} {STATE_PATH} does not match exact owned-region bytes")


def git_tree(repository: Path, sha: str) -> dict[str, bytes]:
    state = validate_release_state(git_file(repository, sha, STATE_PATH))
    tree = {path: git_file(repository, sha, path) for path in OWNED_REGIONS}
    _validate_tree(tree, state, sha)
    return tree


def changed_paths(repository: Path, base_sha: str, head_sha: str) -> list[str]:
    raw = _run_git(repository, "diff", "--name-only", "--no-renames", "-z", base_sha, head_sha)
    paths = raw.split(b"\0")
    decoded: list[str] = []
    for path in paths:
        if not path:
            continue
        try:
            decoded.append(path.decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise CandidateError("candidate changed a non-UTF-8 path") from exc
    return decoded


def validate_generated_change(
    repository: Path,
    base_sha: str,
    head_sha: str,
    trusted_root: Path,
) -> dict[str, Any]:
    _validate_sha(base_sha, "base_sha")
    _validate_sha(head_sha, "head_sha")
    if not trusted_root.is_dir():
        raise ProtocolError("trusted_root does not exist")
    trusted_checker = Path(__file__).resolve()
    if trusted_checker != trusted_root and trusted_root not in trusted_checker.parents:
        raise ProtocolError("ownership checker is not running from trusted_root")
    paths = changed_paths(repository, base_sha, head_sha)
    if not paths:
        raise CandidateError("generated review candidate has no changed paths")
    forbidden = sorted(set(paths) - GENERATED_PATHS)
    if forbidden:
        raise CandidateError(f"candidate changed non-generated paths: {', '.join(forbidden)}")

    base_control_raw = git_file(repository, base_sha, CONTROL_PATH)
    base_control = validate_control(base_control_raw)
    head_control_raw = git_file(repository, head_sha, CONTROL_PATH)
    if base_control_raw != head_control_raw:
        raise CandidateError("candidate changed release-sync-control.json")
    if base_control["mode"] != "active":
        raise CandidateError("release synchronization is held")

    base_state_raw = git_file(repository, base_sha, STATE_PATH)
    base_state = validate_release_state(base_state_raw)
    head_state_raw = git_file(repository, head_sha, STATE_PATH)
    try:
        head_state = validate_release_state(head_state_raw)
    except ProtocolError as exc:
        raise CandidateError(f"candidate {STATE_PATH} is invalid: {exc}") from exc
    compare_release_states(base_state, head_state)
    if head_state["release"]["id"] in base_control["blocked_release_ids"]:
        raise CandidateError("candidate release id is blocked by release-sync-control.json")

    base_tree = git_tree(repository, base_sha)
    head_tree = {path: git_file(repository, head_sha, path) for path in OWNED_REGIONS}
    try:
        _validate_tree(head_tree, head_state, head_sha)
        head_stripped = strip_owned_regions(head_tree, head_state)
    except ProtocolError as exc:
        raise CandidateError(f"candidate generated content is invalid: {exc}") from exc
    base_stripped = strip_owned_regions(base_tree, base_state)
    if base_stripped != head_stripped:
        raise CandidateError("candidate modified human-owned bytes")
    return {
        "changed_paths": paths,
        "control_sha256": hashlib.sha256(base_control_raw).hexdigest(),
        "generated_region_count": sum(len(ids) for ids in OWNED_REGIONS.values()),
        "release_id": head_state["release"]["id"],
        "release_version": head_state["release"]["version"],
    }


def _self_test() -> int:
    test_file = Path(__file__).with_name("test-release-sync.py")
    completed = subprocess.run([sys.executable, str(test_file), "--case", "ownership-review-cas"], check=False)
    return completed.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trusted-root", type=Path)
    parser.add_argument("--base-sha")
    parser.add_argument("--head-sha")
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        if any((args.trusted_root, args.base_sha, args.head_sha)):
            parser.error("--self-test cannot be combined with validation inputs")
        return _self_test()
    if not all((args.trusted_root, args.base_sha, args.head_sha)):
        parser.error("--trusted-root, --base-sha, and --head-sha are required")
    try:
        result = validate_generated_change(
            args.repository.resolve(), args.base_sha, args.head_sha, args.trusted_root.resolve()
        )
    except ProtocolError as exc:
        print(f"generated ownership rejected: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"eligible": True, **result}, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
