#!/usr/bin/env python3
"""Static validation for the marker-scoped release website."""
from __future__ import annotations

from html.parser import HTMLParser

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYNC_PATH = ROOT / "scripts" / "sync-release.py"
REQUIRED_ASSETS = (
    "assets/hero.png",
    "assets/character.png",
    "assets/telegram-mobile-hero.png",
    "css/styles.css",
    "js/main.js",
    "docs/style.css",
)

spec = importlib.util.spec_from_file_location("release_sync_contract", SYNC_PATH)
if spec is None or spec.loader is None:
    raise SystemExit(f"could not load release synchronization contract from {SYNC_PATH}")
sync = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = sync
spec.loader.exec_module(sync)


class PreCodeStructureParser(HTMLParser):
    """Reject unmatched pre/code tags without changing HTML rendering semantics."""

    def __init__(self, relative_path: str) -> None:
        super().__init__()
        self.relative_path = relative_path
        self.open_tags: list[tuple[str, int]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"pre", "code"}:
            self.open_tags.append((tag, self.getpos()[0]))

    def handle_endtag(self, tag: str) -> None:
        if tag not in {"pre", "code"}:
            return
        line = self.getpos()[0]
        if not self.open_tags:
            sync.fail(f"{self.relative_path}:{line} has unmatched closing <{tag}>")
        opened_tag, _opened_line = self.open_tags[-1]
        if opened_tag != tag:
            sync.fail(
                f"{self.relative_path}:{line} has unmatched closing <{tag}>; expected </{opened_tag}>"
            )
        self.open_tags.pop()

    def validate(self) -> None:
        if self.open_tags:
            tag, line = self.open_tags[-1]
            sync.fail(f"{self.relative_path}:{line} has unmatched opening <{tag}>")


def validate_pre_code_structure(relative_path: str, text: str) -> None:
    parser = PreCodeStructureParser(relative_path)
    parser.feed(text)
    parser.close()
    parser.validate()


def main() -> None:
    try:
        for asset in REQUIRED_ASSETS:
            path = ROOT / asset
            if not path.is_file():
                sync.fail(f"missing required static asset {asset}")
        state = sync.validate_static_release_site(ROOT)
        for relative_path in sync.REQUIRED_REGIONS:
            text = (ROOT / relative_path).read_text(encoding="utf-8")
            validate_pre_code_structure(relative_path, text)
    except sync.ReleaseSyncError as exc:
        raise SystemExit(f"site validation failed: {exc}") from None
    print(
        f"validated {len(sync.REQUIRED_REGIONS)} HTML files, static assets, "
        f"and release state {state['release']['tag']} ({state['release']['id']})"
    )


if __name__ == "__main__":
    main()
