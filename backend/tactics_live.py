"""Debounced tactics.tools unit-stat sync used by board-strength scoring."""

from __future__ import annotations

import asyncio
import datetime
import html
import json
import logging
import re
import time
import urllib.request
from pathlib import Path
from typing import Optional

from game_data import CHAMPIONS

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = PROJECT_ROOT / "assets" / "tactics_cache.json"
UNITS_URL = "https://tactics.tools/units/sett/latest"
USER_AGENT = "TFT-Coach/1.0 unit-stats cache"
HTTP_TIMEOUT_SECONDS = 12
DEFAULT_DEBOUNCE_SECONDS = 6 * 60 * 60

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.DOTALL,
)
_PATCH_RE = re.compile(r"Patch\s+([0-9]+(?:\.[0-9a-z]+)+)", re.IGNORECASE)
_API_PREFIX_RE = re.compile(r"^TFT\d+_", re.IGNORECASE)

_refresh_lock = asyncio.Lock()
_last_refresh_attempt_at = 0.0
_unit_stats: dict[str, dict] = {}
_snapshot_meta: dict[str, object] = {}


def _norm(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _champion_name_for_api(api_name: str) -> Optional[str]:
    suffix = _API_PREFIX_RE.sub("", api_name)
    wanted = _norm(suffix)
    aliases = {
        "nunuwillump": "nunu",
        "reksai": "reksai",
        "kaisa": "kaisa",
        "belveth": "belveth",
    }
    wanted = aliases.get(wanted, wanted)
    for name in CHAMPIONS:
        if _norm(name) == wanted:
            return name
    return None


def parse_units_html(page_html: str) -> dict:
    """Extract a normalized unit-stat snapshot from Next.js page data."""
    match = _NEXT_DATA_RE.search(page_html)
    if not match:
        raise ValueError("tactics.tools page did not contain __NEXT_DATA__")
    payload = json.loads(html.unescape(match.group(1)))
    page_props = payload.get("props", {}).get("pageProps", {})
    stats_data = page_props.get("statsData") or {}
    raw_units = stats_data.get("units") or {}

    units: dict[str, dict] = {}
    for api_name, row in raw_units.items():
        name = _champion_name_for_api(api_name)
        if name is None or not isinstance(row, dict):
            continue
        try:
            units[name] = {
                "api_name": api_name,
                "games": int(row.get("count") or 0),
                "avg_place": float(row["place"]),
                "top4": float(row["top4"]),
                "win": float(row["won"]),
                "star_avg_place": (
                    float(row["starPlace"])
                    if row.get("starPlace") is not None else None
                ),
            }
        except (KeyError, TypeError, ValueError):
            continue

    if len(units) < 40:
        raise ValueError(f"only parsed {len(units)} recognized units")
    patch_match = _PATCH_RE.search(page_html)
    return {
        "source_url": UNITS_URL,
        "patch": patch_match.group(1) if patch_match else None,
        "rank": "Diamond+",
        "games_analyzed": int(stats_data.get("totalEntries") or 0),
        "source_updated_at": int(stats_data.get("lastUpdated") or 0),
        "synced_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "units": units,
    }


def _fetch_snapshot_blocking() -> dict:
    request = urllib.request.Request(UNITS_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        page_html = response.read().decode("utf-8", errors="replace")
    return parse_units_html(page_html)


def load_cache() -> Optional[dict]:
    if not CACHE_PATH.exists():
        return None
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        logger.warning(f"tactics.tools cache unreadable ({error}); ignoring it")
        return None


def save_cache(snapshot: dict) -> bool:
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(
            json.dumps(snapshot, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return True
    except OSError as error:
        logger.warning(f"Could not write tactics.tools cache: {error}")
        return False


def apply_snapshot(snapshot: dict) -> None:
    global _unit_stats, _snapshot_meta
    units = snapshot.get("units") or {}
    if not units:
        return
    _unit_stats = dict(units)
    _snapshot_meta = {
        key: snapshot.get(key)
        for key in (
            "source_url", "patch", "rank", "games_analyzed",
            "source_updated_at", "synced_at",
        )
    }


def init_from_cache() -> Optional[str]:
    snapshot = load_cache()
    if not snapshot:
        return None
    apply_snapshot(snapshot)
    logger.info(
        f"Loaded tactics.tools cache: patch={snapshot.get('patch')}, "
        f"{len(_unit_stats)} units"
    )
    return snapshot.get("patch")


def unit_stat(name: str) -> Optional[dict]:
    return _unit_stats.get(name)


def snapshot_meta() -> dict:
    return dict(_snapshot_meta)


def unit_meta_rating(name: str, cost: int) -> float:
    """Return -1..1 performance relative to other units of the same cost."""
    current = unit_stat(name)
    if not current:
        return 0.0
    peers = [
        stats
        for peer_name, stats in _unit_stats.items()
        if CHAMPIONS.get(peer_name, {}).get("cost") == cost
    ]
    if len(peers) < 3:
        return 0.0

    mean_place = sum(row["avg_place"] for row in peers) / len(peers)
    mean_top4 = sum(row["top4"] for row in peers) / len(peers)
    mean_win = sum(row["win"] for row in peers) / len(peers)
    score = (
        0.65 * ((mean_place - current["avg_place"]) / 0.45)
        + 0.25 * ((current["top4"] - mean_top4) / 7.0)
        + 0.10 * ((current["win"] - mean_win) / 5.0)
    )
    return max(-1.0, min(1.0, score))


async def refresh_async(
    *,
    force: bool = False,
    debounce_seconds: int = DEFAULT_DEBOUNCE_SECONDS,
) -> dict:
    global _last_refresh_attempt_at
    now = time.monotonic()
    if not force and now - _last_refresh_attempt_at < debounce_seconds:
        return {"checked": False, "refreshed": False, "error": None}

    async with _refresh_lock:
        now = time.monotonic()
        if not force and now - _last_refresh_attempt_at < debounce_seconds:
            return {"checked": False, "refreshed": False, "error": None}
        _last_refresh_attempt_at = now
        try:
            snapshot = await asyncio.to_thread(_fetch_snapshot_blocking)
        except Exception as error:
            logger.warning(f"tactics.tools unit-stat fetch failed: {error}")
            return {"checked": True, "refreshed": False, "error": str(error)}

        apply_snapshot(snapshot)
        saved = save_cache(snapshot)
        logger.info(
            f"tactics.tools unit stats refreshed: {len(_unit_stats)} units, "
            f"patch {snapshot.get('patch')}"
        )
        return {
            "checked": True,
            "refreshed": saved,
            "count": len(_unit_stats),
            "patch": snapshot.get("patch"),
            "error": None,
        }


def schedule_background_refresh(initial_delay_seconds: float = 3.0) -> None:
    async def _delayed() -> None:
        if initial_delay_seconds:
            await asyncio.sleep(initial_delay_seconds)
        await refresh_async()

    try:
        asyncio.get_running_loop().create_task(_delayed())
    except RuntimeError:
        return


_initial_patch = init_from_cache()
