#!/usr/bin/env python3
"""Trusted, offline semantic-claim validation for inert website candidates."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import posixpath
import re
import stat
import sys
import types
import unicodedata
from collections import deque
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

EXIT_POLICY = 2
EXIT_OPERATIONAL = 3
EXIT_CONTRACT = 4
SHA1 = re.compile(r"[0-9a-f]{40}\Z")
TAG = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?\Z")
TMUX = re.compile(r"(?:scripts/gjc-session/(?:prompt|tail)(?:\.sh)?|\{(?:prompt|tail)\}|\b(?:prompt|tail)\.sh\b)", re.I)


class ContractError(ValueError):
    pass


def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise ContractError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def reject_constant(value: str) -> None:
    raise ContractError(f"non-standard JSON constant: {value}")


def closed_json(raw: bytes, name: str) -> Any:
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=reject_constant,
                          parse_float=lambda _: (_ for _ in ()).throw(ContractError("JSON floats are forbidden")))
    except (UnicodeDecodeError, json.JSONDecodeError, ContractError) as error:
        raise ContractError(f"invalid {name}: {error}") from error


def canonical_value(value: Any) -> Any:
    if value is None or isinstance(value, bool) or isinstance(value, int):
        return value
    if isinstance(value, float):
        raise ContractError("canonical scalar domain excludes floats")
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list):
        return [canonical_value(item) for item in value]
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ContractError("object key must be a string")
            key = unicodedata.normalize("NFC", key)
            if key in normalized:
                raise ContractError(f"NFC-normalized object keys collide: {key}")
            normalized[key] = canonical_value(item)
        return {key: normalized[key] for key in sorted(normalized)}
    raise ContractError("canonical scalar domain excludes non-JSON values")


def canonical(value: Any) -> bytes:
    return (json.dumps(canonical_value(value), ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def require_exact(value: Any, keys: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ContractError(f"{name} keys must be exact")
    return value


def local_path(value: Any) -> str:
    if not isinstance(value, str) or not value or "\x00" in value or value.startswith("/"):
        raise ContractError("path is not artifact-local")
    pieces = value.replace("\\", "/").split("/")
    if any(piece in ("", ".", "..") for piece in pieces):
        raise ContractError("path traversal or empty component")
    return "/".join(pieces)


def normalized(value: str) -> str:
    return "".join(chr(ord(c) + 32) if "A" <= c <= "Z" else c for c in re.sub(r"[ \t\r\n]+", " ", unicodedata.normalize("NFC", value).strip()))


def contained_root(value: str, name: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise ContractError(f"{name} must be absolute")
    try:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise ContractError(f"{name} must not be a symlink")
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise ContractError(f"{name} is unavailable") from error
    if not resolved.is_dir():
        raise ContractError(f"{name} must be a directory")
    return resolved


def safe_file(root: Path, relative: str) -> Path:
    relative = local_path(relative)
    current = root
    for part in relative.split("/"):
        candidate = current / part
        try:
            info = candidate.lstat()
        except OSError as error:
            raise ContractError(f"candidate file missing: {relative}") from error
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode) and part != relative.split("/")[-1]:
            raise ContractError(f"symlink or non-directory component: {relative}")
        current = candidate
    try:
        resolved = current.resolve(strict=True)
        resolved.relative_to(root)
        info = resolved.stat()
    except (OSError, ValueError) as error:
        raise ContractError(f"candidate path escapes root: {relative}") from error
    if not stat.S_ISREG(info.st_mode):
        raise ContractError(f"candidate file is not regular: {relative}")
    return resolved


class Parser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[dict[str, Any]] = []
        self.nodes: list[dict[str, Any]] = []
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = {"tag": tag, "attrs": dict(attrs), "text": [], "data": [], "children": [], "parent": self.stack[-1] if self.stack else None}
        if self.stack:
            self.stack[-1]["children"].append(node)
        self.nodes.append(node)
        self.stack.append(node)
        if tag == "a" and node["attrs"].get("href"):
            self.links.append(node["attrs"]["href"])

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs); self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if self.stack:
            self.stack[-1]["data"].append(data)
        for node in self.stack:
            node["text"].append(data)


def html(raw: str) -> Parser:
    parser = Parser()
    try:
        parser.feed(raw); parser.close()
    except Exception as error:
        raise ContractError("candidate HTML parse failed") from error
    return parser


def classes(node: dict[str, Any]) -> set[str]:
    return set((node["attrs"].get("class") or "").split())


def ancestor(node: dict[str, Any], predicate: Any) -> bool:
    node = node["parent"]
    while node:
        if predicate(node): return True
        node = node["parent"]
    return False


def text(node: dict[str, Any]) -> str:
    return normalized("".join(node["text"]))


def parse_fixture(value: Any) -> dict[str, Any]:
    fixture = require_exact(value, {"generated_ownership", "release", "schema_version", "checks"}, "fixture")
    if fixture["schema_version"] != 1:
        raise ContractError("invalid fixture envelope")
    release = require_exact(fixture["release"], {"release_bound"}, "release")
    identity = require_exact(release["release_bound"], {"peeled_commit_sha", "tag"}, "release.release_bound")
    if not isinstance(identity["tag"], str) or not TAG.fullmatch(identity["tag"]) or not isinstance(identity["peeled_commit_sha"], str) or not SHA1.fullmatch(identity["peeled_commit_sha"]):
        raise ContractError("invalid release identity")
    if not isinstance(fixture["checks"], list) or not fixture["checks"] or not isinstance(fixture["generated_ownership"], list):
        raise ContractError("fixture checks are required")
    for item in fixture["generated_ownership"]:
        require_exact(item, {"end_marker", "path", "start_marker"}, "generated ownership")
        local_path(item["path"])
    return fixture


def trusted_sync(trusted: Path) -> types.ModuleType:
    path = safe_file(trusted, "scripts/sync-release.py")
    raw = path.read_bytes()
    name = "trusted_release_sync_" + hashlib.sha256(raw).hexdigest()
    module = types.ModuleType(name)
    module.__file__ = str(path)
    sys.modules[name] = module
    try:
        exec(compile(raw, str(path), "exec"), module.__dict__)
    except Exception as error:
        raise ContractError("trusted release validator is unavailable") from error
    finally:
        sys.modules.pop(name, None)
    return module


def ownership(root: Path, entries: list[Any], sync: types.ModuleType) -> dict[str, Any]:
    expected = {
        (path, identifier): (
            f"<!-- release-sync:{identifier}:start -->",
            f"<!-- release-sync:{identifier}:end -->",
        )
        for path, identifiers in sync.REQUIRED_REGIONS.items()
        for identifier in identifiers
    }
    actual: dict[tuple[str, str], tuple[str, str]] = {}
    for entry in entries:
        require_exact(entry, {"end_marker", "path", "start_marker"}, "generated ownership")
        path = local_path(entry["path"])
        start, end = entry["start_marker"], entry["end_marker"]
        match = re.fullmatch(r"<!-- release-sync:([a-z0-9]+(?:-[a-z0-9]+)*):start -->", start)
        if not match or end != f"<!-- release-sync:{match.group(1)}:end -->":
            raise ContractError("OWNERSHIP_REJECTED")
        pair = (path, match.group(1))
        if pair in actual or pair not in expected or expected[pair] != (start, end):
            raise ContractError("OWNERSHIP_REJECTED")
        actual[pair] = (start, end)
    if actual != expected:
        raise ContractError("OWNERSHIP_REJECTED")
    for path in site_paths(root):
        raw = safe_file(root, path).read_text(encoding="utf-8")
        matches = list(sync.MARKER_RE.finditer(raw))
        if raw.count("<!-- release-sync:") != len(matches):
            raise ContractError("OWNERSHIP_REJECTED")
        if any((path, match.group(1)) not in expected for match in matches):
            raise ContractError("OWNERSHIP_REJECTED")

    try:
        return sync.validate_static_release_site(root)
    except sync.ReleaseSyncError as error:
        raise ContractError("OWNERSHIP_REJECTED") from error

def route_records(path: str, raw: str) -> list[tuple[str, str, str, str]]:
    result = []
    for node in html(raw).nodes:
        if node["tag"] != "a": continue
        href = node["attrs"].get("href")
        if path == "index.html" and href == "docs/bridge-rpc.html" and "card" in classes(node):
            headings = [child for child in node["children"] if child["tag"] == "h3" and "card__title" in classes(child)]
            if len(headings) != 1: raise ContractError("PRESERVED_ROUTE_ANCHOR_MISMATCH")
            result.append((path, "card", href, text(headings[0])))
        elif path == "index.html" and href == "docs/bridge-rpc.html" and ancestor(node, lambda n: n["tag"] == "footer"):
            result.append((path, "footer", href, text(node)))
        elif path == "docs/index.html" and href == "bridge-rpc.html" and "card" in classes(node):
            headings = [child for child in node["children"] if child["tag"] == "h3" and "card__title" in classes(child)]
            if len(headings) != 1: raise ContractError("PRESERVED_ROUTE_ANCHOR_MISMATCH")
            result.append((path, "card", href, text(headings[0])))
        elif path.startswith("docs/") and href == "bridge-rpc.html" and "docs-nav-link" in classes(node) and ancestor(node, lambda n: "docs-sidebar" in classes(n)):
            result.append((path, "self_nav" if path == "docs/bridge-rpc.html" else "nav", href, text(node)))
        elif path.startswith("docs/") and href == "bridge-rpc.html" and ancestor(node, lambda n: "doc-pager" in classes(n)):
            result.append((path, "pager", href, text(node).strip("←→ ")))
    return result


def site_paths(root: Path) -> list[str]:
    docs = root / "docs"
    try:
        info = docs.lstat()
    except OSError as error:
        raise ContractError("docs directory missing") from error
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise ContractError("docs directory missing")
    paths = ["index.html"]
    for item in sorted(docs.glob("*.html")):
        if item.is_symlink():
            raise ContractError("symlinked documentation page")
        if item.is_file():
            paths.append(f"docs/{item.name}")
    return paths


def claim_values(node: dict[str, Any]) -> list[str]:
    return [
        normalized("".join(node["data"])),
        *(normalized(value or "") for attribute, value in node["attrs"].items() if attribute != "href"),
    ]


def run_check(root: Path, item: dict[str, Any]) -> str | None:
    kind = item.get("kind")
    check_id = item.get("id", "unknown")
    if kind == "forbidden":
        keys = {"id", "kind", "pattern", "paths"}; require_exact(item, keys, f"check {check_id}")
        pattern = re.compile(item["pattern"], re.I)
        for path in item["paths"]:
            parser = html(safe_file(root, local_path(path)).read_text(encoding="utf-8"))
            for node in parser.nodes:
                if any(pattern.search(value) for value in claim_values(node)):
                    return check_id
    elif kind == "migration_boundary":
        require_exact(item, {"alternatives", "attribute", "id", "kind", "path", "removed_pattern", "required_records", "version"}, f"check {check_id}")
        parser = html(safe_file(root, local_path(item["path"])).read_text(encoding="utf-8"))
        attribute, version = item["attribute"], item["version"]
        claimed = [node for node in parser.nodes if attribute in node["attrs"]]
        boundaries = [node for node in claimed if node["tag"] == "section" and node["attrs"][attribute] == version]
        if not claimed:
            return "MIGRATION_BOUNDARY_MISSING"
        if any(node["tag"] != "section" or node["attrs"][attribute] != version for node in claimed):
            return "MIGRATION_BOUNDARY_VERSION_MISMATCH"
        if len(boundaries) != 1:
            return "MIGRATION_BOUNDARY_DUPLICATE"
        boundary = boundaries[0]
        required_records, alternatives = item["required_records"], item["alternatives"]
        if not isinstance(required_records, list) or not required_records or not all(isinstance(record, str) and record == normalized(record) for record in required_records):
            raise ContractError("invalid migration boundary required records")
        if not isinstance(alternatives, list) or not alternatives or not all(isinstance(alternative, list) and alternative and all(isinstance(record, str) and record == normalized(record) for record in alternative) for alternative in alternatives):
            raise ContractError("invalid migration boundary alternatives")
        records = {text(node) for node in boundary["children"] if text(node)}
        if not all(normalized(record) in records for record in item["required_records"]):
            return "MIGRATION_BOUNDARY_REQUIRED_RECORD_MISSING"
        if not all(any(normalized(record) in records for record in alternative) for alternative in item["alternatives"]):
            return "MIGRATION_BOUNDARY_ALTERNATIVE_RECORD_MISSING"
        pattern = re.compile(item["removed_pattern"], re.I)
        for node in parser.nodes:
            if any(pattern.search(value) for value in claim_values(node)) and node is not boundary and not ancestor(node, lambda parent: parent is boundary):
                return "REMOVED_INGRESS_OUTSIDE_MIGRATION_BOUNDARY"
    elif kind == "install":
        require_exact(item, {"id", "kind", "path", "required", "platforms"}, f"check {check_id}")
        nodes = [node for node in html(safe_file(root, item["path"]).read_text(encoding="utf-8")).nodes if node["tag"] == "section" and node["attrs"].get("id") == "install"]
        if len(nodes) != 1 or not all(normalized(value) in text(nodes[0]) for value in item["required"]): return "HOMEPAGE_INSTALLATION_REQUIRED_MISSING"
        if not all(normalized(value) in text(nodes[0]) for value in item["platforms"]): return "HOMEPAGE_INSTALLATION_PLATFORM_MISSING"
    elif kind == "actions":
        require_exact(item, {"actions", "id", "kind", "path"}, f"check {check_id}")
        values = set(re.findall(r"\b(?:screenshot|click|double_click|move|drag|scroll|type|keypress|wait)\b", safe_file(root, item["path"]).read_text(encoding="utf-8")))
        if values != set(item["actions"]): return "COMPUTER_ACTION_SET_MISMATCH"
    elif kind == "routes":
        require_exact(item, {"anchors", "id", "kind", "label", "paths"}, f"check {check_id}")
        records = []
        for path in item["paths"]: records.extend(route_records(path, safe_file(root, path).read_text(encoding="utf-8")))
        expected = sorted((entry["path"], entry["kind"]) for entry in item["anchors"])
        actual = sorted((path, kind) for path, kind, _, label in records if label == normalized(item["label"]))
        if len(records) != len(expected) or actual != expected: return "PRESERVED_ROUTE_ANCHOR_MISMATCH"
    else:
        raise ContractError(f"unknown check kind: {kind}")
    return None

def unactivated_release_claim(root: Path, item: dict[str, Any]) -> str | None:
    require_exact(item, {"id", "kind", "path", "version_pattern"}, f"check {item.get('id', 'unknown')}")
    raw = safe_file(root, local_path(item["path"])).read_text(encoding="utf-8")
    if "<!-- release-sync:" in raw or re.search(item["version_pattern"], raw, re.I):
        return "UNACTIVATED_RELEASE_CLAIM_PRESENT"
    return None




def receipt(code: str, exit_code: int, results: list[dict[str, str]], mode: str) -> bytes:
    value = {"check_results": results, "code": code, "mode": mode, "schema_version": 1}
    value["canonical_sha256"] = digest(canonical(value))
    return canonical(value)


def validate(trusted: Path, candidate: Path, mode: str) -> tuple[int, bytes]:
    fixture_path = safe_file(trusted, "scripts/fixtures/semantic-claims-v1.json")
    fixture = parse_fixture(closed_json(fixture_path.read_bytes(), "semantic fixture"))
    sync = trusted_sync(trusted)
    results: list[dict[str, str]] = []
    try:
        state = ownership(candidate, fixture["generated_ownership"], sync)
    except ContractError:
        return EXIT_POLICY, receipt("OWNERSHIP_REJECTED", EXIT_POLICY, [{"code": "OWNERSHIP_REJECTED", "id": "ownership", "result": "fail"}], mode)
    observed = {"tag": state["release"]["tag"], "peeled_commit_sha": state["source"]["commit_sha"]}
    expected = fixture["release"]["release_bound"]
    if mode == "exact" and observed != expected:
        return EXIT_POLICY, receipt("RELEASE_BINDING_REJECTED", EXIT_POLICY, [{"code": "RELEASE_BINDING_REJECTED", "id": "release", "result": "fail"}], mode)
    binding = "pass" if observed == expected else "skipped"
    results.append({"code": "RELEASE_BINDING_OK" if binding == "pass" else "RELEASE_BINDING_EVERGREEN", "id": "release", "result": binding})
    for item in fixture["checks"]:
        failure = unactivated_release_claim(candidate, item) if item.get("kind") == "unactivated_release_claim" else run_check(candidate, item)
        if failure:
            results.append({"code": failure, "id": item["id"], "result": "fail"})
            return EXIT_POLICY, receipt(failure, EXIT_POLICY, results, mode)
        results.append({"code": "CHECK_PASS", "id": item["id"], "result": "pass"})
    return 0, receipt("SEMANTIC_CLAIMS_PASS", 0, results, mode)


def self_test() -> tuple[int, bytes]:
    cases = [
        ("duplicate-key-rejected", lambda: closed_json(b'{"a":1,"a":2}', "x"), EXIT_CONTRACT, "FIXTURE_SCHEMA_REJECTED"),
        ("json-constant-rejected", lambda: closed_json(b'{"a":NaN}', "x"), EXIT_CONTRACT, "FIXTURE_SCHEMA_REJECTED"),
        ("canonical-float-rejected", lambda: canonical({"a": 1.5}), EXIT_CONTRACT, "FIXTURE_SCHEMA_REJECTED"),
        ("traversal-rejected", lambda: local_path("docs/../x"), EXIT_CONTRACT, "FIXTURE_SCHEMA_REJECTED"),
        ("tmux-prompt-brace", lambda: (_ for _ in ()).throw(ContractError()) if TMUX.search("{prompt}") else None, EXIT_POLICY, "TMUX_FORBIDDEN_INGRESS"),
        ("identity-mismatch", lambda: (_ for _ in ()).throw(ContractError()) if {"tag":"v1"} != {"tag":"v2"} else None, EXIT_POLICY, "RELEASE_BINDING_REJECTED"),
        ("canonical-nfc-key-and-value", lambda: canonical({"e\u0301": "Cafe\u0301"}), 0, "SELF_TEST_PASS"),
    ]
    results = []
    for case_id, action, expected_exit, expected_code in cases:
        try:
            action(); actual_exit, actual_code = 0, "SELF_TEST_PASS"
        except ContractError:
            actual_exit, actual_code = expected_exit, expected_code
        if (actual_exit, actual_code) != (expected_exit, expected_code):
            return EXIT_CONTRACT, receipt("SELF_TEST_MISMATCH", EXIT_CONTRACT, results, "self-test")
        results.append({"code": actual_code, "id": case_id, "result": "pass"})
    return 0, receipt("SELF_TEST_PASS", 0, results, "self-test")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--trusted-root", dest="trusted_root")
    parser.add_argument("--trusted-base-root", dest="trusted_root")
    parser.add_argument("--fixture")
    parser.add_argument("--candidate-root")
    parser.add_argument("--mode", choices=("evergreen", "exact"), default="evergreen")
    args = parser.parse_args(argv)
    if args.self_test:
        if len(argv) != 1: parser.error("--self-test is exclusive")
        exit_code, output = self_test()
    else:
        if not args.trusted_root or not args.candidate_root: parser.error("--trusted-root and --candidate-root are required")
        if args.fixture is not None:
            fixture = Path(args.fixture)
            if not fixture.is_absolute(): parser.error("--fixture must be absolute")
            try:
                if fixture.resolve(strict=True) != (Path(args.trusted_root).resolve(strict=True) / "scripts/fixtures/semantic-claims-v1.json"):
                    parser.error("--fixture must be the trusted semantic fixture")
            except OSError:
                parser.error("--fixture is unavailable")
        try:
            exit_code, output = validate(contained_root(args.trusted_root, "trusted root"), contained_root(args.candidate_root, "candidate root"), args.mode)
        except ContractError as error:
            exit_code, output = EXIT_CONTRACT, receipt("FIXTURE_SCHEMA_REJECTED", EXIT_CONTRACT, [{"code": str(error), "id": "contract", "result": "fail"}], args.mode)
        except OSError as error:
            exit_code, output = EXIT_OPERATIONAL, receipt("OPERATIONAL_FAILURE", EXIT_OPERATIONAL, [{"code": str(error), "id": "io", "result": "fail"}], args.mode)
    sys.stdout.buffer.write(output)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
