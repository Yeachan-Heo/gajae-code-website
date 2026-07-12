#!/usr/bin/env python3
"""Retired compatibility entrypoint for the unsafe broad version rewriter."""
from __future__ import annotations

raise SystemExit(
    "sync-product-version.py is retired: broad semantic-version replacement is unsafe. "
    "Use resolve-release.py followed by sync-release.py with its detached resolver sidecar."
)
