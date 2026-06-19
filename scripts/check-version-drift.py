#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_RE = re.compile(r"(v?)(?P<version>\d+\.\d+\.\d+)")


def read_product_version(source: Path) -> str:
    module_path = ROOT / "scripts" / "sync-product-version.py"
    spec = importlib.util.spec_from_file_location("sync_product_version", module_path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"could not load {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.read_product_version(source)


def find_drift(source: Path) -> tuple[str, list[str]]:
    product_version = read_product_version(source)
    targets = [ROOT / "index.html", *sorted((ROOT / "docs").glob("*.html"))]
    drift: list[str] = []
    for target in targets:
        text = target.read_text()
        for m in VERSION_RE.finditer(text):
            if m.group("version") != product_version:
                drift.append(
                    f"{target.relative_to(ROOT)} has {m.group(0)}, product source has v{product_version}"
                )
    return product_version, drift


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: check-version-drift.py <gajae-code checkout>")
    source = Path(sys.argv[1]).resolve()
    product_version, drift = find_drift(source)
    if drift:
        raise SystemExit("website version drift:\n" + "\n".join(drift))
    print(f"website version matches product source: v{product_version}")


if __name__ == "__main__":
    main()
