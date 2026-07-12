#!/usr/bin/env python3
"""Hermetic release-sync contract tests.

Every case creates its own temporary Git repositories, release state, source tag,
production release evidence, website tree, and sanitized review API fixture.  No
network, credential, or checkout outside the temporary directory is used.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import base64
import importlib.util
import json
import textwrap
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
SOURCE_REPOSITORY = "Yeachan-Heo/gajae-code"
WEBSITE_REPOSITORY = "Yeachan-Heo/gajae-code-website"
GOLDEN_EVIDENCE_FIXTURE = SCRIPTS / "fixtures" / "release-evidence-v1-golden.json"
GOLDEN_EXPECTED_EVIDENCE_SHA256 = "4416b26a8e0c0fa674423101c394891a52c03dbc7f68679971881958f1f20395"
GOLDEN_FINAL_EVIDENCE_SHA256 = "8faaa18358e07eff7c55d7cdee3f8e788474e7fde477e5fc0f27f03033e1899c"


def load_script(name: str, module_name: str) -> Any:
    spec = importlib.util.spec_from_file_location(module_name, SCRIPTS / name)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        del sys.modules[module_name]
        raise
    return module


OWNERSHIP = load_script("check-generated-ownership.py", "release_sync_ownership")
REVIEW = load_script("check-review-eligibility.py", "release_sync_review")
SYNC = load_script("sync-release.py", "release_sync_generator")
RESOLVER = load_script("resolve-release.py", "release_sync_resolver")
SITE_VALIDATOR = load_script("validate-site.py", "release_sync_site_validator")



def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")

def golden_release_evidence() -> dict[str, Any]:
    raw = GOLDEN_EVIDENCE_FIXTURE.read_bytes()
    fixture = json.loads(raw.decode("utf-8"))
    if raw != canonical_json(fixture):
        raise RuntimeError("release evidence golden fixture is not canonical JSON")
    expected_keys = {
        "expected_evidence",
        "expected_evidence_sha256",
        "final_evidence",
        "final_evidence_sha256",
    }
    if set(fixture) != expected_keys:
        raise RuntimeError("release evidence golden fixture has an invalid envelope")
    expected = fixture["expected_evidence"]
    final = fixture["final_evidence"]
    expected_sha256 = hashlib.sha256(canonical_json(expected)).hexdigest()
    final_sha256 = hashlib.sha256(canonical_json(final)).hexdigest()
    if (
        fixture["expected_evidence_sha256"] != GOLDEN_EXPECTED_EVIDENCE_SHA256
        or expected_sha256 != GOLDEN_EXPECTED_EVIDENCE_SHA256
        or fixture["final_evidence_sha256"] != GOLDEN_FINAL_EVIDENCE_SHA256
        or final_sha256 != GOLDEN_FINAL_EVIDENCE_SHA256
    ):
        raise RuntimeError("release evidence golden fixture SHA-256 assertion failed")
    SYNC.validate_evidence_pair(expected, final)
    return fixture


def bound_golden_evidence(source_commit: str) -> tuple[dict[str, Any], dict[str, Any]]:
    fixture = golden_release_evidence()
    expected = copy.deepcopy(fixture["expected_evidence"])
    final = copy.deepcopy(fixture["final_evidence"])
    expected["source_commit"] = source_commit
    final["source_commit"] = source_commit
    final["expected_evidence_sha256"] = hashlib.sha256(canonical_json(expected)).hexdigest()
    return expected, final


def run(directory: Path, *args: str) -> str:
    completed = subprocess.run(
        [*args], cwd=directory, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    if completed.returncode:
        raise RuntimeError(f"{' '.join(args)} failed: {completed.stderr.strip()}")
    return completed.stdout.strip()


def write(path: Path, data: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        data = data.encode("utf-8")
    path.write_bytes(data)


def state(version: str = "1.2.3", release_id: int = 101, commit: str = "a" * 40) -> dict[str, Any]:
    return {
        "generated_content_sha256": "0" * 64,
        "release": {
            "id": release_id,
            "published_at": "2026-07-12T04:00:25Z",
            "tag": f"v{version}",
            "url": f"https://github.com/{SOURCE_REPOSITORY}/releases/tag/v{version}",
            "version": version,
        },
        "schema_version": 1,
        "source": {
            "changelog_path": "packages/coding-agent/CHANGELOG.md",
            "commit_sha": commit,
            "repository": SOURCE_REPOSITORY,
        },
    }


def release_assets(version: str) -> list[dict[str, Any]]:
    tag = f"v{version}"
    result: list[dict[str, Any]] = []
    for asset_id, name in enumerate(SYNC.REQUIRED_BINARY_ASSET_NAMES, start=1):
        result.append(
            {
                "api_url": f"https://api.github.com/repos/{SOURCE_REPOSITORY}/releases/assets/{asset_id}",
                "browser_download_url": f"https://github.com/{SOURCE_REPOSITORY}/releases/download/{tag}/{name}",
                "digest": f"sha256:{asset_id:064x}",
                "id": asset_id,
                "name": name,
                "size": 1,
            }
        )
    return sorted(result, key=lambda asset: asset["name"])


def control(mode: str = "active", blocked: list[int] | None = None) -> dict[str, Any]:
    return {
        "blocked_release_ids": [] if blocked is None else blocked,
        "mode": mode,
        "reason": "release incident" if mode == "hold" else "",
        "schema_version": 1,
    }


def own_line(region_id: str, body: str) -> str:
    return f"<!-- release-sync:{region_id}:start -->\n{body}\n<!-- release-sync:{region_id}:end -->"


def region_body(region_id: str, version: str) -> str:
    return f"  <span data-release-region=\"{region_id}\">v{version}</span>"


def website_tree(release_state: dict[str, Any]) -> dict[str, bytes]:
    version = release_state["release"]["version"]
    tree: dict[str, bytes] = {}
    index_regions = "\n".join(own_line(region_id, region_body(region_id, version)) for region_id in OWNERSHIP.OWNED_REGIONS["index.html"])
    tree["index.html"] = (
        "<!doctype html>\n<html><head><title>Fixture</title>\n"
        f"{index_regions}\n"
        "</head><body>human-owned landing content</body></html>\n"
    ).encode()
    for path, ids in OWNERSHIP.OWNED_REGIONS.items():
        if path == "index.html":
            continue
        lines = ["<!doctype html>", "<html><head><title>Fixture</title></head><body>", "human-owned documentation v0.7.2 remains historical"]
        for region_id in ids:
            if region_id == "docs-nav-release-label":
                lines.append(
                    "<a class=\"docs-nav-link\" href=\"whats-new.html\">"
                    f"<!-- release-sync:{region_id}:start -->What's new (v{version})"
                    f"<!-- release-sync:{region_id}:end --></a>"
                )
            else:
                lines.append(own_line(region_id, region_body(region_id, version)))
        lines.extend(["</body></html>", ""])
        tree[path] = "\n".join(lines).encode()
    return tree


def write_website(root: Path, release_state: dict[str, Any]) -> None:
    tree = website_tree(release_state)
    digest = OWNERSHIP.generated_content_sha256(tree, release_state)
    complete_state = copy.deepcopy(release_state)
    complete_state["generated_content_sha256"] = digest
    for path, content in tree.items():
        write(root / path, content)
    write(root / "release-sync.json", canonical_json(complete_state))
    write(root / "release-sync-control.json", canonical_json(control()))


def commit_all(repository: Path, message: str) -> str:
    run(repository, "git", "add", "--all")
    run(repository, "git", "commit", "-m", message)
    return run(repository, "git", "rev-parse", "HEAD")


def initialise_git(repository: Path) -> None:
    repository.mkdir(parents=True, exist_ok=True)
    run(repository, "git", "init", "-q")
    run(repository, "git", "config", "user.email", "release-sync-test@example.invalid")
    run(repository, "git", "config", "user.name", "Release Sync Test")


def complete_state_from_repository(root: Path) -> dict[str, Any]:
    return json.loads((root / "release-sync.json").read_text())



class ReleaseSyncFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="release-sync-fixture-")
        self.root = Path(self.temporary.name)
        self.repo = self.root / "website"
        initialise_git(self.repo)
        self.base_state = state(commit="a" * 40)
        write_website(self.repo, self.base_state)
        self.base_sha = commit_all(self.repo, "base release state")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def update_release(self, version: str = "1.2.4", release_id: int = 102, commit: str = "b" * 40) -> str:
        next_state = state(version, release_id, commit)
        write_website(self.repo, next_state)
        return commit_all(self.repo, f"release {version}")

    def event(self, head_sha: str, **overrides: Any) -> dict[str, Any]:
        base_control = (self.repo / "release-sync-control.json").read_bytes()
        value: dict[str, Any] = {
            "repository": WEBSITE_REPOSITORY,
            "pull_request": {
                "base_sha": self.base_sha,
                "draft": False,
                "head_repository": WEBSITE_REPOSITORY,
                "head_ref": "automation/release-sync",
                "head_sha": head_sha,
                "number": 7,
                "writer_app": {"id": 11, "slug": "release-sync-writer"},
            },
            "reviews": [],
            "transaction": {
                "base_sha": self.base_sha,
                "control_sha256": hashlib.sha256(base_control).hexdigest(),
                "head_sha": head_sha,
            },
        }
        for key, item in overrides.items():
            value[key] = item
        return value

    def classify(self, head_sha: str, event: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        event_path = self.root / "event.json"
        write(event_path, canonical_json(event))
        status, output = REVIEW.classify(
            self.repo,
            ROOT,
            self.base_sha,
            head_sha,
            event_path,
            {"id": 11, "slug": "release-sync-writer"},
            {"id": 22, "slug": "release-sync-policy-reviewer"},
            True,
        )
        return status, json.loads(output)

    def test_marker_bytes_and_historical_content_are_preserved(self) -> None:
        head_sha = self.update_release()
        base_tree = OWNERSHIP.git_tree(self.repo, self.base_sha)
        head_tree = OWNERSHIP.git_tree(self.repo, head_sha)
        self.assertEqual(
            OWNERSHIP.strip_owned_regions(base_tree, complete_state_from_repository_at(self.repo, self.base_sha)),
            OWNERSHIP.strip_owned_regions(head_tree, complete_state_from_repository_at(self.repo, head_sha)),
        )
        computer = OWNERSHIP.git_file(self.repo, head_sha, "docs/computer-use.html").decode()
        self.assertIn("human-owned documentation v0.7.2 remains historical", computer)
        bad = head_tree["docs/computer-use.html"].replace(b"What's new (v1.2.4)", b"What's new (v1.2.4)\n")
        with self.assertRaises(OWNERSHIP.ProtocolError):
            OWNERSHIP.generated_content_sha256({**head_tree, "docs/computer-use.html": bad}, complete_state_from_repository_at(self.repo, head_sha))

    def test_generated_ownership_rejects_unowned_tampering_and_hold(self) -> None:
        head_sha = self.update_release()
        result = OWNERSHIP.validate_generated_change(self.repo, self.base_sha, head_sha, ROOT)
        self.assertEqual(result["generated_region_count"], 23)

        source = self.repo / "docs/computer-use.html"
        source.write_text(source.read_text().replace("historical", "rewritten"))
        tampered_sha = commit_all(self.repo, "tamper historical bytes")
        with self.assertRaises(OWNERSHIP.CandidateError):
            OWNERSHIP.validate_generated_change(self.repo, self.base_sha, tampered_sha, ROOT)

        held = self.root / "held"
        run(self.repo, "git", "clone", "-q", str(self.repo), str(held))
        run(held, "git", "config", "user.email", "release-sync-test@example.invalid")
        run(held, "git", "config", "user.name", "Release Sync Test")
        run(held, "git", "checkout", "-q", self.base_sha)
        write(held / "release-sync-control.json", canonical_json(control("hold", [102])))
        held_base_sha = commit_all(held, "hold")
        write_website(held, state("1.2.4", 102, "b" * 40))
        write(held / "release-sync-control.json", canonical_json(control("hold", [102])))
        held_head_sha = commit_all(held, "release while held")
        self.assertEqual(
            OWNERSHIP.git_file(held, held_base_sha, "release-sync-control.json"),
            OWNERSHIP.git_file(held, held_head_sha, "release-sync-control.json"),
        )
        with self.assertRaisesRegex(OWNERSHIP.CandidateError, "release synchronization is held"):
            OWNERSHIP.validate_generated_change(held, held_base_sha, held_head_sha, ROOT)

    def test_review_app_classification_and_cas(self) -> None:
        head_sha = self.update_release()
        reviewer = {"id": 22, "slug": "release-sync-policy-reviewer"}
        cases = (
            ("current approval", head_sha, "APPROVED", "current", "none", True),
            ("stale approval", "c" * 40, "APPROVED", "stale", "approve", False),
            ("current changes requested", head_sha, "CHANGES_REQUESTED", "missing", "approve", False),
            ("current request changes", head_sha, "REQUEST_CHANGES", "missing", "approve", False),
        )
        for name, commit_id, review_state, approval, action, auto_merge in cases:
            with self.subTest(name=name):
                event = self.event(head_sha)
                event["reviews"] = [{"app": reviewer, "commit_id": commit_id, "id": 1, "state": review_state}]
                status, classified = self.classify(head_sha, event)
                self.assertEqual(status, 0)
                self.assertEqual(classified["classification"], "bot-generated")
                self.assertEqual(classified["reviewer_approval"], approval)
                self.assertEqual(classified["review_action"], action)
                self.assertEqual(classified["auto_merge"], auto_merge)

        approved = self.event(head_sha)
        approved["reviews"] = [{"app": reviewer, "commit_id": head_sha, "id": 1, "state": "APPROVED"}]
        draft = self.event(head_sha)
        draft["pull_request"]["draft"] = True
        draft["reviews"] = approved["reviews"]
        _, classified = self.classify(head_sha, draft)
        self.assertEqual(classified["classification"], "human-required")
        self.assertEqual(classified["review_action"], "dismiss")
        self.assertFalse(classified["auto_merge"])

        unowned = self.repo / "docs/computer-use.html"
        unowned.write_text(unowned.read_text().replace("historical", "rewritten"))
        tampered_sha = commit_all(self.repo, "tamper generated review candidate")
        status, classified = self.classify(tampered_sha, self.event(tampered_sha))
        self.assertEqual(status, 0)
        self.assertEqual(classified["classification"], "human-required")
        self.assertEqual(classified["review_action"], "none")
        self.assertFalse(classified["auto_merge"])

        raced = self.event(head_sha)
        raced["transaction"]["control_sha256"] = "0" * 64
        with self.assertRaisesRegex(REVIEW.EventError, "control digest"):
            self.classify(head_sha, raced)

        with mock.patch.object(REVIEW, "_load_trusted_ownership", return_value=OWNERSHIP):
            with mock.patch.object(
                OWNERSHIP, "validate_generated_change", side_effect=OWNERSHIP.ProtocolError("git verification failed")
            ):
                with self.assertRaisesRegex(REVIEW.EventError, "generated ownership verification failed"):
                    self.classify(head_sha, self.event(head_sha))
    def test_noop_and_monotonic_state_races_fail_closed(self) -> None:
        same = complete_state_from_repository_at(self.repo, self.base_sha)
        moved = copy.deepcopy(same)
        moved["source"]["commit_sha"] = "c" * 40
        moved["generated_content_sha256"] = same["generated_content_sha256"]
        with self.assertRaises(OWNERSHIP.ProtocolError):
            OWNERSHIP.compare_release_states(same, moved)
        older = state("1.2.2", 99, "d" * 40)
        older["generated_content_sha256"] = same["generated_content_sha256"]
        with self.assertRaises(OWNERSHIP.ProtocolError):
            OWNERSHIP.compare_release_states(same, older)
        self.assertEqual(OWNERSHIP.changed_paths(self.repo, self.base_sha, self.base_sha), [])
        with self.assertRaises(OWNERSHIP.ProtocolError):
            OWNERSHIP.validate_generated_change(self.repo, self.base_sha, self.base_sha, ROOT)

    def test_schema_versions_reject_booleans_and_same_release_comparison_is_type_strict(self) -> None:
        boolean_state = state()
        boolean_state["schema_version"] = True
        with self.assertRaisesRegex(OWNERSHIP.ProtocolError, "schema_version must be the integer 1"):
            OWNERSHIP.validate_release_state(canonical_json(boolean_state))

        boolean_control = control()
        boolean_control["schema_version"] = True
        with self.assertRaisesRegex(OWNERSHIP.ProtocolError, "schema_version must be the integer 1"):
            OWNERSHIP.validate_control(canonical_json(boolean_control))

        same = complete_state_from_repository_at(self.repo, self.base_sha)
        boolean_schema = copy.deepcopy(same)
        boolean_schema["schema_version"] = True
        with self.assertRaisesRegex(OWNERSHIP.CandidateError, "same immutable release must be a no-op"):
            OWNERSHIP.compare_release_states(same, boolean_schema)


def complete_state_from_repository_at(repository: Path, sha: str) -> dict[str, Any]:
    return OWNERSHIP.validate_release_state(OWNERSHIP.git_file(repository, sha, "release-sync.json"))


class ResolverGeneratorFixture(unittest.TestCase):
    def test_resolver_tag_fixture_peels_annotated_tags_and_rejects_cycles(self) -> None:
        ref_url = f"{RESOLVER.API_ROOT}/git/ref/tags/v1.2.3"
        first_tag = "1" * 40
        second_tag = "2" * 40
        commit = "3" * 40
        responses = {
            ref_url: {"object": {"type": "tag", "sha": first_tag}},
            f"{RESOLVER.API_ROOT}/git/tags/{first_tag}": {"object": {"type": "tag", "sha": second_tag}},
            f"{RESOLVER.API_ROOT}/git/tags/{second_tag}": {"object": {"type": "commit", "sha": commit}},
        }
        original_request_json = RESOLVER.request_json
        try:
            RESOLVER.request_json = lambda url, _label: responses[url]
            self.assertEqual(RESOLVER.resolve_tag("v1.2.3"), commit)
            self.assertEqual(RESOLVER.normalize_timestamp("2026-07-12T05:00:25+01:00"), "2026-07-12T04:00:25Z")
            responses[f"{RESOLVER.API_ROOT}/git/tags/{second_tag}"] = {"object": {"type": "tag", "sha": first_tag}}
            with self.assertRaises(RESOLVER.ResolverError):
                RESOLVER.resolve_tag("v1.2.3")
        finally:
            RESOLVER.request_json = original_request_json

    def test_detached_source_fixture_drives_real_generator_and_closed_schemas(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-sync-source-") as temporary:
            root = Path(temporary)
            source = root / "source"
            website = root / "website"
            initialise_git(source)
            version = "1.2.3"
            write(
                source / "package.json",
                canonical_json(
                    {
                        "workspaces": {
                            "catalog": {
                                "@gajae-code/ai": version,
                                "@gajae-code/coding-agent": version,
                            }
                        }
                    }
                ),
            )
            write(source / "Cargo.toml", f"[workspace.package]\nversion = \"{version}\"\n")
            changelog = b"# Changelog\n\n## [1.2.3] - 2026-07-12\n\n### Added\n\n- Fixture release.\n"
            write(source / "packages/coding-agent/CHANGELOG.md", changelog)
            for name, package_dir in SYNC.EXPECTED_PACKAGES.items():
                manifest: dict[str, Any] = {"name": name, "version": version}
                if name == "@gajae-code/coding-agent":
                    manifest["devDependencies"] = {"@gajae-code/ai": "catalog:"}
                write(source / package_dir / "package.json", canonical_json(manifest))
            tag_commit = commit_all(source, "source release")
            run(source, "git", "tag", f"v{version}")
            run(source, "git", "checkout", "--detach", "-q", f"v{version}")
            self.assertEqual(run(source, "git", "rev-parse", "HEAD"), tag_commit)
            self.assertEqual(run(source, "git", "status", "--porcelain"), "")
            golden = golden_release_evidence()
            golden_expected_raw = canonical_json(golden["expected_evidence"])
            golden_final_raw = canonical_json(golden["final_evidence"])
            resolver_workspace = root / "resolver-evidence"
            resolver_workspace.mkdir()
            resolver_release = {
                "asset_map": {
                    SYNC.EXPECTED_EVIDENCE_NAME: {"name": SYNC.EXPECTED_EVIDENCE_NAME},
                    SYNC.FINAL_EVIDENCE_NAME: {"name": SYNC.FINAL_EVIDENCE_NAME},
                },
                "tag": f"v{version}",
            }
            original_downloaded_asset = RESOLVER.downloaded_asset
            try:
                RESOLVER.downloaded_asset = lambda asset, _label: {
                    SYNC.EXPECTED_EVIDENCE_NAME: golden_expected_raw,
                    SYNC.FINAL_EVIDENCE_NAME: golden_final_raw,
                }[asset["name"]]
                self.assertEqual(
                    RESOLVER.evidence_from_release(resolver_release, "0" * 40, resolver_workspace),
                    (golden["expected_evidence"], golden["final_evidence"]),
                )
                self.assertEqual((resolver_workspace / SYNC.EXPECTED_EVIDENCE_NAME).read_bytes(), golden_expected_raw)
                self.assertEqual((resolver_workspace / SYNC.FINAL_EVIDENCE_NAME).read_bytes(), golden_final_raw)
            finally:
                RESOLVER.downloaded_asset = original_downloaded_asset

            expected_evidence, final_evidence = bound_golden_evidence(tag_commit)
            expected_raw = canonical_json(expected_evidence)
            evidence_raw = canonical_json(final_evidence)
            records = final_evidence["packages"]
            write(root / SYNC.EXPECTED_EVIDENCE_NAME, expected_raw)
            write(root / SYNC.FINAL_EVIDENCE_NAME, evidence_raw)
            snapshot = {
                "expected_evidence": expected_evidence,
                "final_evidence": final_evidence,
                "release": {
                    "assets": release_assets(version),
                    "draft": False,
                    "html_url": f"https://github.com/{SOURCE_REPOSITORY}/releases/tag/v{version}",
                    "id": 101,
                    "name": f"v{version}",
                    "peeled_commit_sha": tag_commit,
                    "prerelease": False,
                    "published_at": "2026-07-12T04:00:25Z",
                    "tag": f"v{version}",
                    "target_commitish": "main",
                },
                "requested": {"hint_tag": "", "mode": "latest", "source_run_url": ""},
                "schema_version": 1,
                "source_checkout": {
                    "changelog_path": "packages/coding-agent/CHANGELOG.md",
                    "changelog_sha256": hashlib.sha256(changelog).hexdigest(),
                    "package_evidence_asset_sha256": hashlib.sha256(evidence_raw).hexdigest(),
                    "path": "source",
                    "peeled_commit_sha": tag_commit,
                },
            }
            snapshot_path = root / "snapshot.json"
            write(snapshot_path, canonical_json(snapshot))
            write_website(website, state(version, 101, tag_commit))
            (website / "release-sync.json").unlink()
            symlinked_website = root / "website-symlink"
            symlinked_website.symlink_to(website, target_is_directory=True)
            website_before = {
                path: path.read_bytes()
                for path in (website / "index.html", website / "release-sync-control.json")
            }
            rejected = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "sync-release.py"),
                    "--snapshot",
                    str(snapshot_path),
                    "--source-dir",
                    str(source),
                    "--website-root",
                    str(symlinked_website),
                ],
                cwd=root,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("website root must be a real directory", rejected.stderr)
            self.assertEqual(
                {path: path.read_bytes() for path in website_before},
                website_before,
            )
            self.assertFalse((website / "release-sync.json").exists())

            changed = SYNC.synchronize(snapshot_path, source, website, check=False)
            self.assertIn("release-sync.json", changed)
            generated = SYNC.validate_static_release_site(website)
            self.assertEqual(generated["release"]["id"], 101)
            whats_new_path = website / "docs/whats-new.html"
            release_state_path = website / "release-sync.json"
            whats_new_before = whats_new_path.read_bytes()
            release_state_before = release_state_path.read_bytes()
            malicious_whats_new = whats_new_before.replace(
                b"          <ul>\n            <li>",
                b"          <ul>\n            <script>alert(1)</script>\n            <li>",
                1,
            )
            self.assertNotEqual(malicious_whats_new, whats_new_before)
            write(whats_new_path, malicious_whats_new)
            tampered_regions = [
                region
                for relative_path in SYNC.REQUIRED_REGIONS
                for region in SYNC.extract_regions(
                    relative_path, (website / relative_path).read_text(encoding="utf-8")
                ).values()
            ]
            tampered_state = json.loads(release_state_before)
            tampered_state["generated_content_sha256"] = SYNC.digest_regions(tampered_regions)
            write(release_state_path, canonical_json(tampered_state))
            with self.assertRaisesRegex(SYNC.ReleaseSyncError, "invalid changelog section grammar"):
                SYNC.validate_static_release_site(website)
            write(whats_new_path, whats_new_before)
            write(release_state_path, release_state_before)
            overflow_item = " ".join(
                f'<a href="https://github.com/{SOURCE_REPOSITORY}/issues/{number}" target="_blank" rel="noopener noreferrer">#{number}</a>'
                for number in range(1, 66)
            )
            overflow_whats_new = whats_new_before.replace(b"Fixture release.", overflow_item.encode("utf-8"), 1)
            self.assertNotEqual(overflow_whats_new, whats_new_before)
            write(whats_new_path, overflow_whats_new)
            overflow_regions = [
                region
                for relative_path in SYNC.REQUIRED_REGIONS
                for region in SYNC.extract_regions(
                    relative_path, (website / relative_path).read_text(encoding="utf-8")
                ).values()
            ]
            overflow_state = json.loads(release_state_before)
            overflow_state["generated_content_sha256"] = SYNC.digest_regions(overflow_regions)
            write(release_state_path, canonical_json(overflow_state))
            with self.assertRaisesRegex(SYNC.ReleaseSyncError, "exceeds 64 changelog links"):
                SYNC.validate_static_release_site(website)
            write(whats_new_path, whats_new_before)
            write(release_state_path, release_state_before)
            self.assertEqual(SYNC.synchronize(snapshot_path, source, website, check=True), [])
            SYNC.validate_source_manifests(source, final_evidence)
            self.assertEqual(
                RESOLVER.manifest_internal_dependencies(
                    {"devDependencies": {"@gajae-code/ai": version}}, "registry manifest fixture"
                ),
                {"@gajae-code/ai": version},
            )


            self.assertEqual(SYNC.validate_evidence_pair(expected_evidence, final_evidence), (expected_evidence, final_evidence))
            self.assertEqual(SYNC.validate_final_evidence(final_evidence), final_evidence)
            self.assertEqual(SYNC.validate_expected_evidence(expected_evidence), expected_evidence)
            for label, validator, valid in (
                ("final evidence", SYNC.validate_final_evidence, final_evidence),
                ("expected evidence", SYNC.validate_expected_evidence, expected_evidence),
                ("resolver snapshot", SYNC.validate_snapshot, snapshot),
                ("release state", SYNC.validate_state, state(version, 101, tag_commit)),
                ("release control", SYNC.validate_control, control()),
            ):
                with self.subTest(schema_validator=label):
                    boolean_schema = copy.deepcopy(valid)
                    boolean_schema["schema_version"] = True
                    with self.assertRaisesRegex(SYNC.ReleaseSyncError, "schema_version must equal 1 and be an integer"):
                        validator(boolean_schema)
            contradictory_expected = copy.deepcopy(expected_evidence)
            contradictory_expected["packages"][0]["expected_sri"] = "sha512-" + base64.b64encode(b"y" * 64).decode("ascii")
            with self.assertRaisesRegex(SYNC.ReleaseSyncError, "expected_sri does not match tarball_sha512"):
                SYNC.validate_expected_evidence(contradictory_expected)
            contradictory_final = copy.deepcopy(final_evidence)
            contradictory_final["packages"][0]["registry_sri"] = "sha512-" + base64.b64encode(b"y" * 64).decode("ascii")
            with self.assertRaisesRegex(SYNC.ReleaseSyncError, "registry_sri does not match registry_tarball_sha512"):
                SYNC.validate_final_evidence(contradictory_final)
            obsolete_package_alias = copy.deepcopy(final_evidence)
            obsolete_package_alias["packages"][0]["expected_dist_integrity"] = obsolete_package_alias["packages"][0].pop("expected_sri")
            with self.assertRaisesRegex(SYNC.ReleaseSyncError, "invalid keys"):
                SYNC.validate_final_evidence(obsolete_package_alias)
            obsolete_registry_alias = copy.deepcopy(final_evidence)
            obsolete_registry_alias["packages"][0]["registry_dist_integrity"] = obsolete_registry_alias["packages"][0].pop("registry_sri")
            with self.assertRaisesRegex(SYNC.ReleaseSyncError, "invalid keys"):
                SYNC.validate_final_evidence(obsolete_registry_alias)
            obsolete_source_commit_alias = copy.deepcopy(final_evidence)
            obsolete_source_commit_alias["source_commit_sha"] = obsolete_source_commit_alias.pop("source_commit")
            with self.assertRaisesRegex(SYNC.ReleaseSyncError, "invalid keys"):
                SYNC.validate_final_evidence(obsolete_source_commit_alias)
            obsolete_envelope_alias = copy.deepcopy(final_evidence)
            obsolete_envelope_alias["expected_asset_sha256"] = obsolete_envelope_alias.pop("expected_evidence_sha256")
            with self.assertRaisesRegex(SYNC.ReleaseSyncError, "invalid keys"):
                SYNC.validate_final_evidence(obsolete_envelope_alias)

            contaminated = copy.deepcopy(final_evidence)
            contaminated["sandbox_namespace"] = "@gajae-code-sync-sandbox"
            with self.assertRaisesRegex(SYNC.ReleaseSyncError, "invalid keys"):
                SYNC.validate_final_evidence(contaminated)
            malformed_schema = copy.deepcopy(final_evidence)
            malformed_schema["schema_version"] = 2
            with self.assertRaisesRegex(SYNC.ReleaseSyncError, "schema_version must equal 1"):
                SYNC.validate_final_evidence(malformed_schema)

            mismatched_expected, mismatched_final = bound_golden_evidence("c" * 40)
            mismatched_expected_raw = canonical_json(mismatched_expected)
            mismatched_final_raw = canonical_json(mismatched_final)
            identity_mismatch_snapshot = copy.deepcopy(snapshot)
            identity_mismatch_snapshot["expected_evidence"] = mismatched_expected
            identity_mismatch_snapshot["final_evidence"] = mismatched_final
            identity_mismatch_snapshot["source_checkout"]["package_evidence_asset_sha256"] = hashlib.sha256(
                mismatched_final_raw
            ).hexdigest()
            write(root / SYNC.EXPECTED_EVIDENCE_NAME, mismatched_expected_raw)
            write(root / SYNC.FINAL_EVIDENCE_NAME, mismatched_final_raw)
            write(snapshot_path, canonical_json(identity_mismatch_snapshot))
            with self.assertRaisesRegex(SYNC.ReleaseSyncError, "source_commit differs from release SHA"):
                SYNC.synchronize(snapshot_path, source, website, check=True)
            write(root / SYNC.EXPECTED_EVIDENCE_NAME, expected_raw)
            write(root / SYNC.FINAL_EVIDENCE_NAME, evidence_raw)
            write(snapshot_path, canonical_json(snapshot))

            baseline_index = (website / "index.html").read_bytes()
            write(website / "release-sync-control.json", canonical_json(control("hold")))
            with self.assertRaises(SYNC.ReleaseSyncError):
                SYNC.synchronize(snapshot_path, source, website, check=False)
            self.assertEqual((website / "index.html").read_bytes(), baseline_index)
            write(website / "release-sync-control.json", canonical_json(control("active", [101])))
            with self.assertRaises(SYNC.ReleaseSyncError):
                SYNC.synchronize(snapshot_path, source, website, check=False)
            self.assertEqual((website / "index.html").read_bytes(), baseline_index)
            write(website / "release-sync-control.json", canonical_json(control()))

            drifted_index = baseline_index.replace(b"v1.2.3", b"v9.9.9", 1)
            write(website / "index.html", drifted_index)
            with self.assertRaisesRegex(SYNC.ReleaseSyncError, "release synchronization drift"):
                SYNC.synchronize(snapshot_path, source, website, check=True)
            self.assertEqual((website / "index.html").read_bytes(), drifted_index)
            write(website / "index.html", baseline_index)

            root_manifest = json.loads((source / "package.json").read_text())
            root_manifest["workspaces"]["catalogs"] = {"release": {"@gajae-code/ai": version}}
            write(source / "package.json", canonical_json(root_manifest))
            agent_manifest_path = source / SYNC.EXPECTED_PACKAGES["@gajae-code/agent-core"] / "package.json"
            agent_manifest = json.loads(agent_manifest_path.read_text())
            agent_manifest["dependencies"] = {"@gajae-code/ai": "catalog:release"}
            write(agent_manifest_path, canonical_json(agent_manifest))
            agent_record = next(record for record in records if record["name"] == "@gajae-code/agent-core")
            agent_record["internal_dependencies"] = {"@gajae-code/ai": version}
            agent_record["registry_internal_dependencies"] = {"@gajae-code/ai": version}
            SYNC.validate_source_manifests(source, final_evidence)
            agent_manifest["dependencies"] = {"@gajae-code/ai": "file:../ai"}
            write(agent_manifest_path, canonical_json(agent_manifest))
            SYNC.validate_source_manifests(source, final_evidence)
            agent_manifest["peerDependencies"] = {"@gajae-code/ai": "workspace:1.2.2"}
            write(agent_manifest_path, canonical_json(agent_manifest))
            with self.assertRaisesRegex(SYNC.ReleaseSyncError, "conflicting dependency declarations"):
                SYNC.validate_source_manifests(source, final_evidence)
            agent_manifest["peerDependencies"] = {}
            agent_manifest["dependencies"] = {"external-fixture": "file:../ai"}
            write(agent_manifest_path, canonical_json(agent_manifest))
            with self.assertRaisesRegex(SYNC.ReleaseSyncError, "external dependency external-fixture cannot use file protocol"):
                SYNC.validate_source_manifests(source, final_evidence)
            agent_record["internal_dependencies"] = {}
            agent_record["registry_internal_dependencies"] = {}
            base_agent_manifest = {"name": "@gajae-code/agent-core", "version": version}
            for field in SYNC.PACKAGE_DEPENDENCY_FIELDS:
                for dependency_name in ("@gajae-code/unknown", "@gajae-code-sync-sandbox/fixture"):
                    with self.subTest(source_dependency_field=field, dependency_name=dependency_name):
                        reserved_manifest = copy.deepcopy(base_agent_manifest)
                        reserved_manifest[field] = {dependency_name: version}
                        write(agent_manifest_path, canonical_json(reserved_manifest))
                        with self.assertRaisesRegex(SYNC.ReleaseSyncError, "unknown reserved package"):
                            SYNC.validate_source_manifests(source, final_evidence)
                    with self.subTest(registry_dependency_field=field, dependency_name=dependency_name):
                        with self.assertRaisesRegex(RESOLVER.ResolverError, "unknown reserved package"):
                            RESOLVER.manifest_internal_dependencies(
                                {field: {dependency_name: version}}, "registry manifest fixture"
                            )

            write(agent_manifest_path, canonical_json(base_agent_manifest))
            extra_manifest_path = source / "packages/unexpected-fixture/package.json"
            write(extra_manifest_path, canonical_json({"name": "unexpected-fixture", "version": version}))
            with self.assertRaisesRegex(SYNC.ReleaseSyncError, "exact expected production package set"):
                SYNC.validate_source_manifests(source, final_evidence)
            extra_manifest_path.unlink()
            agent_manifest_path.unlink()
            with self.assertRaisesRegex(SYNC.ReleaseSyncError, "exact expected production package set"):
                SYNC.validate_source_manifests(source, final_evidence)
            write(agent_manifest_path, canonical_json(base_agent_manifest))



    def test_changelog_continuations_reject_nested_and_block_markdown(self) -> None:
        for continuation in (
            "- nested bullet",
            "+ nested bullet",
            "1. nested ordered list",
            "1) nested ordered list",
            "> nested quote",
            "# nested heading",
            "```",
            "~~~",
            "---",
            "***",
            "| nested table |",
            "  nested code block",
        ):
            with self.subTest(continuation=continuation):
                changelog = (
                    "# Changelog\n\n"
                    "## [1.2.3] - 2026-07-12\n\n"
                    "### Added\n\n"
                    "- Top-level item.\n"
                    f"  {continuation}\n"
                ).encode("utf-8")
                with self.assertRaisesRegex(SYNC.ReleaseSyncError, "unsupported changelog continuation block syntax"):
                    SYNC.parse_changelog(changelog, "1.2.3", "2026-07-12T04:00:25Z", "CHANGELOG.md")

    def test_containment_git_environment_and_binary_digest_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-sync-boundary-") as temporary:
            root = Path(temporary)
            outside = root / "outside"
            outside.mkdir()
            source = root / "source"
            source.mkdir()
            (source / "packages").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(SYNC.ReleaseSyncError, "symlinked path component"):
                SYNC.require_real_child(source, source / "packages" / "agent", "source package")
            website = root / "website"
            website.mkdir()
            (website / "docs").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(SYNC.ReleaseSyncError, "symlinked path component"):
                SYNC.require_real_child(website, website / "docs" / "index.html", "website HTML")

            hostile = {
                "GIT_DIR",
                "GIT_WORK_TREE",
                "GIT_CONFIG_KEY_0",
                "GIT_CONFIG_VALUE_0",
                "GIT_HTTP_PROXY",
                "GIT_HTTP_EXTRAHEADER",
                "HTTP_PROXY",
                "HTTPS_PROXY",
            }
            environment = SYNC.git_environment()
            self.assertTrue(hostile.isdisjoint(environment))
            self.assertEqual(environment["GIT_CONFIG_COUNT"], "0")
            self.assertEqual(RESOLVER.sync.git_environment(), environment)

            ignored_repository = root / "ignored-repository"
            initialise_git(ignored_repository)
            write(ignored_repository / ".gitignore", "ignored-release-sync-test\n")
            commit_all(ignored_repository, "ignore generated artifact")
            write(ignored_repository / "ignored-release-sync-test", "ignored")
            with mock.patch.dict(os.environ, {name: "hostile" for name in hostile}, clear=False):
                self.assertTrue(hostile.isdisjoint(SYNC.git_environment()))
                self.assertTrue(hostile.isdisjoint(RESOLVER.sync.git_environment()))
                self.assertFalse(SYNC.source_status_is_clean(ignored_repository))

            asset = release_assets("1.2.3")[0]
            asset["size"] = 3
            asset["digest"] = "sha256:" + hashlib.sha256(b"abc").hexdigest()
            original_request_bytes = RESOLVER.request_bytes
            try:
                RESOLVER.request_bytes = lambda _url, _label: b"abc"
                self.assertEqual(RESOLVER.downloaded_asset(asset, "fixture binary"), b"abc")
                asset["digest"] = "sha256:" + "0" * 64
                with self.assertRaisesRegex(RESOLVER.ResolverError, "SHA-256"):
                    RESOLVER.downloaded_asset(asset, "fixture binary")
            finally:
                RESOLVER.request_bytes = original_request_bytes

            names = (*SYNC.REQUIRED_BINARY_ASSET_NAMES, SYNC.EXPECTED_EVIDENCE_NAME, SYNC.FINAL_EVIDENCE_NAME)
            metadata_assets = [
                {
                    "browser_download_url": f"https://github.com/{SOURCE_REPOSITORY}/releases/download/v1.2.3/{name}",
                    "digest": "sha256:" + f"{asset_id:064x}",
                    "id": asset_id,
                    "name": name,
                    "size": 1,
                    "url": f"https://api.github.com/repos/{SOURCE_REPOSITORY}/releases/assets/{asset_id}",
                }
                for asset_id, name in enumerate(names, start=1)
            ]
            normalized, _ = RESOLVER.normalize_assets(metadata_assets, "v1.2.3")
            self.assertEqual(len(normalized), len(names))
            metadata_assets[0]["digest"] = "sha256:" + "g" * 64
            with self.assertRaisesRegex(RESOLVER.ResolverError, "SHA-256 digest"):
                RESOLVER.normalize_assets(metadata_assets, "v1.2.3")

    def test_bootstrap_release_copy_is_neutral_and_resolver_requires_both_evidence_assets(self) -> None:
        release_state = json.loads((ROOT / "release-sync.json").read_text(encoding="utf-8"))
        self.assertEqual(release_state["release"]["version"], "0.10.0")
        self.assertEqual(SYNC.validate_static_release_site(ROOT)["release"]["version"], "0.10.0")
        snapshot = {
            "release": {
                "html_url": release_state["release"]["url"],
                "id": release_state["release"]["id"],
                "peeled_commit_sha": release_state["source"]["commit_sha"],
                "published_at": release_state["release"]["published_at"],
                "tag": release_state["release"]["tag"],
            }
        }
        rendered = SYNC.render_regions(snapshot, [("Fixture", ["Bootstrap fixture."])])
        expected_homepage_strip = (
            "  <section class=\"section section--tight\" id=\"latest-release\">\n"
            "    <div class=\"section__header reveal\">\n"
            "      <span class=\"section__eyebrow\">Latest stable · v0.10.0</span>\n"
            "      <h2 class=\"section__title\">Gajae Code v0.10.0</h2>\n"
            "      <p class=\"section__subtitle\">Published 2026-07-12. Release binaries and npm packages are available.</p>\n"
            "      <div class=\"hero__cta\">\n"
            "        <a href=\"docs/whats-new.html\" class=\"btn btn--primary\">Read what’s new</a>\n"
            "        <a href=\"https://github.com/Yeachan-Heo/gajae-code/releases/tag/v0.10.0\" class=\"btn btn--secondary\" target=\"_blank\" rel=\"noopener noreferrer\">GitHub Release</a>\n"
            "      </div>\n"
            "    </div>\n"
            "  </section>\n"
        )
        expected_meta_description = (
            "  <meta name=\"description\" content=\"What’s new in Gajae Code v0.10.0, published 2026-07-12: release highlights and upgrade guidance.\" />\n"
        )
        expected_release_card = (
            "            <a class=\"card\" href=\"whats-new.html\">\n"
            "              <div class=\"card__icon\" aria-hidden=\"true\">✨</div>\n"
            "              <h3 class=\"card__title\">What’s new (v0.10.0)</h3>\n"
            "              <p class=\"card__text\">Read release highlights and upgrade guidance.</p>\n"
            "            </a>\n"
        )
        self.assertEqual(rendered[("index.html", "homepage-release-strip")], expected_homepage_strip)
        self.assertEqual(rendered[("docs/whats-new.html", "whats-new-meta-description")], expected_meta_description)
        self.assertEqual(rendered[("docs/index.html", "docs-latest-release-card")], expected_release_card)
        for content in (expected_homepage_strip, expected_meta_description, expected_release_card):
            self.assertNotIn("verified", content.lower())

        homepage_region = SYNC.extract_regions("index.html", (ROOT / "index.html").read_text(encoding="utf-8"))["homepage-release-strip"]
        description_region = SYNC.extract_regions(
            "docs/whats-new.html", (ROOT / "docs/whats-new.html").read_text(encoding="utf-8")
        )["whats-new-meta-description"]
        self.assertEqual(homepage_region.inner, expected_homepage_strip)
        self.assertEqual(description_region.inner, expected_meta_description)

        names = (*SYNC.REQUIRED_BINARY_ASSET_NAMES, SYNC.EXPECTED_EVIDENCE_NAME, SYNC.FINAL_EVIDENCE_NAME)
        metadata_assets = [
            {
                "browser_download_url": f"https://github.com/{SOURCE_REPOSITORY}/releases/download/v0.10.0/{name}",
                "digest": "sha256:" + f"{asset_id:064x}",
                "id": asset_id,
                "name": name,
                "size": 1,
                "url": f"https://api.github.com/repos/{SOURCE_REPOSITORY}/releases/assets/{asset_id}",
            }
            for asset_id, name in enumerate(names, start=1)
        ]
        for missing_name in (SYNC.EXPECTED_EVIDENCE_NAME, SYNC.FINAL_EVIDENCE_NAME):
            with self.subTest(missing_name=missing_name):
                missing_evidence = [asset for asset in metadata_assets if asset["name"] != missing_name]
                with self.assertRaisesRegex(RESOLVER.ResolverError, f"missing required asset {missing_name}"):
                    RESOLVER.normalize_assets(missing_evidence, "v0.10.0")

    def test_atomic_rollback_fault_injection_reports_restoration_failures(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-sync-atomic-") as temporary:
            root = Path(temporary)
            first = root / "index.html"
            state_path = root / "release-sync.json"
            write(first, b"before-index")
            write(state_path, b"before-state")
            changes = {first: (b"after-index", 0o644), state_path: (b"after-state", 0o644)}

            def fail_before_state(phase: str, path: Path) -> None:
                if phase == "before-replace" and path == state_path:
                    raise OSError("injected replacement failure")

            with self.assertRaisesRegex(SYNC.ReleaseSyncError, "atomic release generation failed"):
                SYNC.write_atomically(changes, state_path, root, fault=fail_before_state)
            self.assertEqual(first.read_bytes(), b"before-index")
            self.assertEqual(state_path.read_bytes(), b"before-state")

            outside = root / "outside"
            write(outside, b"outside")

            def switch_output_to_symlink(phase: str, path: Path) -> None:
                if phase == "before-replace" and path == first:
                    path.unlink()
                    path.symlink_to(outside)

            with self.assertRaisesRegex(SYNC.ReleaseSyncError, "regular non-symlink"):
                SYNC.write_atomically(changes, state_path, root, fault=switch_output_to_symlink)
            self.assertEqual(outside.read_bytes(), b"outside")
            first.unlink()
            write(first, b"before-index")

            def fail_restore(phase: str, path: Path) -> None:
                if phase == "before-replace" and path == state_path:
                    raise OSError("injected replacement failure")
                if phase == "before-restore" and path == first:
                    raise OSError("injected restoration failure")

            with self.assertRaisesRegex(SYNC.ReleaseSyncError, "restoration failures"):
                SYNC.write_atomically(changes, state_path, root, fault=fail_restore)

            def fail_during_staging(phase: str, path: Path) -> None:
                if phase == "before-stage" and path == state_path:
                    raise OSError("injected staging failure")

            original_unlink = Path.unlink

            def fail_staged_cleanup(path: Path) -> None:
                if ".release-sync-" in path.name:
                    raise OSError("injected temporary cleanup failure")
                original_unlink(path)

            with mock.patch.object(Path, "unlink", fail_staged_cleanup):
                with self.assertRaisesRegex(SYNC.ReleaseSyncError, "temporary cleanup failures"):
                    SYNC.write_atomically(changes, state_path, root, fault=fail_during_staging)

    def test_generator_fixture_is_deterministic_and_preserves_unowned_bytes(self) -> None:
        release_state = state("1.2.3", 101, "b" * 40)
        first = website_tree(release_state)
        second = website_tree(release_state)
        self.assertEqual(first, second)
        digest = OWNERSHIP.generated_content_sha256(first, release_state)
        release_state["generated_content_sha256"] = digest
        self.assertEqual(digest, OWNERSHIP.generated_content_sha256(first, release_state))
        self.assertIn(b"v0.7.2 remains historical", first["docs/computer-use.html"])

    def test_site_validator_rejects_unmatched_pre_code_tags(self) -> None:
        SITE_VALIDATOR.validate_pre_code_structure(
            "index.html", '<pre><code><span class="tok-cmd">gjc</span></code></pre>'
        )
        cases = {
            "</code>": "unmatched closing <code>",
            "</pre>": "unmatched closing <pre>",
            "<code>gjc": "unmatched opening <code>",
            "<pre>gjc": "unmatched opening <pre>",
            "<pre><code>gjc</pre></code>": "unmatched closing <pre>",
        }
        for markup, message in cases.items():
            with self.subTest(markup=markup):
                with self.assertRaisesRegex(SITE_VALIDATOR.sync.ReleaseSyncError, message):
                    SITE_VALIDATOR.validate_pre_code_structure("index.html", markup)


class WorkflowContractFixture(unittest.TestCase):
    def workflow(self, name: str) -> str:
        return (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")

    def heredoc(self, workflow: str, opening: str, closing: str) -> str:
        start = workflow.index(opening) + len(opening)
        end = workflow.index(closing, start)
        return textwrap.dedent(workflow[start:end])

    def candidate_status_script(self) -> str:
        return self.heredoc(
            self.workflow("sync-release.yml"),
            'changed_paths="$(python3 - <<\'PY\'\n',
            '          PY\n          )"',
        )

    def normalize_reviews(self, workflow: str) -> Any:
        opening = "          def normalize_reviews(value: object) -> list[dict[str, object]]:\n"
        end = workflow.index("\n          def policy_decision")
        start = workflow.rfind(opening, 0, end)
        if start < 0:
            raise AssertionError("workflow is missing the writer policy review normalizer")
        namespace: dict[str, Any] = {}
        exec(textwrap.dedent(workflow[start:end]), namespace)
        return namespace["normalize_reviews"]

    def validation_tuple_script(self) -> str:
        workflow = self.workflow("validate-site.yml")
        step = workflow.index("      - name: Resolve the immutable base and head tuple\n")
        opening = "        run: |\n"
        start = workflow.index(opening, step) + len(opening)
        end = workflow.index("\n      - name:", start)
        return textwrap.dedent(workflow[start:end])

    def trusted_validator_bootstrap(self) -> str:
        return self.heredoc(
            self.workflow("validate-site.yml"),
            '          python3 -I - "$TRUSTED/scripts/validate-site.py" "$CANDIDATE" <<\'PY\'\n',
            '          PY\n',
        )

    def reconciliation_input_validation_script(self) -> str:
        workflow = self.workflow("sync-release.yml")
        step = workflow.index("      - name: Freeze production configuration and validate the optional hint\n")
        opening = "          python3 - <<'PY'\n"
        start = workflow.index(opening, step) + len(opening)
        end = workflow.index("\n          PY\n", start)
        return textwrap.dedent(workflow[start:end])

    def validation_repository(self, root: Path, contents: list[str]) -> tuple[Path, list[str]]:
        origin = root / "origin.git"
        run(root, "git", "init", "--bare", "-q", str(origin))
        source = root / "source"
        initialise_git(source)
        commits: list[str] = []
        for index, content in enumerate(contents):
            write(source / "index.html", content)
            commits.append(commit_all(source, f"revision {index}"))
        run(source, "git", "branch", "-M", "main")
        run(source, "git", "remote", "add", "origin", str(origin))
        run(source, "git", "push", "-q", "-u", "origin", "main")
        candidate = root / "candidate"
        run(root, "git", "clone", "-q", "--branch", "main", str(origin), str(candidate))
        return candidate, commits

    def run_validation_tuple(self, repository: Path, before: str, head: str, output: Path) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment.update(
            {
                "EVENT_NAME": "push",
                "GITHUB_OUTPUT": str(output),
                "GITHUB_REPOSITORY": WEBSITE_REPOSITORY,
                "WEBSITE_REPOSITORY": WEBSITE_REPOSITORY,
                "PR_BASE_SHA": "",
                "PR_HEAD_SHA": "",
                "PUSH_BEFORE_SHA": before,
                "PUSH_HEAD_SHA": head,
            }
        )
        return subprocess.run(
            ["bash", "-c", self.validation_tuple_script()],
            cwd=repository,
            env=environment,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def run_reconciliation_input_validation(
        self, event_name: str, inputs_json: str | None, output: Path
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment.update({"EVENT_NAME": event_name, "GITHUB_OUTPUT": str(output)})
        if inputs_json is None:
            environment.pop("INPUTS_JSON", None)
        else:
            environment["INPUTS_JSON"] = inputs_json
        return subprocess.run(
            [sys.executable, "-c", self.reconciliation_input_validation_script()],
            cwd=ROOT,
            env=environment,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def test_sync_checkouts_are_pinned_and_main_advance_fails_closed(self) -> None:
        sync = self.workflow("sync-release.yml")
        reviewer = self.workflow("review-release-sync-pr.yml")
        self.assertEqual(sync.count("ref: ${{ github.sha }}"), 6)

        self.assertIn("test \"$(git rev-parse HEAD)\" = \"$DEFAULT_BRANCH_SHA\"", sync)
        self.assertIn('test "$(git -C "$GITHUB_WORKSPACE/trusted" rev-parse HEAD)" = "$DEFAULT_BRANCH_SHA"', sync)
        self.assertNotIn('git switch --detach "origin/${DEFAULT_BRANCH}"', sync)
        self.assertIn('if main_sha != os.environ["PINNED_BASE_SHA"]:', sync)
        self.assertIn("main advanced before Writer-App token mint; discard this worktree", sync)
        self.assertEqual(reviewer.count("ref: ${{ github.sha }}"), 4)
        self.assertIn('if base["sha"] != trusted_base_sha:', reviewer)
        self.assertIn("trusted repository and guard checkouts are not pinned to github.sha", reviewer)

    def test_complete_worktree_rejects_unexpected_changes_and_stages_deleted_pages(self) -> None:
        script = self.candidate_status_script()
        sync = self.workflow("sync-release.yml")
        self.assertIn("git add -A -- index.html docs release-sync.json", sync)
        self.assertIn('git status --porcelain=v1 --untracked-files=all', sync)
        self.assertIn("candidate commit did not leave a clean worktree", sync)
        with tempfile.TemporaryDirectory(prefix="release-sync-worktree-") as temporary:
            repository = Path(temporary) / "website"
            initialise_git(repository)
            write(repository / "index.html", "base\n")
            write(repository / "docs/deleted-generated-page.html", "generated page\n")
            write(repository / "release-sync.json", "{}\n")
            write(repository / "CNAME", "example.invalid\n")
            commit_all(repository, "base")

            (repository / "docs/deleted-generated-page.html").unlink()
            allowed = subprocess.run(
                [sys.executable, "-c", script],
                cwd=repository,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertEqual(allowed.returncode, 0, allowed.stderr)
            self.assertIn("docs/deleted-generated-page.html", allowed.stdout)
            run(repository, "git", "add", "-A", "--", "index.html", "docs", "release-sync.json")
            self.assertIn("D  docs/deleted-generated-page.html", run(repository, "git", "status", "--porcelain"))
            run(repository, "git", "reset", "--hard", "HEAD")

            write(repository / "index.html", "allowed generated change\n")
            write(repository / "CNAME", "unexpected.example.invalid\n")
            mixed = subprocess.run(
                [sys.executable, "-c", script],
                cwd=repository,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertNotEqual(mixed.returncode, 0)
            self.assertIn("undeclared worktree change: CNAME", mixed.stderr)

    def test_writer_and_reviewer_review_inputs_are_equally_bounded_and_typed(self) -> None:
        sync = self.workflow("sync-release.yml")
        reviewer = self.workflow("review-release-sync-pr.yml")
        writer_normalize = self.normalize_reviews(sync)
        valid_review = {
            "id": 1,
            "state": "APPROVED",
            "commit_id": "a" * 40,
            "user": {"id": 22, "login": "release-sync-policy-reviewer[bot]"},
        }
        self.assertEqual(writer_normalize([valid_review])[0]["app"], {"id": 22, "slug": "release-sync-policy-reviewer"})
        with self.assertRaises(SystemExit):
            writer_normalize([valid_review] * 100)
        for invalid in (
            {**valid_review, "id": True},
            {**valid_review, "state": "UNKNOWN"},
            {**valid_review, "commit_id": ""},
            {**valid_review, "user": {"id": 22, "login": ""}},
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(SystemExit):
                    writer_normalize([invalid])
        function_start = "          def normalize_reviews(value: object) -> list[dict[str, object]]:\n"
        sync_start = sync.rfind(function_start, 0, sync.index("          def policy_decision"))
        sync_end = sync.index("\n          def has_current_writer_provenance", sync_start)
        writer_function = sync[sync_start:sync_end]
        self.assertEqual(reviewer.count(writer_function), 2)


    def test_reconciliation_inputs_normalize_only_schedule_nulls(self) -> None:
        sync = self.workflow("sync-release.yml")
        self.assertIn("EVENT_NAME: ${{ github.event_name }}", sync)
        self.assertIn('if event_name == "schedule" and raw in {None, "null"}:', sync)
        self.assertIn('inputs = json.loads(raw)', sync)
        self.assertNotIn('json.loads(raw or "{}")', sync)
        with tempfile.TemporaryDirectory(prefix="release-sync-inputs-") as temporary:
            output = Path(temporary) / "output"
            schedule_absent = self.run_reconciliation_input_validation("schedule", None, output)
            self.assertEqual(schedule_absent.returncode, 0, schedule_absent.stderr)
            self.assertIn("hint_accepted=false\n", output.read_text())

            schedule_null = self.run_reconciliation_input_validation("schedule", "null", output)
            self.assertEqual(schedule_null.returncode, 0, schedule_null.stderr)
            self.assertIn("hint_accepted=false\n", output.read_text())

            dispatch_object = self.run_reconciliation_input_validation(
                "workflow_dispatch", '{"release_hint": ""}', output
            )
            self.assertEqual(dispatch_object.returncode, 0, dispatch_object.stderr)
            self.assertIn("hint_accepted=false\n", output.read_text())

            cleanup_dispatch = self.run_reconciliation_input_validation(
                "workflow_dispatch", '{"release_hint": "", "cleanup_only": "true"}', output
            )
            self.assertEqual(cleanup_dispatch.returncode, 0, cleanup_dispatch.stderr)
            invalid_cleanup_dispatch = self.run_reconciliation_input_validation(
                "workflow_dispatch", '{"release_hint": "", "cleanup_only": "sometimes"}', output
            )
            self.assertNotEqual(invalid_cleanup_dispatch.returncode, 0)


            for malformed_dispatch in ("null", "{", "[]", '{"unexpected": "value"}'):
                with self.subTest(inputs_json=malformed_dispatch):
                    rejected = self.run_reconciliation_input_validation(
                        "workflow_dispatch", malformed_dispatch, output
                    )
                    self.assertNotEqual(rejected.returncode, 0)
    def test_push_before_handles_creation_rejects_malformed_values_and_keeps_full_range(self) -> None:
        zero_sha = "0" * 40
        empty_tree_sha = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
        with tempfile.TemporaryDirectory(prefix="release-sync-validate-creation-") as temporary:
            root = Path(temporary)
            candidate, commits = self.validation_repository(root, ["first\n"])
            output = root / "output"
            created = self.run_validation_tuple(candidate, zero_sha, commits[-1], output)
            self.assertEqual(created.returncode, 0, created.stderr)
            self.assertIn(f"base_sha={empty_tree_sha}\nhead_sha={commits[-1]}\n", output.read_text())

        with tempfile.TemporaryDirectory(prefix="release-sync-validate-malformed-") as temporary:
            root = Path(temporary)
            candidate, commits = self.validation_repository(root, ["first\n"])
            malformed = self.run_validation_tuple(candidate, "not-a-sha", commits[-1], root / "output")
            self.assertNotEqual(malformed.returncode, 0)
            self.assertIn("push before SHA is malformed", malformed.stderr)

        with tempfile.TemporaryDirectory(prefix="release-sync-validate-range-") as temporary:
            root = Path(temporary)
            candidate, commits = self.validation_repository(root, ["first\n", "second\n", "third\n"])
            output = root / "output"
            ranged = self.run_validation_tuple(candidate, commits[0], commits[-1], output)
            self.assertEqual(ranged.returncode, 0, ranged.stderr)
            self.assertIn(f"base_sha={commits[0]}\nhead_sha={commits[-1]}\n", output.read_text())
        validate = self.workflow("validate-site.yml")
        self.assertNotIn('git rev-parse "${head_sha}^"', validate)

    def test_trusted_validator_uses_an_isolated_resolved_candidate_interface(self) -> None:
        validate = self.workflow("validate-site.yml")
        candidate_checkout = validate.index("      - name: Check out candidate objects without executing candidate code\n")
        trusted_checkout = validate.index("      - name: Check out trusted base validation code\n")
        self.assertIn("          path: candidate\n", validate[candidate_checkout:trusted_checkout])
        self.assertIn("          path: trusted\n", validate[trusted_checkout:])
        self.assertEqual(validate.count("        working-directory: candidate\n"), 2)
        self.assertIn('CANDIDATE: ${{ github.workspace }}/candidate', validate)
        self.assertIn('--repository "$GITHUB_WORKSPACE/candidate"', validate)
        self.assertIn('candidate checkout path must not be a symlink', validate)
        self.assertIn('candidate and trusted checkouts must be strictly resolved siblings', validate)
        self.assertIn('python3 -I - "$TRUSTED/scripts/validate-site.py" "$CANDIDATE"', validate)
        self.assertIn('candidate .trusted-validator path is forbidden to prevent validator shadowing', validate)
        self.assertIn('if candidate_root in import_paths:', validate)
        self.assertIn('namespace = {"__name__": "__main__", "__file__": str(trusted_script)}', validate)
        self.assertIn('sync_assignment = \'SYNC_PATH = ROOT / "scripts" / "sync-release.py"\'', validate)
        self.assertIn('SYNC_PATH = Path(sys.argv[1]).resolve(strict=True).with_name("sync-release.py")', validate)
        self.assertNotIn("candidate_script_path", validate)

        with tempfile.TemporaryDirectory(prefix="release-sync-validator-isolation-") as temporary:
            root = Path(temporary)
            trusted_script = root / "trusted" / "scripts" / "validate-site.py"
            candidate = root / "candidate"
            candidate.mkdir()
            write(candidate / "candidate.txt", "candidate data\n")
            write(candidate / "sitecustomize.py", 'raise SystemExit("candidate module executed")\n')
            write(candidate / "scripts" / "sync-release.py", 'raise SystemExit("candidate sync module executed")\n')
            write(trusted_script.with_name("sync-release.py"), "trusted sync\n")
            write(
                trusted_script,
                "from pathlib import Path\n"
                "import sys\n"
                "ROOT = Path(__file__).resolve().parents[1]\n"
                "SYNC_PATH = ROOT / \"scripts\" / \"sync-release.py\"\n"
                "if str(ROOT) in {str(Path(item).resolve(strict=False)) for item in sys.path if item}:\n"
                "    raise SystemExit('candidate root was importable')\n"
                "if (ROOT / 'candidate.txt').read_text() != 'candidate data\\n':\n"
                "    raise SystemExit('candidate root was not passed explicitly')\n"
                "if SYNC_PATH.read_text() != 'trusted sync\\n':\n"
                "    raise SystemExit('candidate sync module was selected')\n",
            )

            def bootstrap(candidate_root: Path, script: Path = trusted_script) -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    [sys.executable, "-I", "-c", self.trusted_validator_bootstrap(), str(script), str(candidate_root)],
                    cwd=root,
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )

            isolated = bootstrap(candidate)
            self.assertEqual(isolated.returncode, 0, isolated.stderr)

            shadow = candidate / ".trusted-validator"
            shadow.mkdir()
            shadow_rejected = bootstrap(candidate)
            self.assertNotEqual(shadow_rejected.returncode, 0)
            self.assertIn("candidate .trusted-validator path is forbidden", shadow_rejected.stderr)
            shadow.rmdir()

            shadow_target = root / "shadow-target"
            shadow_target.mkdir()
            shadow.symlink_to(shadow_target, target_is_directory=True)
            symlink_rejected = bootstrap(candidate)
            self.assertNotEqual(symlink_rejected.returncode, 0)
            self.assertIn("candidate .trusted-validator path is forbidden", symlink_rejected.stderr)
            shadow.unlink()

            non_sibling_candidate = root / "outside" / "candidate"
            non_sibling_candidate.mkdir(parents=True)
            topology_rejected = bootstrap(non_sibling_candidate)
            self.assertNotEqual(topology_rejected.returncode, 0)
            self.assertIn("candidate and trusted checkouts must be strictly resolved siblings", topology_rejected.stderr)

            nested_trusted_script = candidate / "trusted" / "scripts" / "validate-site.py"
            write(nested_trusted_script, "raise SystemExit('candidate trusted checkout executed')\n")
            nested_rejected = bootstrap(candidate, nested_trusted_script)
            self.assertNotEqual(nested_rejected.returncode, 0)
            self.assertIn("trusted validator must be outside the candidate root", nested_rejected.stderr)

            candidate_alias = root / "candidate-alias"
            candidate_alias.symlink_to(candidate, target_is_directory=True)
            alias_rejected = bootstrap(candidate_alias)
            self.assertNotEqual(alias_rejected.returncode, 0)
            self.assertIn("candidate checkout path must not be a symlink", alias_rejected.stderr)

    def test_reviewer_approval_reconciles_timeout_missing_id_and_policy_races(self) -> None:
        reviewer = self.workflow("review-release-sync-pr.yml")
        self.assertIn('policy_decision(pre_confirmed_pull, pre_reviews, "pre-action")', reviewer)
        self.assertIn('policy_decision(final_confirmed_pull, final_reviews, "post-approval")', reviewer)
        self.assertIn('elif final_decision != expected_post_approval_decision:', reviewer)
        self.assertIn('pre_action_ids = {review["id"] for review in exact_head_approvals(pre_post_reviews)}', reviewer)
        self.assertIn('policy_decision(pre_post_pull, pre_post_reviews, "pre-approval-post")', reviewer)
        self.assertIn('raise SystemExit("review lifecycle changed before CAS-bound automated approval")', reviewer)
        self.assertIn('approval request was indeterminate:', reviewer)
        self.assertIn("approval response did not identify the exact Reviewer-App review on the expected head", reviewer)
        self.assertIn("for _attempt in range(3):", reviewer)
        self.assertIn('"new_active": [review for review in active if review["id"] not in pre_action_ids]', reviewer)
        self.assertIn('remaining_new_active_ids', reviewer)
        self.assertIn('rollback = rollback_new_approvals(verification_error, pre_action_ids)', reviewer)
        self.assertIn('"approval_evidence": approval_evidence,', reviewer)
        self.assertIn('"control_sha256": expected["control_sha256"],', reviewer)
        self.assertIn("Reviewer-App approval remained active after dismissal", reviewer)
        self.assertNotIn('api("DELETE", f"/repos/{repository}/pulls/{expected[\'number\']}/reviews/', reviewer)

    def test_reviewer_rollback_accepts_only_a_main_base_advance(self) -> None:
        reviewer = self.workflow("review-release-sync-pr.yml")
        start = reviewer.index("          def rollback_pr_observation(token: str) -> dict[str, object]:\n")
        end = reviewer.index("\n          # The reviewer token", start)
        observation = reviewer[start:end]
        self.assertIn('value["base"]["sha"] != current_main', observation)
        self.assertNotIn('value["base"]["sha"] != expected["base_sha"]', observation)
        for invariant in (
            'value["number"] != expected["number"]',
            'value["base"]["repo"]["full_name"] != repository',
            'value["head"]["sha"] != expected["head_sha"]',
            'value["head"]["repo"]["full_name"] != repository',
            'bool(value["draft"]) != bool(expected["draft"])',
        ):
            with self.subTest(invariant=invariant):
                self.assertIn(invariant, observation)
        self.assertIn('def rollback_observation(token: str, pre_action_ids: set[int])', reviewer)
        self.assertIn('"new_active": [review for review in active if review["id"] not in pre_action_ids]', reviewer)
        self.assertIn('"reviewer_app": {"slug": reviewer_slug, "id": reviewer_id}', reviewer)
        self.assertIn('rollback["auto_merge_rollback"] = rollback_auto_merge(auto_merge_observation)', reviewer)
        self.assertIn('auto-merge remained enabled after Reviewer-App rollback', reviewer)
        self.assertIn('rollback_observation(reviewer_token, pre_action_ids)', reviewer)

    def test_writer_revoked_policy_disables_existing_auto_merge(self) -> None:
        sync = self.workflow("sync-release.yml")
        self.assertIn('policy_decision(pr_data, normalized_reviews, "initial")', sync)
        self.assertIn('fresh_reviews = normalize_reviews(api("GET", f"/repos/{repository}/pulls/{pr_number}/reviews?per_page=100", read_token))', sync)
        self.assertIn('fresh_policy = policy_decision(fresh_pr_data, fresh_reviews, "pre-enable")', sync)
        self.assertIn('if not writer_auto_merge_authorized(fresh_policy):', sync)
        initial_start = sync.index('          if not writer_auto_merge_authorized(policy_value):\n')
        initial_end = sync.index('\n\n          pull = graphql_pull(pr_number)', initial_start)
        revoked_policy = sync[initial_start:initial_end]
        self.assertIn('revocation["rollback"] = disable_revoked_auto_merge(', revoked_policy)
        self.assertIn('revoked-policy auto-merge compensation failed', revoked_policy)
        self.assertLess(revoked_policy.index('disable_revoked_auto_merge('), revoked_policy.index('print(json.dumps'))

        self.assertIn('pre_head_mutation_auto_merge', sync)
        self.assertIn('fixed bot head will be replaced', sync)
        self.assertIn("disablePullRequestAutoMerge", sync)
        self.assertIn('if enable_error:', sync)
        self.assertIn('rollback = disable_auto_merge("enable auto-merge response was indeterminate or not exact-head", pr_number, candidate, after_push["main_sha"], pull["id"])', sync)
        self.assertIn('rollback["verified_auto_merge"] = verified.get("autoMergeRequest")', sync)
        self.assertIn('require_exact_graphql_pull(', sync)
        self.assertIn('"control_sha256": after_push["control_sha256"],', sync)

    def test_workflow_read_tokens_are_explicit_and_never_implicit(self) -> None:
        sync = self.workflow("sync-release.yml")
        reviewer = self.workflow("review-release-sync-pr.yml")
        for workflow, expected_bindings in ((sync, 6), (reviewer, 3)):
            with self.subTest(workflow=workflow[:32]):
                self.assertNotIn("GITHUB_TOKEN", workflow)
                self.assertEqual(workflow.count("GITHUB_READ_TOKEN: ${{ github.token }}"), expected_bindings)
                self.assertIn('os.environ["GITHUB_READ_TOKEN"]', workflow)
        self.assertIn('WRITER_TOKEN: ${{ steps.writer-token.outputs.token }}', sync)
        self.assertIn('REVIEWER_TOKEN: ${{ steps.reviewer-token.outputs.token }}', reviewer)

    def test_writer_auto_merge_rejects_generic_human_or_pending_reviewer_authorization(self) -> None:
        sync = self.workflow("sync-release.yml")
        start = sync.index("          def writer_auto_merge_authorized(policy: dict[str, object]) -> bool:\n")
        end = sync.index("\n          def exact_pr_tuple", start)
        namespace: dict[str, Any] = {}
        exec(textwrap.dedent(sync[start:end]), namespace)
        authorized = namespace["writer_auto_merge_authorized"]
        current = {
            "reviewer_approval": "current",
            "review_action": "none",
            "token_mint_required": False,
            "auto_merge": True,
        }
        self.assertTrue(authorized(current))
        self.assertFalse(authorized({**current, "reviewer_approval": "missing"}))
        self.assertFalse(authorized({**current, "review_action": "approve"}))
        self.assertFalse(authorized({**current, "token_mint_required": True}))
        self.assertFalse(authorized({**current, "auto_merge": False}))
        self.assertIn('if not writer_auto_merge_authorized(policy_value):', sync)
        self.assertIn('if not writer_auto_merge_authorized(fresh_policy):', sync)

    def test_writer_waits_for_verified_reviewer_revocation_cleanup(self) -> None:
        sync = self.workflow("sync-release.yml")
        self.assertIn("    needs: [cleanup-policy-revocation, cleanup-auto-merge]", sync)
        reconcile = sync[sync.index("  reconcile:\n"):sync.index("      - name: Check out trusted website default branch", sync.index("  reconcile:\n"))]
        self.assertIn("needs.cleanup-policy-revocation.result == 'success'", reconcile)
        self.assertIn("needs.cleanup-auto-merge.result == 'success'", reconcile)
        self.assertIn("needs.cleanup-auto-merge.outputs.cleanup_verified == 'true'", reconcile)
        self.assertIn("cleanup_verified: ${{ steps.disable.outputs.cleanup_verified }}", sync)
        self.assertIn('Path(os.environ["GITHUB_OUTPUT"]).write_text("cleanup_verified=true\\n")', sync)
        self.assertLess(sync.index('cleanup_verified=true\\n'), sync.index("  reconcile:\n"))

    def test_writer_reobserves_exact_release_and_evidence_at_both_privileged_boundaries(self) -> None:
        sync = self.workflow("sync-release.yml")
        self.assertIn('"expected_evidence_asset_sha256": evidence_assets["gajae-release-packages-expected-v1.json"]', sync)
        self.assertIn('"final_evidence_asset_sha256": evidence_assets["gajae-release-packages-v1.json"]', sync)
        self.assertIn('reobserve_latest_complete_release("Writer branch mutation", "WRITER_MUTATION_RECHECK_ROOT")', sync)
        self.assertIn('reobserve_latest_complete_release("pre-auto-merge", "WRITER_PRE_ENABLE_RECHECK_ROOT")', sync)
        self.assertIn("if mutation_release != original_release:", sync)
        self.assertIn("if pre_enable_release != original_release:", sync)
        self.assertIn('rollback = disable_auto_merge(release_error, pr_number, candidate, after_push["main_sha"], pull["id"])', sync)
        current_start = sync.index("          def current_tuple(observed_release: dict[str, str | int]) -> dict[str, object]:\n")
        current_end = sync.index("\n          def require_tuple", current_start)
        current_tuple = sync[current_start:current_end]
        self.assertIn('"release": observed_release,', current_tuple)
        self.assertNotIn("snapshot", current_tuple)

    def test_cleanup_revocation_disarms_dismissed_or_false_policy(self) -> None:
        sync = self.workflow("sync-release.yml")
        reviewer = self.workflow("review-release-sync-pr.yml")
        self.assertIn("  push:\n    branches: [main]\n    paths:\n      - release-sync-control.json", sync)
        self.assertIn("cleanup_only:", sync)
        self.assertIn("if: ${{ always() && github.event_name != 'push' && inputs.cleanup_only != true && needs.cleanup-policy-revocation.result == 'success'", sync)
        self.assertIn("  cleanup-policy-revocation:\n", sync)
        self.assertIn("  cleanup-auto-merge:\n", sync)
        self.assertIn("Dismiss revoked approvals and re-run current policy", sync)
        self.assertIn('final_policy = policy(final_pr, final_reviews, final_control, "after-dismissal")', sync)
        self.assertIn('raise SystemExit("Reviewer-App approval remained active after cleanup")', sync)
        self.assertIn('raise SystemExit("cleanup policy unexpectedly still authorizes auto-merge after dismissal")', sync)
        self.assertIn('"authorization_false": True', sync)
        self.assertIn('"approval_ids": [], "auto_merge": False', sync)
        self.assertIn('"variables": {"id": expected["node_id"]}', sync)
        self.assertIn('Reviewer-App approval remained active at cleanup terminal state', sync)
        self.assertNotIn("needs.classify.outputs.auto_merge == 'false'", reviewer)
        self.assertIn("needs.classify.outputs.review_action == 'dismiss'", reviewer)
        self.assertIn('if expected["action"] == "dismiss":', reviewer)
        self.assertIn('policy_decision(final_pull, remaining, "post-dismissal")', reviewer)
        self.assertIn('auto_merge_rollback = rollback_auto_merge(rollback_pr_observation(reviewer_token))', reviewer)
        self.assertIn('raise SystemExit("revocation auto-merge cleanup failed")', reviewer)

        dismiss_start = reviewer.index('          decision = policy_decision(pre_confirmed_pull, pre_reviews, "pre-action")\n')
        dismiss_end = reviewer.index('\n          if decision.get("review_action") != expected["action"]:', dismiss_start)
        dismissed_reviews = [{"id": 73, "state": "APPROVED", "app": {"slug": "reviewer", "id": 17}}]
        dismissal_calls: list[int] = []

        def dismissal_api(method: str, _path: str, _token: str, body: object | None = None) -> object:
            if method == "GET":
                return dismissed_reviews
            self.assertEqual(method, "PUT")
            self.assertEqual(body, {"message": "Release-sync authorization no longer permits automated approval."})
            dismissal_calls.append(73)
            dismissed_reviews[0]["state"] = "DISMISSED"
            return {}

        dismissal_namespace: dict[str, Any] = {
            "api": dismissal_api,
            "expected": {"action": "dismiss", "number": 42, "head_sha": "c" * 40},
            "json": json,
            "normalize_reviews": lambda value: value,
            "policy_decision": lambda _pr, _reviews, _label: {"auto_merge": False},
            "pre_confirmed_pull": {},
            "pre_reviews": list(dismissed_reviews),
            "pull": lambda _token: {},
            "repository": WEBSITE_REPOSITORY,
            "reviewer_id": 17,
            "reviewer_slug": "reviewer",
            "reviewer_token": "reviewer-token",
            "rollback_auto_merge": lambda _observation: {"outcome": "verified-disabled"},
            "rollback_pr_observation": lambda _token: {},
        }
        with self.assertRaises(SystemExit) as dismissed:
            exec(textwrap.dedent(reviewer[dismiss_start:dismiss_end]), dismissal_namespace)
        self.assertEqual(dismissed.exception.code, 0)
        self.assertEqual(dismissal_calls, [73])
        self.assertEqual(dismissed_reviews[0]["state"], "DISMISSED")

    def test_writer_revocation_rebinds_main_after_base_only_advance(self) -> None:
        sync = self.workflow("sync-release.yml")
        start = sync.index("          def current_revocation_pr(number: int, head_sha: str) -> dict[str, object]:\n")
        end = sync.index("\n          def current_tuple", start)
        compensation = sync[start:end]
        for invariant in (
            'value["number"] != number',
            'value["node_id"]',
            'value["base"]["sha"] != current_main',
            'value["base"]["repo"]["full_name"] != repository',
            'value["head"]["sha"] != head_sha',
            'value["head"]["repo"]["full_name"] != repository',
            '"variables": {"id": pull_id}',
            'verified_observation = current_revocation_pr(number, head_sha)',
            'rollback["verified_auto_merge"] = verified.get("autoMergeRequest")',
        ):
            with self.subTest(invariant=invariant):
                self.assertIn(invariant, compensation)
        self.assertIn("for attempt in range(3):", compensation)
        initial_start = sync.index('          if not writer_auto_merge_authorized(policy_value):\n')
        initial_end = sync.index('\n\n          pull = graphql_pull(pr_number)', initial_start)
        self.assertIn("disable_revoked_auto_merge(", sync[initial_start:initial_end])
        fresh_start = sync.index('          if not writer_auto_merge_authorized(fresh_policy):\n')
        fresh_end = sync.index('\n          if (\n              fresh_pull.get("headRefOid")', fresh_start)
        self.assertIn("disable_revoked_auto_merge(", sync[fresh_start:fresh_end])

        old_base = "a" * 40
        advanced_base = "b" * 40
        head = "c" * 40
        node_id = "PR_node"
        state: dict[str, Any] = {"base": old_base, "auto_merge": {"enabledAt": "now"}, "observations": 0, "mutation_ids": []}

        def git(*_args: str) -> str:
            state["observations"] += 1
            return old_base if state["observations"] == 1 else advanced_base

        def api(method: str, path: str, _token: str, body: object | None = None) -> object:
            if method == "GET":
                return {
                    "number": 42,
                    "node_id": node_id,
                    "base": {"ref": "main", "sha": state["base"], "repo": {"full_name": WEBSITE_REPOSITORY}},
                    "head": {"ref": "automation/release-sync", "sha": head, "repo": {"full_name": WEBSITE_REPOSITORY}},
                }
            self.assertEqual(path, "/graphql")
            self.assertIsInstance(body, dict)
            state["mutation_ids"].append(body["variables"]["id"])
            state["auto_merge"] = None
            state["base"] = advanced_base
            return {"data": {"disablePullRequestAutoMerge": {"pullRequest": {"id": node_id, "number": 42, "headRefOid": head, "baseRefOid": advanced_base, "autoMergeRequest": None}}}}

        def graphql_pull(number: int) -> dict[str, object]:
            self.assertEqual(number, 42)
            return {"id": node_id, "number": number, "headRefOid": head, "baseRefOid": state["base"], "autoMergeRequest": state["auto_merge"]}

        def require_exact(value: dict[str, object], number: int, expected_head: str, base: str, pull: str) -> None:
            self.assertEqual((value["id"], value["number"], value["headRefOid"], value["baseRefOid"]), (pull, number, expected_head, base))

        namespace: dict[str, Any] = {
            "api": api,
            "branch": "automation/release-sync",
            "git": git,
            "graphql_pull": graphql_pull,
            "read_token": "read",
            "repository": WEBSITE_REPOSITORY,
            "require_exact_graphql_pull": require_exact,
            "subprocess": mock.Mock(check_call=mock.Mock()),
            "website": Path("/worktree"),
            "writer_token": "writer",
        }
        exec(textwrap.dedent(compensation), namespace)
        rollback = namespace["disable_revoked_auto_merge"]("policy revoked", 42, head)
        self.assertEqual(rollback["outcome"], "verified-disabled")
        self.assertEqual(rollback["verified_base_sha"], advanced_base)
        self.assertEqual(state["mutation_ids"], [node_id])

    def test_reviewer_approves_missing_or_stale_exact_writer_heads_without_treating_preapproval_auto_merge_false_as_revocation(self) -> None:
        reviewer = self.workflow("review-release-sync-pr.yml")
        lifecycle_start = reviewer.index('          decision = policy_decision(pre_confirmed_pull, pre_reviews, "pre-action")\n')
        lifecycle_end = reviewer.index('\n          created_id = created.get("id")', lifecycle_start)
        lifecycle = reviewer[lifecycle_start:lifecycle_end]
        self.assertIn('if expected["action"] == "dismiss":', lifecycle)
        self.assertLess(
            lifecycle.index('if expected["action"] == "dismiss":'),
            lifecycle.index('if decision.get("review_action") != expected["action"]:'),
        )
        self.assertIn('"event": "APPROVE", "commit_id": expected["head_sha"]', lifecycle)
        self.assertIn('api("POST", f"/repos/{repository}/pulls/{expected[\'number\']}/reviews", reviewer_token, {', lifecycle)

    def test_writer_recheck_roots_are_job_scoped_for_always_cleanup(self) -> None:
        sync = self.workflow("sync-release.yml")
        reconcile = sync[sync.index("  reconcile:\n"):sync.index("      - name: Check out trusted website default branch", sync.index("  reconcile:\n"))]
        self.assertIn("WRITER_MUTATION_RECHECK_ROOT: ${{ github.workspace }}/release-writer-mutation-recheck", reconcile)
        self.assertIn("WRITER_PRE_ENABLE_RECHECK_ROOT: ${{ github.workspace }}/release-writer-pre-enable-recheck", reconcile)
        self.assertIn('rm -rf "$RESOLVE_ROOT" "$RECHECK_ROOT" "$WRITER_MUTATION_RECHECK_ROOT" "$WRITER_PRE_ENABLE_RECHECK_ROOT"', sync)

    def test_writer_final_enable_reauthorizes_after_final_release_observation(self) -> None:
        sync = self.workflow("sync-release.yml")
        start = sync.index('          latest = current_tuple(pre_enable_release)\n')
        end = sync.index('\n          print(json.dumps({"pr": pr_number', start)
        final_enable = sync[start:end]
        for invariant in (
            'require_tuple(latest, after_push, ("main_sha", "control_sha256", "bot_sha", "release"))',
            'final_policy = policy_decision(final_pr_data, final_reviews, "final-enable")',
            'review["commit_id"] == candidate and review["state"] in {"CHANGES_REQUESTED", "REQUEST_CHANGES"}',
            'not writer_auto_merge_authorized(final_policy)',
            'final_pull.get("mergeStateStatus") != "CLEAN"',
            'final_pull.get("autoMergeRequest") is not None',
            'mutation = """mutation($id:ID!,$head:GitObjectID!){enablePullRequestAutoMerge(input:{pullRequestId:$id,mergeMethod:SQUASH,expectedHeadOid:$head})',
        ):
            with self.subTest(invariant=invariant):
                self.assertIn(invariant, final_enable)
        self.assertLess(final_enable.index('final_policy = policy_decision'), final_enable.index('enablePullRequestAutoMerge'))
        self.assertIn('"variables": {"id": pull["id"], "head": candidate}', final_enable)

    def test_writer_provenance_status_is_authenticated_and_required_for_the_exact_head(self) -> None:
        sync = self.workflow("sync-release.yml")
        reviewer = self.workflow("review-release-sync-pr.yml")
        self.assertIn("permission-statuses: write", sync)
        self.assertIn('api("POST", f"/repos/{repository}/statuses/{candidate}", writer_token, {', sync)
        self.assertIn('"context": "release-sync/writer-provenance"', sync)
        self.assertIn('provenance["creator"].get("id") != writer_identity["id"]', sync)
        self.assertIn('def has_current_writer_provenance(head_sha: str) -> bool:', sync)
        self.assertIn('def has_current_writer_provenance(head_sha: str) -> bool:', reviewer)
        self.assertIn('current head lacks authenticated Writer-App provenance; human review required', reviewer)
        self.assertIn('current head lacks authenticated Writer-App provenance before Reviewer-App token mint', reviewer)

    def test_pages_observer_binds_workflow_runs_and_deployments_to_one_main_state(self) -> None:
        pages = self.workflow("post-pages-release-check.yml")
        for invariant in (
            "WORKFLOW_RUN_HEAD_SHA: ${{ github.event.workflow_run.head_sha }}",
            "WORKFLOW_RUN_HEAD_BRANCH: ${{ github.event.workflow_run.head_branch }}",
            "WORKFLOW_RUN_HEAD_REPOSITORY: ${{ github.event.workflow_run.head_repository.full_name }}",
            'test "$WORKFLOW_RUN_HEAD_SHA" = "$main_sha"',
            "Pages workflow_run deployed a stale main head",
            'git show "$main_sha:release-sync.json" > "$expected"',
            'test "$(git rev-parse origin/main)" = "$EXPECTED_MAIN_SHA"',
            'git show "$EXPECTED_MAIN_SHA:release-sync.json" > "$after_expected"',
            "main release-sync.json drifted during Pages deployment observation",
        ):
            with self.subTest(invariant=invariant):
                self.assertIn(invariant, pages)

    def test_human_and_fork_release_sync_prs_fall_back_without_reviewer_token_mint(self) -> None:
        reviewer = self.workflow("review-release-sync-pr.yml")
        self.assertIn('def human_fallback(reason: str) -> None:', reviewer)
        self.assertIn('"classification": "human-required"', reviewer)
        self.assertIn('"review_action": "none"', reviewer)
        self.assertIn('if not canonical_base or not canonical_head:', reviewer)
        self.assertIn('human_fallback("PR is not the canonical same-repository release-sync branch; human review required")', reviewer)
        self.assertNotIn("needs.classify.outputs.auto_merge == 'false'", reviewer)
        self.assertIn("needs.classify.outputs.review_action == 'dismiss'", reviewer)

    def test_bot_object_fallback_only_accepts_documented_unavailable_object(self) -> None:
        sync = self.workflow("sync-release.yml")
        opening = "          def documented_unavailable_bot_object(result: subprocess.CompletedProcess[str], sha: str) -> bool:\n"
        start = sync.index(opening)
        end = sync.index("\n          def fetch_and_probe_observed_bot", start)
        namespace: dict[str, Any] = {"subprocess": subprocess}
        exec(textwrap.dedent(sync[start:end]), namespace)
        classify = namespace["documented_unavailable_bot_object"]
        sha = "a" * 40
        self.assertTrue(classify(subprocess.CompletedProcess(["git"], 128, "", f"fatal: remote error: upload-pack: not our ref {sha}"), sha))
        self.assertTrue(classify(subprocess.CompletedProcess(["git"], 128, "", f"fatal: git upload-pack: not our ref {sha}"), sha))
        self.assertFalse(classify(subprocess.CompletedProcess(["git"], 128, "", f"fatal: not our ref {sha}"), sha))
        self.assertFalse(classify(subprocess.CompletedProcess(["git"], 1, "", f"fatal: remote error: upload-pack: not our ref {sha}"), sha))
        self.assertFalse(classify(subprocess.CompletedProcess(["git"], 128, "output", f"fatal: remote error: upload-pack: not our ref {sha}"), sha))
        self.assertIn("fetch_and_probe_observed_bot(observed_bot)", sync)
        self.assertIn("failed closed while fetching observed bot object", sync)
        self.assertIn("failed closed while probing fetched bot object", sync)
        self.assertNotIn("except subprocess.CalledProcessError:\n              reuse_existing = False", sync)

    def test_all_embedded_python_heredocs_compile(self) -> None:
        for workflow_name in (
            "sync-release.yml",
            "review-release-sync-pr.yml",
            "post-pages-release-check.yml",
            "validate-site.yml",
        ):
            lines = self.workflow(workflow_name).splitlines()
            index = 0
            heredoc_count = 0
            while index < len(lines):
                if "<<'PY'" not in lines[index]:
                    index += 1
                    continue
                start_line = index + 2
                index += 1
                body: list[str] = []
                while index < len(lines) and lines[index].strip() != "PY":
                    body.append(lines[index])
                    index += 1
                self.assertLess(index, len(lines), f"{workflow_name}:{start_line} has no PY terminator")
                source = textwrap.dedent("\n".join(body)) + "\n"
                compile(source, f"{workflow_name}:{start_line}", "exec")
                heredoc_count += 1
                index += 1
            self.assertGreater(heredoc_count, 0, f"{workflow_name} has no Python heredoc")

    def test_tokenless_release_tuple_validator_executes_with_runtime_imports(self) -> None:
        sync = self.workflow("sync-release.yml")
        step_start = sync.index("      - name: Capture tokenless main, control, bot, PR, and release tuple")
        heredoc_start = sync.index("          python3 - <<'PY'\n", step_start) + len("          python3 - <<'PY'\n")
        heredoc_end = sync.index("          PY\n", heredoc_start)
        heredoc = sync[heredoc_start:heredoc_end]
        imports = heredoc[:heredoc.index("\n          website =")]
        function_start = heredoc.index("          def exact_release_tuple")
        function_end = heredoc.index("\n          def git", function_start)
        namespace: dict[str, Any] = {}
        exec(textwrap.dedent(imports + "\n" + heredoc[function_start:function_end]), namespace)
        digest = "a" * 64
        value = {
            "release": {
                "assets": [
                    {"name": "gajae-release-packages-expected-v1.json", "digest": f"sha256:{digest}"},
                    {"name": "gajae-release-packages-v1.json", "digest": f"sha256:{digest}"},
                ],
                "id": 1,
                "tag": "v1.2.3",
                "published_at": "2026-07-12T04:00:25Z",
                "peeled_commit_sha": "b" * 40,
            },
            "source_checkout": {"package_evidence_asset_sha256": digest},
        }
        observed = namespace["exact_release_tuple"](value, "fixture")
        self.assertEqual(observed["expected_evidence_asset_sha256"], f"sha256:{digest}")
        self.assertEqual(observed["verified_final_evidence_sha256"], digest)


def suite_for(case: str) -> unittest.TestSuite:
    loader = unittest.defaultTestLoader
    if case == "resolver-generator":
        return loader.loadTestsFromTestCase(ResolverGeneratorFixture)
    if case == "ownership-review-cas":
        return loader.loadTestsFromTestCase(ReleaseSyncFixture)
    if case == "workflow-contracts":
        return loader.loadTestsFromTestCase(WorkflowContractFixture)
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(ResolverGeneratorFixture))
    suite.addTests(loader.loadTestsFromTestCase(ReleaseSyncFixture))
    suite.addTests(loader.loadTestsFromTestCase(WorkflowContractFixture))
    return suite


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=("resolver-generator", "ownership-review-cas", "workflow-contracts", "all"), default="all")
    args = parser.parse_args()
    result = unittest.TextTestRunner(verbosity=2).run(suite_for(args.case))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
