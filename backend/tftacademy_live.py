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
USER_AGENT = "TFT-Coach/1.0 (auto-sync; +https://github.com/yourname/tft-coach)"

# Don't fetch more often than this — TFT Academy updates at most once per
# patch (weekly-ish). Frequent fetches add nothing and are rude to the host.
DEFAULT_DEBOUNCE_SECONDS = 30 * 60   # 30 minutes
HTTP_TIMEOUT_SECONDS = 12

# Tier letters TFT Academy uses; anything else gets dropped during parse.
_VALID_TIERS = ("S", "A", "B", "C", "X")


#  Module state 

_refresh_lock = asyncio.Lock()
_last_refresh_attempt_at: float = 0.0
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

# TFT Academy renders the patch number in headers like "Patch 17.2B" or
# "Patch 17.2b - Last Updated …". Capture the version segment.
_PATCH_RE = re.compile(r"Patch\s+([0-9]+\.[0-9]+[a-zA-Z]?)", re.IGNORECASE)

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
_COMP_LINK_RE = re.compile(
    r"""<a[^>]+href=["']/tierlist/comps/[^"']+["'][^>]*>
        (?P<text>[^<]+)
        </a>""",
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)


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
    tokens: list[tuple[int, str, str]] = []   # (pos, kind, value)
    for m in _TIER_LABEL_RE.finditer(html):
        tier = next((g for g in m.groups() if g), "")
        if tier:
            tokens.append((m.start(), "tier", tier.upper()))
    for m in _COMP_LINK_RE.finditer(html):
        name = (m.group("text") or "").strip()
        if name:
            tokens.append((m.start(), "comp", name))
    tokens.sort(key=lambda t: t[0])

    current_tier = "?"
    seen_names: set[str] = set()
    entries: list[dict] = []
    for _, kind, value in tokens:
        if kind == "tier":
            if value in _VALID_TIERS:
                current_tier = value
        elif kind == "comp" and current_tier in _VALID_TIERS:
            # Dedupe by name only — comp links appearing later in the page
            # (e.g., in nav, "related", or sidebar widgets) carry whatever
            # tier marker last appeared in the document and would otherwise
            # produce phantom entries under the wrong tier.
            if value in seen_names:
                continue
            seen_names.add(value)
            entries.append({"name": value, "tier": current_tier})
    return entries


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
) -> list[dict]:
    """
    Combine bare {name, tier} scrape output with the curated carry/match
    metadata from `seed`. Comps in `seed` that aren't in `scraped` are
    dropped (they are no longer in the meta).
    """
    merged: list[dict] = []
    for entry in scraped:
        meta = seed.get(entry["name"], {})
        merged.append({
            "name": entry["name"],
            "tier": entry["tier"],
            "trend": meta.get("trend", ""),
            "carry": meta.get("carry", "?"),
            "match_traits": meta.get("match_traits", []),
        })
    return merged


#  HTTP fetch 

def _fetch_html_blocking(url: str) -> str:
    """Plain blocking fetch. Always called via asyncio.to_thread."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
        return resp.read().decode("utf-8", errors="replace")


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

        merged = _merge_scraped_into_full(scraped, _seed_lookup_from_existing())
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


def schedule_background_refresh(
    *,
    initial_delay_seconds: float = 1.0,
    debounce_seconds: int = DEFAULT_DEBOUNCE_SECONDS,
) -> asyncio.Task:
    """
    Convenience wrapper: schedule a single refresh on the running event
    loop. Returns the task so callers can await it if they choose.

    Use this from server startup or from a WebSocket connect handler — it
    fires-and-forgets safely.
    """
    async def _run():
        if initial_delay_seconds > 0:
            await asyncio.sleep(initial_delay_seconds)
        try:
            await refresh_async(debounce_seconds=debounce_seconds)
        except Exception:
            logger.exception("Unexpected error during background refresh")

    return asyncio.create_task(_run())


# Auto-load the cache on import so any module that imports META_COMPS
# afterward sees the cached values.
_initial_patch = init_from_cache()
