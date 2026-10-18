"""Validate the exact manual publish body for current and older Dolly clients."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dolly import __version__
from dolly.release_notes import parse_release_notes


def validate_publish_body(body: str, version: str) -> list[dict[str, str]]:
    version = version.removeprefix("v")
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    heading, marker = f"### Deadlock Dolly v{version}", f"**{version}**"
    if not lines or lines[0] != heading:
        raise ValueError(f"Start the publish body with {heading}")
    # .51-.54 clients cannot read a plain version heading. Keep their marker
    # before any bullets or prose, even though newer parsers accept the heading.
    if len(lines) < 2 or lines[1] != marker:
        raise ValueError(f"Keep {marker} directly below the heading so older Dolly clients show highlights")
    entries = parse_release_notes(body, version)
    if not 2 <= len(entries) <= 4:
        raise ValueError("The publish body must contain two to four supported Before/After highlights")
    # In the older reader every plain heading ends the preview, including one
    # naming this version. Neutralize those headings before using the shared
    # bounded bullet grammar; exact bold headings retain their original meaning.
    legacy_body = "\n".join(
        "# Release section" if re.match(r"\s*#{1,6}(?:\s|$)", line)
        and not re.fullmatch(r"\s*#{1,6}\s+\*\*[^*]+\*\*\s*", line) else line
        for line in body.splitlines())
    if parse_release_notes(legacy_body, version) != entries:
        raise ValueError("Older Dolly clients cannot read the same highlights; keep them directly below the bold version line")
    return entries


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("body", type=Path, nargs="?", help="Exact text to paste; defaults to this version's release notes")
    parser.add_argument("--version", default=__version__)
    args = parser.parse_args(argv)
    path = args.body or ROOT / "docs" / f"RELEASE_NOTES_{args.version.removeprefix('v')}.md"
    try:
        entries = validate_publish_body(path.read_text(encoding="utf-8-sig"), args.version)
    except (OSError, ValueError) as error:
        print(f"Release highlights check failed: {error}", file=sys.stderr)
        return 1
    print(f"Validated {len(entries)} release highlights, including the older-client version marker: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
