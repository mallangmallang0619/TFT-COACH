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

# Display-name overrides keyed by the prefix-stripped apiName, lowercased.
# TFT Academy ships some units under internal codenames that don't match the
# in-game champion name; map them here so the scrape stays human-readable.
# 'TFT17_IvernMinion' is the in-game champion Meepsie.
_APINAME_OVERRIDES = {
    "ivernminion": "Meepsie",
}
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


# Lazily-built reverse index mapping any "normalized" name (apostrophes/spaces
# stripped, lowercased) to the canonical name used in game_data.CHAMPIONS /
# ITEM_RECIPES. Built from game_data once at first use; rebuilt on demand so
# the order of module imports doesn't matter.
_canonical_index: Optional[dict[str, str]] = None


def _build_canonical_index() -> dict[str, str]:
    """
    Build the reverse lookup from game_data on first use. Each canonical
    name gets multiple keys: with apostrophes removed, with apostrophes
    replaced by space, and the lowercased forms of each. This catches the
    inconsistent apiName casing Riot ships ('TFT17_Belveth' vs
    'TFT17_RekSai') and the apostrophes the scrape always drops.
    """
    import game_data

    index: dict[str, str] = {}
    sources: list[str] = []
    for name in game_data.CHAMPIONS:
        sources.append(name)
    for recipe in game_data.ITEM_RECIPES:
        sources.append(recipe["name"])

    for canonical in sources:
        variants = {
            canonical,
            canonical.replace("'", ""),
            canonical.replace("'", " "),
        }
        for v in variants:
            collapsed = " ".join(v.split())   # collapse double spaces
            index[collapsed.lower()] = canonical
    return index


def canonical_name(name: str) -> str:
    """
    Map a scraper-produced name to its canonical form in game_data.
    Returns the input unchanged if no canonical match exists (e.g. items
    from older sets that aren't in our ITEM_RECIPES yet).
    """
    global _canonical_index
    if not name:
        return name
    if _canonical_index is None:
        _canonical_index = _build_canonical_index()
    key = " ".join(name.replace("'", "").split()).lower()
    return _canonical_index.get(key, name)


def _human_name(api_name: str) -> str:
    """
    Turn an apiName like 'TFT17_TahmKench' into a human label, then resolve
    that label to its canonical game_data spelling (with apostrophes) when
    possible. Falls back to the camelCase-split label for unknown names.
    """
    stripped = _API_PREFIX_RE.sub("", api_name)
    override = _APINAME_OVERRIDES.get(stripped.lower())
    if override is not None:
        return override
    split = _CAMEL_SPLIT_RE.sub(" ", stripped)
    return canonical_name(split)


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


#  Augment tier-list sync
#
# TFT Academy's augments *page* is client-rendered, but the page's own data
# source is a plain JSON API (found in the SvelteKit bundle):
#     GET /api/tierlist/augments?set=<N>
# It returns S/A/B/C buckets of augment apiNames per augment slot
# (1=silver, 2=gold, 3=prismatic) and per pick stage (2-1 / 3-2 / 4-2 / All).
# Display names are resolved via Data Dragon's tft-augments.json, falling
# back to camelCase-splitting the apiName for anything it doesn't carry.

AUGMENTS_API_URL_TEMPLATE = "https://tftacademy.com/api/tierlist/augments?set={set_number}"
# Fallback set number, used only when it can't be derived from comp slugs.
CURRENT_SET_NUMBER = 17

_SLUG_SET_NUMBER_RE = re.compile(r"^set-?(\d+)", re.IGNORECASE)


def current_set_number(cache: Optional[dict] = None) -> int:
    """
    Derive the live TFT set number from the cached comp slugs
    ('set-17-dark-star' → 17), so a new set is picked up without a code
    change. Falls back to CURRENT_SET_NUMBER when no slugs are available.
    """
    if cache is None:
        cache = load_cache() or {}
    best = 0
    for entry in cache.get("comps") or []:
        m = _SLUG_SET_NUMBER_RE.match(entry.get("slug") or "")
        if m:
            best = max(best, int(m.group(1)))
    return best or CURRENT_SET_NUMBER


DDRAGON_VERSIONS_URL = "https://ddragon.leagueoflegends.com/api/versions.json"
DDRAGON_AUGMENTS_URL_TEMPLATE = (
    "https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/tft-augments.json"
)

_AUGMENT_SLOT_NAMES = {1: "silver", 2: "gold", 3: "prismatic"}

_augments_refresh_lock = asyncio.Lock()
_last_augments_refresh_at: float = 0.0
# Snapshot of the hand-curated AUGMENT_RATINGS taken before the first live
# apply, so curated tips survive refreshes and curated-only entries (comp-page
# X-tier augments the API doesn't list) are never dropped.
_curated_augment_seed: Optional[dict] = None


def parse_augments_payload(payload: dict, name_by_api: dict[str, str]) -> list[dict]:
    """
    Flatten the augments API payload into one entry per augment:

        {"api_name": "TFT_Augment_SmallGrabBag",
         "name": "Small Grab Bag",
         "slot": "silver",
         "ratings": {"All": "A", "2-1": "S", ...}}   # stage → tier

    Unknown tier letters are dropped; unknown apiNames get a name derived
    from the apiName itself.
    """
    by_api: dict[str, dict] = {}
    for block in payload.get("augments_tierlists") or []:
        slot = _AUGMENT_SLOT_NAMES.get(block.get("augmenttier"), "unknown")
        stage = str(block.get("stage") or "All")
        for tier, api_names in (block.get("tier") or {}).items():
            if tier not in _VALID_TIERS:
                continue
            for api_name in api_names or []:
                entry = by_api.setdefault(api_name, {
                    "api_name": api_name,
                    "name": name_by_api.get(api_name) or _human_name(api_name),
                    "slot": slot,
                    "ratings": {},
                })
                entry["ratings"][stage] = tier
    return sorted(by_api.values(), key=lambda e: e["name"])


def _fetch_augments_blocking(set_number: int = CURRENT_SET_NUMBER) -> dict:
    """Fetch the augments tier-list API. Always called via asyncio.to_thread."""
    raw = _fetch_html_blocking(AUGMENTS_API_URL_TEMPLATE.format(set_number=set_number))
    return json.loads(raw)


def _fetch_ddragon_augment_names_blocking() -> dict[str, str]:
    """Fetch {apiName: display name} from Data Dragon's tft-augments.json."""
    versions = json.loads(_fetch_html_blocking(DDRAGON_VERSIONS_URL))
    payload = json.loads(_fetch_html_blocking(
        DDRAGON_AUGMENTS_URL_TEMPLATE.format(version=versions[0])
    ))
    return {
        api_name: entry["name"]
        for api_name, entry in (payload.get("data") or {}).items()
        if entry.get("name")
    }


def _augment_overall_rating(ratings: dict[str, str]) -> Optional[str]:
    """The rating shown in the overlay: the 'All'-stages bucket when present."""
    return ratings.get("All") or next(iter(ratings.values()), None)


def _augment_generated_tip(entry: dict) -> str:
    """Fallback tip for augments without a hand-curated one."""
    ratings = entry.get("ratings") or {}
    overall = _augment_overall_rating(ratings)
    per_stage = ", ".join(
        f"{stage}: {tier}" for stage, tier in sorted(ratings.items()) if stage != "All"
    )
    stage_note = f" By pick stage — {per_stage}." if per_stage else ""
    return (
        f"TFT Academy rates this {overall}-tier among {entry.get('slot', '?')} "
        f"augments.{stage_note}"
    )


def apply_augments_to_game_data(augments: list[dict]) -> None:
    """
    Replace `game_data.AUGMENT_RATINGS` (in place) with live tier data.

    Hand-curated tips win over generated ones when the names match, and
    curated entries the live list doesn't carry are kept. Mutating the dict
    in place keeps existing `from game_data import AUGMENT_RATINGS`
    references live.
    """
    if not augments:
        return
    import game_data

    global _curated_augment_seed
    if _curated_augment_seed is None:
        _curated_augment_seed = dict(game_data.AUGMENT_RATINGS)

    merged: dict[str, dict] = {}
    for entry in augments:
        ratings = entry.get("ratings") or {}
        overall = _augment_overall_rating(ratings)
        name = entry.get("name")
        if not name or not overall:
            continue
        curated = _curated_augment_seed.get(name)
        merged[name] = {
            "rating": overall,
            "tip": curated["tip"] if curated else _augment_generated_tip(entry),
            "slot": entry.get("slot"),
            "stage_ratings": ratings,
        }
    for name, data in _curated_augment_seed.items():
        merged.setdefault(name, data)

    game_data.AUGMENT_RATINGS.clear()
    game_data.AUGMENT_RATINGS.update(merged)


async def refresh_augments_async(
    *,
    force: bool = False,
    debounce_seconds: int = DEFAULT_DEBOUNCE_SECONDS,
) -> dict:
    """
    Refresh the augment tier list from TFT Academy's API and update the
    cache + in-memory AUGMENT_RATINGS.

    Returns {"checked": bool, "refreshed": bool, "count": int, "error": str|None}.
    Debounced and lock-serialized like refresh_async().
    """
    global _last_augments_refresh_at

    now = time.monotonic()
    if not force and (now - _last_augments_refresh_at) < debounce_seconds:
        return {"checked": False, "refreshed": False, "count": 0, "error": None}

    async with _augments_refresh_lock:
        now = time.monotonic()
        if not force and (now - _last_augments_refresh_at) < debounce_seconds:
            return {"checked": False, "refreshed": False, "count": 0, "error": None}
        _last_augments_refresh_at = now

        cache = load_cache() or {}
        set_number = current_set_number(cache)
        try:
            payload = await asyncio.to_thread(_fetch_augments_blocking, set_number)
        except Exception as e:
            logger.warning(f"TFT Academy augments fetch failed: {e}")
            return {"checked": True, "refreshed": False, "count": 0, "error": str(e)}

        # Resolve apiNames → display names. Names already resolved in the
        # cache are reused so Data Dragon is only hit when new augments show up.
        name_by_api = {
            e["api_name"]: e["name"]
            for e in (cache.get("augments") or {}).get("entries") or []
            if e.get("api_name") and e.get("name")
        }
        wanted = {
            api_name
            for block in payload.get("augments_tierlists") or []
            for api_names in (block.get("tier") or {}).values()
            for api_name in api_names or []
        }
        if wanted - set(name_by_api):
            try:
                name_by_api.update(
                    await asyncio.to_thread(_fetch_ddragon_augment_names_blocking)
                )
            except Exception as e:
                logger.warning(
                    f"Data Dragon augment-name fetch failed ({e}); "
                    f"deriving names from apiNames"
                )

        entries = parse_augments_payload(payload, name_by_api)
        if not entries:
            logger.warning(
                "TFT Academy augments API returned 0 augments — payload shape "
                "may have changed. Keeping existing data."
            )
            return {
                "checked": True, "refreshed": False, "count": 0,
                "error": "no augments parsed",
            }

        apply_augments_to_game_data(entries)
        cache["augments"] = {
            "set": set_number,
            "synced_at": datetime.datetime.utcnow().isoformat() + "Z",
            "source_url": AUGMENTS_API_URL_TEMPLATE.format(set_number=set_number),
            "entries": entries,
        }
        save_cache(cache)
        logger.info(f"TFT Academy augment tier list refreshed: {len(entries)} augments")
        return {
            "checked": True, "refreshed": True,
            "count": len(entries), "error": None,
        }


#  Item tier list (craftables + radiant items + artifacts + emblems)
#
# Same hidden API family as the augments: /api/tierlist/items?set=N returns
# several tier lists per item kind ("craftables", "ornns" = artifacts,
# "radiants", "emblems"), sometimes with stale duplicates — the freshest
# non-empty list per kind wins. apiNames resolve via Data Dragon's
# tft-item.json (its radiant keys are path-prefixed, e.g.
# "Set5_RadiantItems/TFT5_Item_...", so names are keyed on the last path
# segment).

ITEMS_API_URL_TEMPLATE = "https://tftacademy.com/api/tierlist/items?set={set_number}"
DDRAGON_ITEMS_URL_TEMPLATE = (
    "https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/tft-item.json"
)

_ITEM_KIND_BY_TYPE = {
    "craftables": "craftable",
    "ornns": "artifact",
    "radiants": "radiant",
    "emblems": "emblem",
}

_items_refresh_lock = asyncio.Lock()
_last_items_refresh_at: float = 0.0


def _fetch_items_blocking(set_number: int = CURRENT_SET_NUMBER) -> dict:
    raw = _fetch_html_blocking(ITEMS_API_URL_TEMPLATE.format(set_number=set_number))
    return json.loads(raw)


def _fetch_ddragon_item_names_blocking() -> dict[str, str]:
    """{apiName (last path segment): display name} from tft-item.json."""
    versions = json.loads(_fetch_html_blocking(DDRAGON_VERSIONS_URL))
    payload = json.loads(_fetch_html_blocking(
        DDRAGON_ITEMS_URL_TEMPLATE.format(version=versions[0])
    ))
    return {
        api_name.split("/")[-1]: entry["name"]
        for api_name, entry in (payload.get("data") or {}).items()
        if entry.get("name")
    }


def parse_items_payload(payload: dict, name_by_api: dict[str, str]) -> list[dict]:
    """
    Flatten the items API payload into one entry per item:

        {"api_name": "TFT_Item_Artifact_Dawncore",
         "name": "Dawncore", "kind": "artifact", "tier": "S"}

    The payload repeats each kind (stale rebuild leftovers) — the most
    recently updated list that actually has items wins per kind.
    """
    best_by_kind: dict[str, dict] = {}
    for block in payload.get("items_tierlists") or []:
        kind = _ITEM_KIND_BY_TYPE.get(block.get("type"))
        if kind is None:
            continue
        count = sum(len(v or []) for v in (block.get("tier") or {}).values())
        if count == 0:
            continue
        cur = best_by_kind.get(kind)
        if cur is None or (block.get("updated") or "") > (cur.get("updated") or ""):
            best_by_kind[kind] = block

    entries: list[dict] = []
    for kind, block in best_by_kind.items():
        for tier, api_names in (block.get("tier") or {}).items():
            if tier not in _VALID_TIERS:
                continue
            for api_name in api_names or []:
                entries.append({
                    "api_name": api_name,
                    "name": name_by_api.get(api_name) or _human_name(api_name),
                    "kind": kind,
                    "tier": tier,
                })
    return sorted(entries, key=lambda e: (e["kind"], e["name"]))


def apply_items_to_game_data(entries: list[dict]) -> None:
    """
    Push live item tiers into game_data: LIVE_ITEM_TIERS (in place, covers
    radiants/artifacts/emblems that have no recipe) and the tier field of
    matching ITEM_RECIPES rows, so every consumer of static tiers follows
    the live list. Mechanical flags (shred/burn/type/recipe) stay static —
    they're facts about the items, not opinions that move with patches.
    """
    if not entries:
        return
    import game_data

    game_data.LIVE_ITEM_TIERS.clear()
    for e in entries:
        if e.get("name") and e.get("tier"):
            game_data.LIVE_ITEM_TIERS[game_data.norm_item_key(e["name"])] = {
                "name": e["name"], "tier": e["tier"], "kind": e["kind"],
            }

    for recipe in game_data.ITEM_RECIPES:
        live = game_data.LIVE_ITEM_TIERS.get(game_data.norm_item_key(recipe["name"]))
        if live and live["kind"] == "craftable":
            recipe["tier"] = live["tier"]


async def refresh_items_async(
    *,
    force: bool = False,
    debounce_seconds: int = DEFAULT_DEBOUNCE_SECONDS,
) -> dict:
    """
    Refresh the item tier list from TFT Academy's API and update the
    cache + in-memory tiers. Debounced and lock-serialized like the
    augments refresh.
    """
    global _last_items_refresh_at

    now = time.monotonic()
    if not force and (now - _last_items_refresh_at) < debounce_seconds:
        return {"checked": False, "refreshed": False, "count": 0, "error": None}

    async with _items_refresh_lock:
        now = time.monotonic()
        if not force and (now - _last_items_refresh_at) < debounce_seconds:
            return {"checked": False, "refreshed": False, "count": 0, "error": None}
        _last_items_refresh_at = now

        cache = load_cache() or {}
        set_number = current_set_number(cache)
        try:
            payload = await asyncio.to_thread(_fetch_items_blocking, set_number)
        except Exception as e:
            logger.warning(f"TFT Academy items fetch failed: {e}")
            return {"checked": True, "refreshed": False, "count": 0, "error": str(e)}

        name_by_api = {
            e["api_name"]: e["name"]
            for e in (cache.get("items") or {}).get("entries") or []
            if e.get("api_name") and e.get("name")
        }
        wanted = {
            api_name
            for block in payload.get("items_tierlists") or []
            for api_names in (block.get("tier") or {}).values()
            for api_name in api_names or []
        }
        if wanted - set(name_by_api):
            try:
                name_by_api.update(
                    await asyncio.to_thread(_fetch_ddragon_item_names_blocking)
                )
            except Exception as e:
                logger.warning(
                    f"Data Dragon item-name fetch failed ({e}); "
                    f"deriving names from apiNames"
                )

        entries = parse_items_payload(payload, name_by_api)
        if not entries:
            logger.warning(
                "TFT Academy items API returned 0 items — payload shape "
                "may have changed. Keeping existing data."
            )
            return {
                "checked": True, "refreshed": False, "count": 0,
                "error": "no items parsed",
            }

        apply_items_to_game_data(entries)
        cache["items"] = {
            "set": set_number,
            "synced_at": datetime.datetime.utcnow().isoformat() + "Z",
            "source_url": ITEMS_API_URL_TEMPLATE.format(set_number=set_number),
            "entries": entries,
        }
        save_cache(cache)
        logger.info(f"TFT Academy item tier list refreshed: {len(entries)} items")
        return {
            "checked": True, "refreshed": True,
            "count": len(entries), "error": None,
        }


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
    augment_entries = (cache.get("augments") or {}).get("entries") or []
    apply_augments_to_game_data(augment_entries)
    item_entries = (cache.get("items") or {}).get("entries") or []
    apply_items_to_game_data(item_entries)
    patch = cache.get("patch")
    logger.info(
        f"Loaded TFT Academy cache: patch={patch}, {len(comps)} comps, "
        f"{len(augment_entries)} augments, {len(item_entries)} items "
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
            # Two cheap JSON calls — refresh augment and item tiers
            # alongside the listing (their own debounce keeps repeats free).
            await refresh_augments_async(debounce_seconds=debounce_seconds)
            await refresh_items_async(debounce_seconds=debounce_seconds)
            if include_details:
                await refresh_details_async(debounce_seconds=debounce_seconds)
        except Exception:
            logger.exception("Unexpected error during background refresh")

    return asyncio.create_task(_run())


# Auto-load the cache on import so any module that imports META_COMPS
# afterward sees the cached values.
_initial_patch = init_from_cache()
