#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BADGE_RE = re.compile(r"hero__badge[^>]*>[^<]*v(?P<version>\d+\.\d+\.\d+)")


def read_product_version(source: Path) -> str:
    module_path = ROOT / "scripts" / "sync-product-version.py"
    spec = importlib.util.spec_from_file_location("sync_product_version", module_path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"could not load {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.read_product_version(source)


def read_website_version() -> str:
    text = (ROOT / "index.html").read_text()
    match = BADGE_RE.search(text)
    if not match:
        raise SystemExit("could not find hero badge product version in index.html")
    return match.group("version")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: check-version-drift.py <gajae-code checkout>")
    source = Path(sys.argv[1]).resolve()
    product_version = read_product_version(source)
    website_version = read_website_version()
    if website_version != product_version:
        raise SystemExit(
            f"website version drift: index.html has v{website_version}, product source has v{product_version}"
        )
    print(f"website version matches product source: v{website_version}")


if __name__ == "__main__":
    main()
