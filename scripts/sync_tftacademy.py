"""
TFT Academy Tier-List Sync (CLI)

Pulls the comp tier list from tftacademy.com and writes the result to
`assets/tftacademy_cache.json` — the same cache the live backend reads
on startup.

This is a thin CLI on top of `backend/tftacademy_live.py`. The backend
also auto-refreshes on startup and on each WebSocket connection, so this
script is for ad-hoc manual use:

    python scripts/sync_tftacademy.py            # show what would change
    python scripts/sync_tftacademy.py --write    # update the cache file

The augments and items pages on tftacademy.com are JavaScript-rendered,
so this script only handles comps. Augments referenced by the comp tier
list ("Aura Farming", "Portable Forge", etc.) are baked into
`AUGMENT_RATINGS` in backend/game_data.py — edit that dict by hand to
add more.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Make backend imports work whether the script is run from the repo root
# or from inside scripts/.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from tftacademy_live import (   # noqa: E402  (after sys.path mutation)
    COMPS_URL,
    parse_comps,
    parse_patch,
    refresh_async,
    _fetch_html_blocking,
    _seed_lookup_from_existing,
    _merge_scraped_into_full,
)


# ── Reporting ─────────────────────────────────────────────────────────────────

def print_summary(entries: list[dict], patch: str | None) -> None:
    """Print a tier-grouped summary of what we scraped."""
    by_tier: dict[str, list[str]] = {}
    for e in entries:
        by_tier.setdefault(e["tier"], []).append(e["name"])
    print(f"Source: {COMPS_URL}")
    print(f"Patch:  {patch or '(unknown)'}")
    print(f"Total:  {len(entries)} comps")
    print()
    for tier in ("S", "A", "B", "C", "X"):
        names = by_tier.get(tier, [])
        if not names:
            continue
        print(f"  {tier}-Tier ({len(names)})")
        for name in names:
            print(f"    - {name}")
        print()


def print_augments_note() -> None:
    """Explain the augments-page situation."""
    print("─" * 70)
    print("Augments page status")
    print("─" * 70)
    print(
        "The TFT Academy augments tier list at"
        f"\n    https://tftacademy.com/tierlist/augments"
        "\nis JavaScript-rendered. urllib cannot extract the augment data from"
        "\nthe raw HTML."
        "\n"
        "\nAugments referenced by the scraped comps page (Aura Farming,"
        "\nPortable Forge, Bonk, etc.) are already baked into AUGMENT_RATINGS"
        "\nin backend/game_data.py. To add full augment coverage, edit that"
        "\ndict by hand — the schema is {augment_name: {\"rating\": \"...\","
        "\n\"tip\": \"...\"}}."
    )


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--write",
        action="store_true",
        help="Update assets/tftacademy_cache.json with the scraped data.",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="Bypass debounce and re-scrape even if a recent cache exists.",
    )
    args = ap.parse_args()

    print(f"Fetching {COMPS_URL}…")

    if args.write:
        # Use the same code path the backend uses, so behavior matches.
        result = asyncio.run(refresh_async(force=args.force, debounce_seconds=0))
        if result["error"]:
            print(f"!! Refresh failed: {result['error']}", file=sys.stderr)
            return 1
        if result["refreshed"]:
            print(f"Wrote new cache (patch={result['patch']}).")
        elif result["checked"]:
            print(f"Cache already current (patch={result['patch']}).")
        else:
            print("Cache was within debounce window — no fetch performed.")
        print()
        print_augments_note()
        return 0

    # Dry-run: scrape and print, don't touch the cache.
    try:
        html = _fetch_html_blocking(COMPS_URL)
    except Exception as e:
        print(f"!! Fetch failed: {e}", file=sys.stderr)
        return 1

    patch = parse_patch(html)
    scraped = parse_comps(html)
    if not scraped:
        print(
            "!! No comps parsed — the page layout may have changed.",
            file=sys.stderr,
        )
        print(
            "   Inspect the HTML and adjust parse_comps() in "
            "backend/tftacademy_live.py."
        )
        return 1

    merged = _merge_scraped_into_full(scraped, _seed_lookup_from_existing())
    print_summary(merged, patch)
    print("─" * 70)
    print("Re-run with --write to update assets/tftacademy_cache.json.")
    print()
    print_augments_note()
    return 0


if __name__ == "__main__":
    sys.exit(main())
