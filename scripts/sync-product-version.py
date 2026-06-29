#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_RE = re.compile(r"v(?P<version>\d+\.\d+\.\d+)")


def read_product_version(source: Path) -> str:
    candidates = [
        source / "packages" / "gajae-code" / "package.json",
        source / "packages" / "coding-agent" / "package.json",
        source / "package.json",
    ]
    for package_json in candidates:
        if not package_json.exists():
            continue
        data = json.loads(package_json.read_text())
        version = data.get("version")
        if isinstance(version, str):
            return version
        catalog_version = data.get("workspaces", {}).get("catalog", {}).get("@gajae-code/coding-agent")
        if isinstance(catalog_version, str):
            return catalog_version
    raise SystemExit(f"could not find product version under {source}")


def sync_version(version: str) -> list[Path]:
    changed: list[Path] = []
    targets = [ROOT / "index.html", ROOT / "README.md", *sorted((ROOT / "docs").glob("*.html"))]
    for target in targets:
        if not target.exists():
            continue
        before = target.read_text()
        after = VERSION_RE.sub(f"v{version}", before)
        if after != before:
            target.write_text(after)
            changed.append(target)
    return changed


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: sync-product-version.py <gajae-code checkout>")
    source = Path(sys.argv[1]).resolve()
    version = read_product_version(source)
    changed = sync_version(version)
    if changed:
        print(f"website product version updated to v{version} in:")
        for path in changed:
            print(f"- {path.relative_to(ROOT)}")
    else:
        print(f"website product version already current: v{version}")


if __name__ == "__main__":
    main()
