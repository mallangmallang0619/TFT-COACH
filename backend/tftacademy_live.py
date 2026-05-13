"""
TFT Academy Live Sync


Keeps META_COMPS in sync with tftacademy.com without blocking the app.


Three integration points:
  - On import (sync, fast) load assets/tftacademy_cache.json into
   game_data.META_COMPS, if the cache
  exists and is newer than the
   hardcoded data.

  - On server startup (async) kick off `refresh_async()` once so
   the cache is checked when the
    backend boots.

  - On each new client connection also call `refresh_async()` — the
   function is debounced internally so
  this is safe to call from every
   WebSocket handshake.

Design notes:
  - urllib + asyncio.to_thread is intentional. Adding aiohttp/requests just
    for one URL is overkill; run_in_executor keeps stdlib-only.
  - The cache file is the source of truth at runtime. The hardcoded
    META_COMPS in game_data.py is the seed/fallback for first-run users.
  - Refreshes are debounced (default: at most once every 30 minutes) and
    serialized via an asyncio.Lock so concurrent client connections cannot
    trigger duplicate fetches.
    imma be honest, this is just a web scraper :^)
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import re
import time
import urllib.request
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ── Constants ─────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = PROJECT_ROOT / "assets" / "tftacademy_cache.json"

COMPS_URL = "https://tftacademy.com/tierlist/comps"
COMP_DETAIL_URL_TEMPLATE = "https://tftacademy.com/tierlist/comps/{slug}"
USER_AGENT = "TFT-Coach/1.0 (auto-sync; +https://github.com/yourname/tft-coach)"

# Don't fetch more often than this — TFT Academy updates at most once per
# patch (weekly-ish). Frequent fetches add nothing and are rude to the host.
DEFAULT_DEBOUNCE_SECONDS = 30 * 60   # 30 minutes
DEFAULT_DETAIL_RATE_LIMIT = 1.0       # seconds between per-comp detail fetches
HTTP_TIMEOUT_SECONDS = 12

# Tier letters TFT Academy uses; anything else gets dropped during parse.
_VALID_TIERS = ("S", "A", "B", "C", "X")


#  Module state 

_refresh_lock = asyncio.Lock()
_details_refresh_lock = asyncio.Lock()
_last_refresh_attempt_at: float = 0.0
_last_details_refresh_at: float = 0.0
_last_successful_patch: Optional[str] = None


# Cache I/O

def load_cache() -> Optional[dict]:
    """Return the parsed cache JSON, or None if the file is missing/corrupt."""
    if not CACHE_PATH.exists():
        return None
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"tftacademy cache unreadable ({e}); ignoring it")
        return None


def save_cache(data: dict) -> bool:
    """Persist a fresh tier-list snapshot to disk. Returns True on success."""
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return True
    except OSError as e:
        logger.warning(f"Could not write tftacademy cache: {e}")
        return False


#  Apply cache to game_data 

def apply_to_game_data(comps: list[dict]) -> None:
    """
    Replace `game_data.META_COMPS` (in place) with the supplied list.

    Mutating the list in place keeps every existing `from game_data import
    META_COMPS` reference live — no caller needs to re-import.
    """
    if not comps:
        return
    # Imported lazily to avoid an import cycle at module load.
    import game_data

    game_data.META_COMPS[:] = comps
    game_data.META_COMPS_BY_CARRY.clear()
    for entry in comps:
        carry = entry.get("carry")
        if carry:
            game_data.META_COMPS_BY_CARRY.setdefault(carry, []).append(entry)


#  HTML parsing 

# TFT Academy renders the patch number in two places: as a header label
# ("Patch 17.2B - Last Updated …") and as a field on the SvelteKit hydration
# blob (`patch:"17.2B"`). Match either form so we keep working through layout
# tweaks.
_PATCH_RE = re.compile(
    r"""(?:Patch\s+|patch:\s*["'])([0-9]+\.[0-9]+[a-zA-Z]?)""",
    re.IGNORECASE,
)

# Each comp-card link looks like:
#   <a href="/tierlist/comps/set17/dark-star">Dark Star</a>
# Tier sections wrap groups of these links and carry an `S-Tier`,
# `A-Tier`, etc. label. We walk the document linearly, remembering the
# most-recently-seen tier label and tagging every link found inside it.
_TIER_LABEL_RE = re.compile(
    r"""(?ix)
    (?:
        (?:[>\s\"\']|^)([SABCX])-?\s?[Tt]ier(?:[<\s\"\']|$)   # "S-Tier" / "S Tier"
        |
        data-tier\s*=\s*[\"']([SABCX])[\"']                    # data-tier="S"
        |
        \"tier\"\s*:\s*[\"']([SABCX])[\"']                     # "tier":"S"
    )
    """
)
# Listing-page anchors only carry an icon grid — no plain comp name in the
# `<a>` body. The slug itself is the stable identifier (e.g. set-17-dark-star
# → "Dark Star"), so we match on href only and derive the name from the slug.
_COMP_LINK_RE = re.compile(
    r"""href=["']/tierlist/comps/(?P<slug>[^"'/]+)["']""",
    re.IGNORECASE,
)
# Strip a leading "set-<N>-" (e.g. "set-17-", "set-13a-") from a slug.
_SET_PREFIX_RE = re.compile(r"^set-?\d+[a-z]?-", re.IGNORECASE)


def _slug_to_display_name(slug: str) -> str:
    """Convert 'set-17-dark-star' into a display name like 'Dark Star'."""
    base = _SET_PREFIX_RE.sub("", slug)
    return " ".join(part.capitalize() for part in base.split("-") if part)


def parse_patch(html: str) -> Optional[str]:
    """Pull the patch identifier (e.g., '17.2b') out of the page HTML."""
    m = _PATCH_RE.search(html)
    return m.group(1).lower() if m else None


def parse_comps(html: str) -> list[dict]:
    """
    Pull comp entries from the comps tier-list page HTML.

    Returns a list of {"name": str, "tier": str} entries in document order,
    de-duplicated by (name, tier).

    The page is server-rendered enough that the comp names appear in static
    HTML next to their tier headers — but the structure is not stable, so
    we deliberately favor a forgiving regex pass over a strict DOM parser.
    """
    # Build one combined iterator over both regexes so we can interleave
    # them in document order.
    tokens: list[tuple[int, str, object]] = []   # (pos, kind, value)
    for m in _TIER_LABEL_RE.finditer(html):
        tier = next((g for g in m.groups() if g), "")
        if tier:
            tokens.append((m.start(), "tier", tier.upper()))
    for m in _COMP_LINK_RE.finditer(html):
        slug = (m.group("slug") or "").strip()
        if not slug:
            continue
        name = _slug_to_display_name(slug)
        if name:
            tokens.append((m.start(), "comp", (name, slug)))
    tokens.sort(key=lambda t: t[0])

    current_tier = "?"
    seen_slugs: set[str] = set()
    entries: list[dict] = []
    for _, kind, value in tokens:
        if kind == "tier":
            if value in _VALID_TIERS:
                current_tier = value
        elif kind == "comp" and current_tier in _VALID_TIERS:
            name, slug = value
            # Dedupe by slug — the same comp may be linked multiple times on
            # the page (carry icon, "related", sidebar). The first occurrence
            # is under the correct tier header; later ones inherit whatever
            # tier marker last preceded them and would land in the wrong
            # bucket.
            if slug in seen_slugs:
                continue
            seen_slugs.add(slug)
            entries.append({"name": name, "tier": current_tier, "slug": slug})
    return entries


# ── Comp-detail parsing ───────────────────────────────────────────────────────
#
# Each comp's detail page (e.g. /tierlist/comps/set-17-dark-star) is server-
# rendered as a SvelteKit `__sveltekit_*` script with a JS object literal
# holding every field the page renders: finalComp, earlyComp, mainChampion,
# augments, augmentsTip, carousel, difficulty, etc. We pull what we need with
# targeted regexes against the relevant sub-array so we never have to evaluate
# the JS or run a headless browser.

# Strip a leading set-prefix like "TFT17_" or "TFT_Item_"/"TFT_Augment_".
_API_PREFIX_RE = re.compile(r"^TFT\d*(?:_(?:Item|Augment))?_")
# Insert a space at lower→upper transitions and letter→digit transitions, so
# "TahmKench" → "Tahm Kench" and "MakeshiftArmor1" → "Makeshift Armor 1".
_CAMEL_SPLIT_RE = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Za-z])(?=\d)")

# Unit entries inside finalComp/earlyComp. Field order is consistent on the
# pages we've seen, but we use a permissive shape to tolerate small changes:
# match one balanced {...} that starts with apiName, then pull individual
# fields out of the body separately.
_UNIT_ENTRY_RE = re.compile(r'\{apiName:"(?P<api>[^"]+)"(?P<body>[^{}]*?)\}')
_ITEMS_FIELD_RE = re.compile(r'items:\[([^\]]*)\]')
_BOARD_INDEX_RE = re.compile(r'boardIndex:(\d+)')
_STARS_RE = re.compile(r'stars:(\d+)')
_QUOTED_RE = re.compile(r'"([^"]+)"')

# Scalar fields at the top of the hydration blob.
_MAIN_CHAMPION_RE = re.compile(r'mainChampion:\{apiName:"([^"]+)",cost:(\d+)\}')
_DIFFICULTY_RE = re.compile(r'difficulty:"([^"]+)"')
# `augmentsTip` is a JS string that can contain escaped quotes and apostrophes.
_TIP_RE = re.compile(r'augmentsTip:"((?:[^"\\]|\\.)*)"')


def _human_name(api_name: str) -> str:
    """Turn an apiName like 'TFT17_TahmKench' into a human label ('Tahm Kench')."""
    stripped = _API_PREFIX_RE.sub("", api_name)
    return _CAMEL_SPLIT_RE.sub(" ", stripped)


def _extract_array_field(blob: str, field: str) -> Optional[str]:
    """
    Find `<field>:[` inside `blob` and return the body between the matching
    brackets (exclusive of the outer `[` and `]`). Respects nested arrays
    and double-quoted strings with backslash escapes. Returns None if the
    field is missing.
    """
    needle = field + ":["
    idx = blob.find(needle)
    if idx < 0:
        return None
    start = idx + len(needle) - 1   # position of the opening '['
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(blob)):
        c = blob[i]
        if escape:
            escape = False
            continue
        if in_string:
            if c == "\\":
                escape = True
            elif c == '"':
                in_string = False
            continue
        if c == '"':
            in_string = True
        elif c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return blob[start + 1:i]
    return None


def _parse_unit_entries(arr_body: str) -> list[dict]:
    """Pull {apiName, boardIndex, items, stars} entries out of one comp array."""
    units: list[dict] = []
    for m in _UNIT_ENTRY_RE.finditer(arr_body):
        api = m.group("api")
        # Placeholder used by TFT Academy for empty trait-emblem slots.
        if "FakeUnit" in api:
            continue
        body = m.group("body")

        items: list[dict] = []
        items_m = _ITEMS_FIELD_RE.search(body)
        if items_m:
            items = [
                {"apiName": s, "name": _human_name(s)}
                for s in _QUOTED_RE.findall(items_m.group(1))
            ]

        board_m = _BOARD_INDEX_RE.search(body)
        stars_m = _STARS_RE.search(body)
        units.append({
            "apiName": api,
            "name": _human_name(api),
            "boardIndex": int(board_m.group(1)) if board_m else None,
            "items": items,
            "stars": int(stars_m.group(1)) if stars_m else 1,
        })
    return units


def parse_comp_detail(html: str) -> Optional[dict]:
    """
    Pull units / items / augments / tip from a comp detail page.

    Returns a dict with any subset of:
      - units: list of final-comp units with apiName, name, boardIndex, items, stars
      - early_comp: list of early-game units
      - main_champion: {apiName, name, cost} (the comp's primary carry)
      - augments: list of {apiName, name}
      - carousel: list of {apiName, name} (carousel-priority items)
      - tip: the augments/playstyle tip text
      - difficulty: 'EASY' / 'MEDIUM' / 'HARD'

    Returns None if no SvelteKit hydration blob is present.
    """
    sk_idx = html.find("__sveltekit")
    if sk_idx < 0:
        return None
    blob = html[sk_idx:]

    detail: dict = {}

    final_str = _extract_array_field(blob, "finalComp")
    if final_str is not None:
        detail["units"] = _parse_unit_entries(final_str)

    early_str = _extract_array_field(blob, "earlyComp")
    if early_str is not None:
        detail["early_comp"] = _parse_unit_entries(early_str)

    augments_str = _extract_array_field(blob, "augments")
    if augments_str is not None:
        detail["augments"] = [
            {"apiName": api, "name": _human_name(api)}
            for api in (m.group(1) for m in re.finditer(r'apiName:"([^"]+)"', augments_str))
        ]

    carousel_str = _extract_array_field(blob, "carousel")
    if carousel_str is not None:
        detail["carousel"] = [
            {"apiName": api, "name": _human_name(api)}
            for api in (m.group(1) for m in re.finditer(r'apiName:"([^"]+)"', carousel_str))
        ]

    m = _MAIN_CHAMPION_RE.search(blob)
    if m:
        api = m.group(1)
        detail["main_champion"] = {
            "apiName": api,
            "name": _human_name(api),
            "cost": int(m.group(2)),
        }

    m = _TIP_RE.search(blob)
    if m:
        # Unescape the only sequences we expect inside a tip string.
        detail["tip"] = m.group(1).replace('\\"', '"').replace("\\n", "\n")

    m = _DIFFICULTY_RE.search(blob)
    if m:
        detail["difficulty"] = m.group(1)

    return detail or None


# Carry / trait lookup

def _seed_lookup_from_existing() -> dict[str, dict]:
    """
    Build a name → {carry, match_traits, trend} lookup using the curated
    META_COMPS in game_data. We want to preserve those fields when refreshing
    from a fresh scrape (the scrape only gives us name + tier).
    """
    import game_data
    seed: dict[str, dict] = {}
    for entry in game_data.META_COMPS:
        seed[entry["name"]] = {
            "carry": entry.get("carry", "?"),
            "match_traits": list(entry.get("match_traits", [])),
            "trend": entry.get("trend", ""),
        }
    return seed


def _merge_scraped_into_full(
    scraped: list[dict],
    seed: dict[str, dict],
    detail_by_slug: Optional[dict[str, dict]] = None,
) -> list[dict]:
    """
    Combine bare {name, tier, slug} scrape output with the curated carry/match
    metadata from `seed`. Comps in `seed` that aren't in `scraped` are
    dropped (they are no longer in the meta).

    If `detail_by_slug` is provided, any cached `detail` blob for a matching
    slug is preserved (so a listing-only refresh doesn't drop expensive
    per-comp scrape results).
    """
    detail_by_slug = detail_by_slug or {}
    merged: list[dict] = []
    for entry in scraped:
        meta = seed.get(entry["name"], {})
        merged_entry = {
            "name": entry["name"],
            "tier": entry["tier"],
            "slug": entry.get("slug", ""),
            "trend": meta.get("trend", ""),
            "carry": meta.get("carry", "?"),
            "match_traits": meta.get("match_traits", []),
        }
        cached_detail = detail_by_slug.get(merged_entry["slug"])
        if cached_detail:
            merged_entry["detail"] = cached_detail
        merged.append(merged_entry)
    return merged


def _detail_by_slug_from_cache() -> dict[str, dict]:
    """Read existing per-comp detail out of the on-disk cache, keyed by slug."""
    cache = load_cache() or {}
    out: dict[str, dict] = {}
    for entry in cache.get("comps") or []:
        slug = entry.get("slug")
        detail = entry.get("detail")
        if slug and detail:
            out[slug] = detail
    return out


#  HTTP fetch 

def _fetch_html_blocking(url: str) -> str:
    """Plain blocking fetch. Always called via asyncio.to_thread."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _fetch_comp_detail_blocking(slug: str) -> str:
    """Fetch one comp detail page by slug. Always called via asyncio.to_thread."""
    return _fetch_html_blocking(COMP_DETAIL_URL_TEMPLATE.format(slug=slug))


#  Public API 

def init_from_cache() -> Optional[str]:
    """
    Load cached tier data into `game_data` (in-place). Call this once at
    process startup. Returns the cached patch string, or None if no cache.
    """
    cache = load_cache()
    if not cache:
        return None
    comps = cache.get("comps") or []
    apply_to_game_data(comps)
    patch = cache.get("patch")
    logger.info(
        f"Loaded TFT Academy cache: patch={patch}, {len(comps)} comps "
        f"(synced {cache.get('synced_at', 'unknown')})"
    )
    return patch


async def refresh_async(
    *,
    force: bool = False,
    debounce_seconds: int = DEFAULT_DEBOUNCE_SECONDS,
) -> dict:
    """
    Check tftacademy.com for new tier-list data and update the cache + the
    in-memory META_COMPS if anything changed.

    Returns a status dict:
        {
            "checked": bool,         # did we actually hit the network?
            "refreshed": bool,       # did we write a new cache?
            "patch": str|None,       # patch reported by the live page
            "error": str|None,       # error message on failure, if any
        }

    Safe to call concurrently — only one refresh runs at a time. Subsequent
    callers within `debounce_seconds` of a previous attempt return early
    without hitting the network.
    """
    global _last_refresh_attempt_at, _last_successful_patch

    now = time.monotonic()
    if not force and (now - _last_refresh_attempt_at) < debounce_seconds:
        return {
            "checked": False,
            "refreshed": False,
            "patch": _last_successful_patch,
            "error": None,
        }

    async with _refresh_lock:
        # Re-check inside the lock — another caller may have just run.
        now = time.monotonic()
        if not force and (now - _last_refresh_attempt_at) < debounce_seconds:
            return {
                "checked": False,
                "refreshed": False,
                "patch": _last_successful_patch,
                "error": None,
            }
        _last_refresh_attempt_at = now

        try:
            html = await asyncio.to_thread(_fetch_html_blocking, COMPS_URL)
        except Exception as e:
            logger.warning(f"TFT Academy fetch failed: {e}")
            return {
                "checked": True,
                "refreshed": False,
                "patch": _last_successful_patch,
                "error": str(e),
            }

        live_patch = parse_patch(html)
        scraped = parse_comps(html)
        if not scraped:
            logger.warning(
                "TFT Academy scrape returned 0 comps — page layout may have "
                "changed. Keeping existing cache."
            )
            return {
                "checked": True,
                "refreshed": False,
                "patch": live_patch,
                "error": "no comps parsed",
            }

        cache = load_cache() or {}
        cached_patch = cache.get("patch")
        cached_count = len(cache.get("comps") or [])

        same_patch = live_patch and cached_patch and live_patch == cached_patch
        same_size  = len(scraped) == cached_count

        if same_patch and same_size and not force:
            # Nothing meaningful changed — touch the timestamp and bail.
            cache["last_checked_at"] = datetime.datetime.utcnow().isoformat() + "Z"
            save_cache(cache)
            _last_successful_patch = live_patch
            return {
                "checked": True,
                "refreshed": False,
                "patch": live_patch,
                "error": None,
            }

        merged = _merge_scraped_into_full(
            scraped,
            _seed_lookup_from_existing(),
            detail_by_slug=_detail_by_slug_from_cache(),
        )
        apply_to_game_data(merged)

        new_cache = {
            "patch": live_patch or cached_patch,
            "synced_at": datetime.datetime.utcnow().isoformat() + "Z",
            "last_checked_at": datetime.datetime.utcnow().isoformat() + "Z",
            "source_url": COMPS_URL,
            "comps": merged,
        }
        save_cache(new_cache)
        _last_successful_patch = live_patch

        logger.info(
            f"TFT Academy tier list refreshed: patch={live_patch}, "
            f"{len(merged)} comps "
            f"(was {cached_count} on patch {cached_patch})"
        )
        return {
            "checked": True,
            "refreshed": True,
            "patch": live_patch,
            "error": None,
        }


async def refresh_details_async(
    *,
    force: bool = False,
    debounce_seconds: int = DEFAULT_DEBOUNCE_SECONDS,
    rate_limit_seconds: float = DEFAULT_DETAIL_RATE_LIMIT,
    max_per_run: Optional[int] = None,
) -> dict:
    """
    Walk the on-disk cache and fetch per-comp detail (units, items, augments)
    for any comp whose cached detail is missing or stale (different patch).

    Returns a status dict:
        {
            "checked": bool,         # did we actually look at the network?
            "fetched": int,          # how many detail pages we pulled this run
            "skipped": int,          # how many were already fresh
            "errors": list[str],     # one entry per slug that failed
        }

    Sequential + rate-limited so we don't hammer TFT Academy. Safe to call
    concurrently — a second caller sees the lock and bails on the debounce.
    Run `refresh_async()` first so the listing (and therefore the slug list)
    is populated.
    """
    global _last_details_refresh_at

    now = time.monotonic()
    if not force and (now - _last_details_refresh_at) < debounce_seconds:
        return {"checked": False, "fetched": 0, "skipped": 0, "errors": []}

    async with _details_refresh_lock:
        now = time.monotonic()
        if not force and (now - _last_details_refresh_at) < debounce_seconds:
            return {"checked": False, "fetched": 0, "skipped": 0, "errors": []}
        _last_details_refresh_at = now

        cache = load_cache()
        if not cache:
            return {
                "checked": True,
                "fetched": 0,
                "skipped": 0,
                "errors": ["no cache on disk — run refresh_async() first"],
            }

        patch = cache.get("patch") or ""
        comps = cache.get("comps") or []

        # Decide which slugs need a re-fetch.
        to_fetch: list[dict] = []
        skipped = 0
        for entry in comps:
            slug = entry.get("slug")
            if not slug:
                continue
            existing = entry.get("detail") or {}
            if (
                not force
                and existing.get("patch") == patch
                and existing.get("units")
            ):
                skipped += 1
                continue
            to_fetch.append(entry)

        if max_per_run is not None:
            to_fetch = to_fetch[:max_per_run]

        fetched = 0
        errors: list[str] = []
        for i, entry in enumerate(to_fetch):
            slug = entry["slug"]
            try:
                html = await asyncio.to_thread(_fetch_comp_detail_blocking, slug)
            except Exception as e:
                errors.append(f"{slug}: {e}")
                logger.warning(f"TFT Academy detail fetch failed for {slug}: {e}")
            else:
                detail = parse_comp_detail(html)
                if not detail:
                    errors.append(f"{slug}: no detail parsed")
                    logger.warning(
                        f"No detail parsed for {slug} — page layout may have "
                        f"changed; check parse_comp_detail()."
                    )
                else:
                    detail["patch"] = patch
                    detail["scraped_at"] = datetime.datetime.utcnow().isoformat() + "Z"
                    entry["detail"] = detail
                    fetched += 1

            # Be a polite scraper: pause between pages even on failure.
            if i < len(to_fetch) - 1 and rate_limit_seconds > 0:
                await asyncio.sleep(rate_limit_seconds)

        if fetched:
            cache["last_checked_at"] = datetime.datetime.utcnow().isoformat() + "Z"
            save_cache(cache)
            # Refresh the in-memory copy so consumers see the new details.
            apply_to_game_data(cache.get("comps") or [])

        logger.info(
            f"TFT Academy detail refresh: fetched={fetched}, "
            f"skipped={skipped}, errors={len(errors)}"
        )
        return {
            "checked": True,
            "fetched": fetched,
            "skipped": skipped,
            "errors": errors,
        }


def schedule_background_refresh(
    *,
    initial_delay_seconds: float = 1.0,
    debounce_seconds: int = DEFAULT_DEBOUNCE_SECONDS,
    include_details: bool = False,
) -> asyncio.Task:
    """
    Convenience wrapper: schedule a single refresh on the running event
    loop. Returns the task so callers can await it if they choose.

    Use this from server startup or from a WebSocket connect handler — it
    fires-and-forgets safely.

    Set `include_details=True` to also fetch per-comp detail pages after the
    listing refresh. Detail refresh is rate-limited and can take ~30s on a
    cold cache, so leave it False for latency-sensitive call sites (e.g.
    WebSocket handshake) and True for startup.
    """
    async def _run():
        if initial_delay_seconds > 0:
            await asyncio.sleep(initial_delay_seconds)
        try:
            await refresh_async(debounce_seconds=debounce_seconds)
            if include_details:
                await refresh_details_async(debounce_seconds=debounce_seconds)
        except Exception:
            logger.exception("Unexpected error during background refresh")

    return asyncio.create_task(_run())


# Auto-load the cache on import so any module that imports META_COMPS
# afterward sees the cached values.
_initial_patch = init_from_cache()
