"""verify_feeds.py — confirm every Phase-N RSS URL is live and parseable.

Run this from your Windows PowerShell (which has real internet):

    cd D:\\MCA\\NewsLens\\backend
    python scripts\\verify_feeds.py                # phase_1 by default
    python scripts\\verify_feeds.py --phase phase_1 --phase phase_2

For each outlet: HTTP GETs the RSS URL, parses with feedparser, prints
status, byte count, entry count, and the newest entry's headline.

Exit code 0 if every feed returned 200 with ≥1 entry, else 1.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make src.* importable when running from backend/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import feedparser  # noqa: E402
import httpx        # noqa: E402

from src.ingestion.outlets import load_outlets  # noqa: E402

USER_AGENT = "NewsLens/0.1 (MCA project; +https://github.com/newslens/newslens) python-httpx"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase", action="append", dest="phases", default=None)
    ap.add_argument("--timeout", type=float, default=20.0)
    args = ap.parse_args()

    phases = args.phases or ["phase_1"]
    outlets = load_outlets(phases)
    if not outlets:
        print(f"FAIL: no outlets found for phases={phases}")
        return 1

    failures = 0
    print(f"{'slug':<18} {'HTTP':<6} {'bytes':<8} {'items':<6} first_headline")
    print("-" * 100)

    with httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
        follow_redirects=True,
        timeout=args.timeout,
    ) as client:
        for outlet in outlets:
            try:
                resp = client.get(outlet.rss_url)
            except Exception as exc:
                print(f"{outlet.slug:<18} ERR    {type(exc).__name__}: {exc}")
                failures += 1
                continue

            parsed = feedparser.parse(resp.content) if resp.status_code == 200 else None
            items = len(parsed.entries) if parsed else 0
            first_headline = ""
            if parsed and parsed.entries:
                first_headline = (parsed.entries[0].get("title") or "")[:60]

            status_ok = resp.status_code == 200 and items > 0
            marker = " " if status_ok else "!"
            print(f"{marker}{outlet.slug:<17} {resp.status_code:<6} "
                  f"{len(resp.content):<8} {items:<6} {first_headline}")
            if not status_ok:
                failures += 1

    print()
    if failures == 0:
        print(f"PASS: all {len(outlets)} feeds live and parseable")
        return 0
    print(f"FAIL: {failures}/{len(outlets)} feeds unusable — update outlets.yaml")
    return 1


if __name__ == "__main__":
    sys.exit(main())
