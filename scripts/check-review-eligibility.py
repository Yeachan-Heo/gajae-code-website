#!/usr/bin/env python3
"""Classify a release-sync PR without executing candidate code.

The caller must run this file from a trusted default-branch checkout.  Candidate
files are read as Git objects by the trusted ownership checker; an event fixture is
only sanitized API data, never an authority for repository contents.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

CANONICAL_REPOSITORY = "Yeachan-Heo/gajae-code-website"
BOT_BRANCH = "automation/release-sync"


class EventError(ValueError):
    """The trusted workflow supplied an incomplete or inconsistent API snapshot."""


def _load_trusted_ownership(trusted_root: Path) -> Any:
    script = (trusted_root / "scripts" / "check-generated-ownership.py").resolve()
    if not script.is_file():
        raise EventError(f"trusted ownership checker is missing: {script}")
    spec = importlib.util.spec_from_file_location("trusted_generated_ownership", script)
    if spec is None or spec.loader is None:
        raise EventError("could not load trusted ownership checker")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EventError(f"duplicate event key: {key}")
        result[key] = value
    return result


def _no_float(_value: str) -> None:
    raise EventError("event floats are forbidden")




def _read_event(path: Path) -> dict[str, Any]:
    try:
        event = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs, parse_float=_no_float)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, EventError) as exc:
        raise EventError(f"invalid event JSON: {exc}") from exc
    if not isinstance(event, dict):
        raise EventError("event JSON must be an object")
    return event


def _require_keys(value: dict[str, Any], keys: set[str], description: str) -> None:
    if set(value) != keys:
        raise EventError(
            f"{description} keys must be exact; missing={sorted(keys - set(value))}, "
            f"extra={sorted(set(value) - keys)}"
        )


def _string(value: Any, description: str) -> str:
    if not isinstance(value, str) or not value:
        raise EventError(f"{description} must be a non-empty string")
    return value


def _positive_int(value: Any, description: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise EventError(f"{description} must be a positive integer")
    return value


def _app(value: Any, description: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EventError(f"{description} must be an object")
    _require_keys(value, {"id", "slug"}, description)
    return {"id": _positive_int(value["id"], f"{description}.id"), "slug": _string(value["slug"], f"{description}.slug")}


def _review(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EventError("review must be an object")
    _require_keys(value, {"app", "commit_id", "id", "state"}, "review")
    state = _string(value["state"], "review.state")
    if state not in {"APPROVED", "CHANGES_REQUESTED", "COMMENTED", "DISMISSED", "REQUEST_CHANGES"}:
        raise EventError("review.state is unsupported")
    app = value["app"]
    if app is not None:
        app = _app(app, "review.app")
    return {
        "app": app,
        "commit_id": _string(value["commit_id"], "review.commit_id"),
        "id": _positive_int(value["id"], "review.id"),
        "state": state,
    }


def parse_event(event: dict[str, Any]) -> dict[str, Any]:
    _require_keys(event, {"pull_request", "repository", "reviews", "transaction"}, "event")
    repository = _string(event["repository"], "event.repository")
    pr = event["pull_request"]
    if not isinstance(pr, dict):
        raise EventError("event.pull_request must be an object")
    _require_keys(
        pr,
        {"base_sha", "draft", "head_repository", "head_ref", "head_sha", "number", "writer_app"},
        "event.pull_request",
    )
    if not isinstance(pr["draft"], bool):
        raise EventError("event.pull_request.draft must be a boolean")
    transaction = event["transaction"]
    if not isinstance(transaction, dict):
        raise EventError("event.transaction must be an object")
    _require_keys(transaction, {"base_sha", "control_sha256", "head_sha"}, "event.transaction")
    reviews = event["reviews"]
    if not isinstance(reviews, list):
        raise EventError("event.reviews must be an array")
    parsed = {
        "repository": repository,
        "pull_request": {
            "base_sha": _string(pr["base_sha"], "event.pull_request.base_sha"),
            "draft": pr["draft"],
            "head_repository": _string(pr["head_repository"], "event.pull_request.head_repository"),
            "head_ref": _string(pr["head_ref"], "event.pull_request.head_ref"),
            "head_sha": _string(pr["head_sha"], "event.pull_request.head_sha"),
            "number": _positive_int(pr["number"], "event.pull_request.number"),
            "writer_app": _app(pr["writer_app"], "event.pull_request.writer_app"),
        },
        "reviews": [_review(review) for review in reviews],
        "transaction": {
            "base_sha": _string(transaction["base_sha"], "event.transaction.base_sha"),
            "control_sha256": _string(transaction["control_sha256"], "event.transaction.control_sha256"),
            "head_sha": _string(transaction["head_sha"], "event.transaction.head_sha"),
        },
    }
    return parsed


def _identity(slug: str | None, app_id: str | None, description: str) -> dict[str, Any]:
    if not slug:
        raise EventError(f"missing {description} app slug")
    try:
        parsed_id = int(app_id or "")
    except ValueError as exc:
        raise EventError(f"invalid {description} app id") from exc
    if parsed_id <= 0:
        raise EventError(f"invalid {description} app id")
    return {"slug": slug, "id": parsed_id}


def _enabled(value: str | None) -> bool:
    if value is None:
        raise EventError("missing RELEASE_SYNC_AUTO_REVIEW_ENABLED")
    if value == "true":
        return True
    if value == "false":
        return False
    raise EventError("RELEASE_SYNC_AUTO_REVIEW_ENABLED must be literal true or false")


def _same_app(left: dict[str, Any] | None, right: dict[str, Any]) -> bool:
    return left is not None and left["id"] == right["id"] and left["slug"] == right["slug"]


def _review_status(reviews: list[dict[str, Any]], reviewer: dict[str, Any], head_sha: str) -> tuple[str, bool]:
    approvals = sorted(
        (
            review
            for review in reviews
            if _same_app(review["app"], reviewer) and review["state"] == "APPROVED"
        ),
        key=lambda review: review["id"],
    )
    if not approvals:
        return "missing", False
    latest = approvals[-1]
    if latest["commit_id"] == head_sha:
        return "current", True
    return "stale", True


def _has_request_changes(reviews: list[dict[str, Any]], head_sha: str) -> bool:
    return any(
        review["state"] in {"CHANGES_REQUESTED", "REQUEST_CHANGES"} and review["commit_id"] == head_sha
        for review in reviews
    )


def _output(
    classification: str,
    reason: str,
    review_action: str,
    reviewer_status: str,
    auto_merge: bool,
    pr_number: int | None = None,
) -> str:
    value: dict[str, Any] = {
        "auto_merge": auto_merge,
        "classification": classification,
        "eligible": classification == "bot-generated",
        "reason": reason,
        "review_action": review_action,
        "reviewer_approval": reviewer_status,
        "token_mint_required": review_action in {"approve", "dismiss"},
    }
    if pr_number is not None:
        value["pr_number"] = pr_number
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def classify(
    repository: Path,
    trusted_root: Path,
    base_sha: str,
    head_sha: str,
    event_path: Path,
    writer: dict[str, Any],
    reviewer: dict[str, Any],
    auto_review_enabled: bool,
) -> tuple[int, str]:
    ownership = _load_trusted_ownership(trusted_root)
    event = parse_event(_read_event(event_path))
    pr = event["pull_request"]
    if writer == reviewer:
        raise EventError("writer and reviewer App identities must differ")
    if event["repository"] != CANONICAL_REPOSITORY:
        raise EventError("event repository is not the canonical production website repository")
    if pr["base_sha"] != base_sha or pr["head_sha"] != head_sha:
        raise EventError("event PR tuple does not match requested base/head SHAs")
    if event["transaction"]["base_sha"] != base_sha or event["transaction"]["head_sha"] != head_sha:
        raise EventError("event transaction tuple does not match requested base/head SHAs")
    if ownership.SHA256_RE.fullmatch(event["transaction"]["control_sha256"]) is None:
        raise EventError("event transaction control_sha256 is invalid")

    reviewer_status, reviewer_approval_exists = _review_status(event["reviews"], reviewer, head_sha)
    reasons: list[str] = []
    if not auto_review_enabled:
        reasons.append("automatic App review is disabled")
    if pr["draft"]:
        reasons.append("PR is a draft")
    if pr["head_repository"] != CANONICAL_REPOSITORY:
        reasons.append("PR head repository is not canonical")
    if pr["head_ref"] != BOT_BRANCH:
        reasons.append("PR head branch is not the release-sync bot branch")
    if pr["writer_app"] != writer:
        reasons.append("PR author is not the exact Writer App")

    ownership_result: dict[str, Any] | None = None

    try:
        ownership_result = ownership.validate_generated_change(repository, base_sha, head_sha, trusted_root)
    except ownership.CandidateError as exc:
        reasons.append(f"generated ownership rejected: {exc}")
    except ownership.ProtocolError as exc:
        raise EventError(f"generated ownership verification failed: {exc}") from exc
    if ownership_result is not None and event["transaction"]["control_sha256"] != ownership_result["control_sha256"]:
        raise EventError("event control digest does not match trusted base control bytes")

    if reasons:
        action = "dismiss" if reviewer_approval_exists else "none"
        return 0, _output(
            "human-required",
            "; ".join(reasons),
            action,
            reviewer_status,
            False,
            pr["number"],
        )

    action = "none" if reviewer_status == "current" else "approve"
    return 0, _output(
        "bot-generated",
        "eligible generated Writer-App PR",
        action,
        reviewer_status,
        reviewer_status == "current" and not _has_request_changes(event["reviews"], head_sha),
        pr["number"],
    )


def _self_test() -> int:
    test_file = Path(__file__).with_name("test-release-sync.py")
    completed = __import__("subprocess").run(
        [sys.executable, str(test_file), "--case", "ownership-review-cas"], check=False
    )
    return completed.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trusted-root", type=Path)
    parser.add_argument("--base-sha")
    parser.add_argument("--head-sha")
    parser.add_argument("--event-json", type=Path)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--writer-app-slug", default=os.environ.get("RELEASE_SYNC_WRITER_APP_SLUG"))
    parser.add_argument("--writer-app-id", default=os.environ.get("RELEASE_SYNC_WRITER_APP_ID_PUBLIC"))
    parser.add_argument("--reviewer-app-slug", default=os.environ.get("RELEASE_SYNC_POLICY_REVIEWER_APP_SLUG"))
    parser.add_argument("--reviewer-app-id", default=os.environ.get("RELEASE_SYNC_POLICY_REVIEWER_APP_ID_PUBLIC"))
    parser.add_argument("--auto-review-enabled", default=os.environ.get("RELEASE_SYNC_AUTO_REVIEW_ENABLED"))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return _self_test()
    if not all((args.trusted_root, args.base_sha, args.head_sha, args.event_json)):
        parser.error("--trusted-root, --base-sha, --head-sha, and --event-json are required")
    try:
        writer = _identity(args.writer_app_slug, args.writer_app_id, "Writer")
        reviewer = _identity(args.reviewer_app_slug, args.reviewer_app_id, "Reviewer")
        status, output = classify(
            args.repository.resolve(),
            args.trusted_root.resolve(),
            args.base_sha,
            args.head_sha,
            args.event_json.resolve(),
            writer,
            reviewer,
            _enabled(args.auto_review_enabled),
        )
    except EventError as exc:
        print(_output("error", str(exc), "none", "unknown", False))
        print(f"review eligibility rejected: {exc}", file=sys.stderr)
        return 1
    print(output)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
