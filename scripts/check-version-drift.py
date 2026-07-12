#!/usr/bin/env python3
"""Fail closed when committed release markers or state drift from a resolver sidecar."""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYNC_PATH = ROOT / "scripts" / "sync-release.py"
spec = importlib.util.spec_from_file_location("release_sync_contract", SYNC_PATH)
if spec is None or spec.loader is None:
    raise SystemExit(f"could not load release synchronization contract from {SYNC_PATH}")
sync = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = sync
spec.loader.exec_module(sync)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate release state and generated markers against a detached resolver sidecar.")
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--source-dir", "--source", dest="source_dir", type=Path)
    parser.add_argument("--website-root", type=Path, default=ROOT)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        if args.snapshot is not None or args.source_dir is not None or args.website_root != ROOT:
            parser.error("--self-test cannot be combined with release inputs")
    elif args.snapshot is None or args.source_dir is None:
        parser.error("--snapshot and --source-dir are required")
    return args


def main() -> None:
    args = parse_args()
    try:
        if args.self_test:
            sync.self_test()
            print("check-version-drift self-test passed")
            return
        root = sync.require_real_directory(args.website_root, "website root")
        state = sync.validate_static_release_site(root)
        # synchronize(..., check=True) verifies the detached HEAD/tag, source
        # manifests, final evidence sidecar, exact changelog rendering, every
        # owned region, state digest, and control gate without mutating files.
        sync.synchronize(args.snapshot, args.source_dir, root, check=True)
    except sync.ReleaseSyncError as exc:
        raise SystemExit(f"release version/state drift: {exc}") from None
    print(
        "website release state matches verified source sidecar: "
        f"{state['release']['tag']} ({state['release']['id']})"
    )


if __name__ == "__main__":
    main()
