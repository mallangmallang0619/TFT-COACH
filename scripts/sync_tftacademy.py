"""
TFT Academy Tier-List Sync (CLI)

Pulls the comp tier list from tftacademy.com and writes the result to
`assets/tftacademy_cache.json` — the same cache the live backend reads
on startup.

This is a thin CLI on top of `backend/tftacademy_live.py`. The backend
also auto-refreshes on startup and on each WebSocket connection, so this
script is for ad-hoc manual use:

    python scripts/sync_tftacademy.py                # dry-run listing
    python scripts/sync_tftacademy.py --write        # write listing cache
    python scripts/sync_tftacademy.py --write --details
        # also fetch each comp's detail page (units, items, augments).
        # Sequential + rate-limited so it can take ~30s on a cold cache.
    python scripts/sync_tftacademy.py --detail set-17-dark-star
        # dry-run a single comp detail page and print parsed output.

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
    COMP_DETAIL_URL_TEMPLATE,
    COMPS_URL,
    parse_comp_detail,
    parse_comps,
    parse_patch,
    refresh_async,
    refresh_details_async,
    _fetch_comp_detail_blocking,
    _fetch_html_blocking,
    _seed_lookup_from_existing,
    _merge_scraped_into_full,
)


# ── Reporting ─────────────────────────────────────────────────────────────────

def print_summary(entries: list[dict], patch: str | None) -> None:
    """Print a tier-grouped summary of what we scraped."""
    by_tier: dict[str, list[dict]] = {}
    for e in entries:
        by_tier.setdefault(e["tier"], []).append(e)
    print(f"Source: {COMPS_URL}")
    print(f"Patch:  {patch or '(unknown)'}")
    print(f"Total:  {len(entries)} comps")
    print()
    for tier in ("S", "A", "B", "C", "X"):
        bucket = by_tier.get(tier, [])
        if not bucket:
            continue
        print(f"  {tier}-Tier ({len(bucket)})")
        for entry in bucket:
            slug = entry.get("slug", "?")
            print(f"    - {entry['name']:<28} [{slug}]")
        print()


def print_detail(slug: str, detail: dict) -> None:
    """Pretty-print one parsed comp detail."""
    print(f"=== {slug} ===")
    mc = detail.get("main_champion")
    if mc:
        print(f"Carry:      {mc['name']} ({mc['cost']}-cost)")
    if "difficulty" in detail:
        print(f"Difficulty: {detail['difficulty']}")
    units = detail.get("units") or []
    print(f"Final comp ({len(units)} units):")
    for u in units:
        items = ", ".join(i["name"] for i in u["items"]) or "(none)"
        board = u["boardIndex"] if u["boardIndex"] is not None else "?"
        print(f"    hex {board:>2}  {u['name']:<14} {u['stars']}*  items: {items}")
    early = detail.get("early_comp") or []
    if early:
        print("Early comp:")
        print("    " + ", ".join(u["name"] for u in early))
    augs = detail.get("augments") or []
    if augs:
        print("Augments:")
        print("    " + ", ".join(a["name"] for a in augs))
    car = detail.get("carousel") or []
    if car:
        print("Carousel priority:")
        print("    " + " > ".join(c["name"] for c in car))
    tip = detail.get("tip")
    if tip:
        print(f"Tip: {tip}")
    print()


def print_augments_note() -> None:
    """Explain the augments-page situation."""
    print("-" * 70)
    print("Augments page status")
    print("-" * 70)
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

def _run_detail_dry(slug: str) -> int:
    """Fetch and parse a single comp detail page; print the result."""
    url = COMP_DETAIL_URL_TEMPLATE.format(slug=slug)
    print(f"Fetching {url}…")
    try:
        html = _fetch_comp_detail_blocking(slug)
    except Exception as e:
        print(f"!! Fetch failed: {e}", file=sys.stderr)
        return 1
    detail = parse_comp_detail(html)
    if not detail:
        print(
            "!! No hydration blob found — page may have changed.",
            file=sys.stderr,
        )
        return 1
    print_detail(slug, detail)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--write",
        action="store_true",
        help="Update assets/tftacademy_cache.json with the scraped data.",
    )
    ap.add_argument(
        "--details",
        action="store_true",
        help=(
            "After the listing refresh, fetch each comp's detail page and "
            "store units/items/augments inline in the cache. Sequential and "
            "rate-limited — ~30s on a cold cache. Requires --write."
        ),
    )
    ap.add_argument(
        "--detail",
        metavar="SLUG",
        help=(
            "Dry-run a single comp detail page (e.g. 'set-17-dark-star'). "
            "Prints the parsed output and exits without touching the cache."
        ),
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="Bypass debounce and re-scrape even if a recent cache exists.",
    )
    args = ap.parse_args()

    if args.detail:
        return _run_detail_dry(args.detail)

    if args.details and not args.write:
        print(
            "!! --details requires --write (it persists results to the cache).",
            file=sys.stderr,
        )
        return 2

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

        if args.details:
            print()
            print("Fetching per-comp details (rate-limited)…")
            det_result = asyncio.run(
                refresh_details_async(force=args.force, debounce_seconds=0)
            )
            print(
                f"Details: fetched={det_result['fetched']}, "
                f"skipped={det_result['skipped']}, "
                f"errors={len(det_result['errors'])}"
            )
            for err in det_result["errors"]:
                print(f"  !! {err}", file=sys.stderr)

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
    print("-" * 70)
    print("Re-run with --write to update assets/tftacademy_cache.json,")
    print("or --write --details to also fetch per-comp units/items.")
    print()
    print_augments_note()
    return 0


if __name__ == "__main__":
    sys.exit(main())
