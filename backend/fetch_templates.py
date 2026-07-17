"""
Template Fetcher — Riot Data Dragon

Downloads component icons + champion portraits from Riot's Data Dragon CDN
and saves them to assets/templates/{components,champions}/ with filenames
matching COMPONENT_IDS and CHAMPIONS keys in game_data.py.

This replaces the fragile in-game capture flow for static assets. The
in-game wizard (capture_templates.py) is still used for UI elements that
aren't on the CDN (stage banner, augment panel framing).

Usage:
    python backend/fetch_templates.py                 # fetch everything missing
    python backend/fetch_templates.py --force         # re-download even if present
    python backend/fetch_templates.py --components    # only components
    python backend/fetch_templates.py --champions     # only champions
    python backend/fetch_templates.py --dry-run       # show what would download
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterable, Optional

sys.path.insert(0, str(Path(__file__).parent))

from config import (
    COMPONENT_TEMPLATE_DIR,
    CHAMPION_TEMPLATE_DIR,
    TRAIT_TEMPLATE_DIR,
    ITEM_TEMPLATE_DIR,
)
from game_data import COMPONENT_NAMES, CHAMPIONS, TRAITS

logger = logging.getLogger("fetch_templates")

DDRAGON_BASE = "https://ddragon.leagueoflegends.com"
VERSIONS_URL = f"{DDRAGON_BASE}/api/versions.json"
USER_AGENT = "tft-coach-template-fetcher/0.1"
REQUEST_TIMEOUT = 15

# Community Dragon serves the real in-game art (square champion portraits, trait
# icons, item icons) that Data Dragon's splash art doesn't. We pull traits/items
# from here because Data Dragon has no trait icons and CDragon's are the actual
# HUD glyphs the detector needs to match.
CDRAGON_TFT_DATA = "https://raw.communitydragon.org/latest/cdragon/tft/en_us.json"
CDRAGON_GAME_BASE = "https://raw.communitydragon.org/latest/game/"
# Fallback TFT set (matches the "set-17-…" comp slugs and TFT17_ apiNames)
# used only when auto-detection against the CDragon payload fails.
CURRENT_SET = "17"


def detect_current_set(cdragon: dict) -> str:
    """
    Pick the newest set in the CDragon payload that actually ships traits.
    Falls back to CURRENT_SET so a payload-shape change can't break fetching.
    """
    best: Optional[tuple[int, str]] = None
    for key, data in (cdragon.get("sets") or {}).items():
        if not (data or {}).get("traits"):
            continue
        m = re.match(r"(\d+)", str(key))
        if not m:
            continue
        num = int(m.group(1))
        if best is None or num > best[0]:
            best = (num, str(key))
    return best[1] if best else CURRENT_SET


def cdragon_asset_url(icon_path: str) -> str:
    """Map a CDragon asset path (e.g. 'ASSETS/UX/TraitIcons/Foo.tex') to a URL.

    CDragon serves game assets lowercased with .tex/.dds rewritten to .png.
    """
    p = icon_path.lower()
    for ext in (".tex", ".dds"):
        if p.endswith(ext):
            p = p[: -len(ext)] + ".png"
            break
    if not p.endswith(".png"):
        p += ".png"
    return CDRAGON_GAME_BASE + p


def _http_get(url: str) -> bytes:
    """GET a URL with a sensible UA + timeout. Raises on non-2xx."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        return resp.read()


def _http_get_json(url: str) -> dict | list:
    return json.loads(_http_get(url).decode("utf-8"))


def get_latest_version() -> str:
    """Return the newest Data Dragon version string (e.g. '14.10.1')."""
    versions = _http_get_json(VERSIONS_URL)
    if not isinstance(versions, list) or not versions:
        raise RuntimeError(f"Unexpected versions payload: {versions!r}")
    return versions[0]


# ── Name normalization ────────────────────────────────────────────────────────

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize(name: str) -> str:
    """Lowercase, strip punctuation/whitespace — for fuzzy name matching."""
    return _NON_ALNUM.sub("", name.lower())


# ── Index builders ────────────────────────────────────────────────────────────

def build_item_index(version: str) -> dict[str, dict]:
    """
    Fetch tft-item.json and return {normalized_name: entry}.
    Entries have at least {"name": str, "image": {"full": str, ...}}.
    """
    url = f"{DDRAGON_BASE}/cdn/{version}/data/en_US/tft-item.json"
    payload = _http_get_json(url)
    items = payload.get("data", {}) if isinstance(payload, dict) else {}
    index: dict[str, dict] = {}
    for entry in items.values():
        nm = entry.get("name")
        if not nm:
            continue
        index[normalize(nm)] = entry
    return index


def build_champion_index(version: str) -> dict[str, dict]:
    """Fetch tft-champion.json and return {normalized_name: entry}."""
    url = f"{DDRAGON_BASE}/cdn/{version}/data/en_US/tft-champion.json"
    payload = _http_get_json(url)
    champs = payload.get("data", {}) if isinstance(payload, dict) else {}
    index: dict[str, dict] = {}
    for entry in champs.values():
        nm = entry.get("name")
        if not nm:
            continue
        index[normalize(nm)] = entry
    return index


def build_lol_champion_index(version: str) -> dict[str, dict]:
    """
    Fallback: regular League champion data. Used when a champ isn't in
    tft-champion.json (occasionally happens during a new set's rollout).
    """
    url = f"{DDRAGON_BASE}/cdn/{version}/data/en_US/champion.json"
    payload = _http_get_json(url)
    champs = payload.get("data", {}) if isinstance(payload, dict) else {}
    index: dict[str, dict] = {}
    for entry in champs.values():
        nm = entry.get("name")
        if not nm:
            continue
        index[normalize(nm)] = entry
    return index


# ── Download helpers ──────────────────────────────────────────────────────────

def _image_url_tft_item(version: str, filename: str) -> str:
    return f"{DDRAGON_BASE}/cdn/{version}/img/tft-item/{filename}"


def _image_url_tft_champion(version: str, filename: str) -> str:
    return f"{DDRAGON_BASE}/cdn/{version}/img/tft-champion/{filename}"


def _image_url_lol_champion(version: str, filename: str) -> str:
    return f"{DDRAGON_BASE}/cdn/{version}/img/champion/{filename}"


def download_to(path: Path, url: str, dry_run: bool = False) -> bool:
    """Download `url` to `path`. Returns True on success."""
    if dry_run:
        logger.info(f"  [dry-run] would download {url} → {path.name}")
        return True
    try:
        data = _http_get(url)
    except urllib.error.HTTPError as e:
        logger.warning(f"  HTTP {e.code} for {url}")
        return False
    except (urllib.error.URLError, TimeoutError) as e:
        logger.warning(f"  network error for {url}: {e}")
        return False
    if not data:
        logger.warning(f"  empty response for {url}")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return True


# ── Fetch jobs ────────────────────────────────────────────────────────────────

def fetch_components(
    version: str,
    item_index: dict[str, dict],
    *,
    force: bool = False,
    dry_run: bool = False,
) -> tuple[int, list[str]]:
    """Download component icons. Returns (ok_count, missing_names)."""
    ok = 0
    missing: list[str] = []

    for comp_id, display_name in COMPONENT_NAMES.items():
        out_path = COMPONENT_TEMPLATE_DIR / f"{comp_id}.png"
        if out_path.exists() and not force:
            logger.info(f"  ✓ {comp_id}.png (exists, skipping)")
            ok += 1
            continue

        entry = item_index.get(normalize(display_name))
        if entry is None:
            # Try a few common aliases
            for alias in _component_aliases(display_name):
                entry = item_index.get(normalize(alias))
                if entry:
                    break

        if entry is None:
            logger.warning(f"  ✗ {comp_id}: '{display_name}' not found in tft-item.json")
            missing.append(display_name)
            continue

        image_name = (entry.get("image") or {}).get("full")
        if not image_name:
            logger.warning(f"  ✗ {comp_id}: no image filename in entry")
            missing.append(display_name)
            continue

        url = _image_url_tft_item(version, image_name)
        if download_to(out_path, url, dry_run=dry_run):
            logger.info(f"  ✓ {comp_id}.png  ({image_name})")
            ok += 1
        else:
            missing.append(display_name)

    return ok, missing


def _champion_aliases(name: str) -> Iterable[str]:
    """Yield alternate names Data Dragon might use for a champion."""
    yield name.replace("'", "")
    if name == "Nunu":
        yield "Nunu & Willump"
        yield "Nunu and Willump"
    if name == "The Mighty Mech":
        yield "Mighty Mech"


def _component_aliases(name: str) -> Iterable[str]:
    """Yield alternate names Data Dragon might use for a component."""
    # Data Dragon historically uses "B. F. Sword" with periods + spaces,
    # and sometimes drops apostrophes from "Giant's Belt".
    yield name.replace(".", "")           # "B F Sword"
    yield name.replace("'", "")            # "Giants Belt"
    yield name.replace("'", "").replace(".", "")
    if name == "Tear of the Goddess":
        yield "Tear"


def fetch_champions(
    version: str,
    champ_index: dict[str, dict],
    lol_champ_index: dict[str, dict],
    *,
    force: bool = False,
    dry_run: bool = False,
) -> tuple[int, list[str]]:
    """Download champion portraits. Returns (ok_count, missing_names)."""
    ok = 0
    missing: list[str] = []

    for champ_name in CHAMPIONS.keys():
        # Filename uses the dict key verbatim so detector.py can do a
        # direct dict lookup later. Slashes/apostrophes are fine on disk.
        safe = champ_name.replace("/", "_")
        out_path = CHAMPION_TEMPLATE_DIR / f"{safe}.png"
        if out_path.exists() and not force:
            logger.info(f"  ✓ {safe}.png (exists, skipping)")
            ok += 1
            continue

        norm = normalize(champ_name)

        # Build search keys: canonical name + aliases
        search_keys = [norm] + [normalize(a) for a in _champion_aliases(champ_name)]

        # Prefer TFT-specific portrait
        entry: Optional[dict] = None
        for key in search_keys:
            entry = champ_index.get(key)
            if entry is not None:
                break

        url: Optional[str] = None
        if entry is not None:
            image_name = (entry.get("image") or {}).get("full")
            if image_name:
                url = _image_url_tft_champion(version, image_name)

        # Fall back to League champion square
        if url is None:
            lol_entry: Optional[dict] = None
            for key in search_keys:
                lol_entry = lol_champ_index.get(key)
                if lol_entry is not None:
                    break
            if lol_entry is not None:
                image_name = (lol_entry.get("image") or {}).get("full")
                if image_name:
                    url = _image_url_lol_champion(version, image_name)

        if url is None:
            logger.warning(f"  ✗ {champ_name}: not in tft-champion.json or champion.json")
            missing.append(champ_name)
            continue

        if download_to(out_path, url, dry_run=dry_run):
            logger.info(f"  ✓ {safe}.png  ({url.rsplit('/', 1)[-1]})")
            ok += 1
        else:
            missing.append(champ_name)

    return ok, missing


# ── Community Dragon (traits + items) ─────────────────────────────────────────

def load_cdragon_tft() -> dict:
    """Fetch the Community Dragon TFT data blob (champions/traits/items)."""
    return _http_get_json(CDRAGON_TFT_DATA)


def fetch_traits(
    cdragon: dict, *, force: bool = False, dry_run: bool = False
) -> tuple[int, list[str]]:
    """Download current-set trait icons named by their game_data.TRAITS key."""
    wanted = set(TRAITS.keys())
    set_key = detect_current_set(cdragon)
    set_traits = (cdragon.get("sets", {}).get(set_key, {}) or {}).get("traits", [])
    by_name = {t["name"]: t for t in set_traits if t.get("name")}

    ok = 0
    missing: list[str] = []
    for name in sorted(wanted):
        out_path = TRAIT_TEMPLATE_DIR / f"{name}.png"
        if out_path.exists() and not force:
            logger.info(f"  ✓ {name}.png (exists, skipping)")
            ok += 1
            continue
        entry = by_name.get(name)
        icon = entry.get("icon") if entry else None
        if not icon:
            logger.warning(f"  ✗ {name}: no trait icon in CDragon set {set_key}")
            missing.append(name)
            continue
        if download_to(out_path, cdragon_asset_url(icon), dry_run=dry_run):
            logger.info(f"  ✓ {name}.png")
            ok += 1
        else:
            missing.append(name)
    return ok, missing


def fetch_items(
    cdragon: dict, *, force: bool = False, dry_run: bool = False
) -> tuple[int, list[str]]:
    """Download item icons: the craftables in game_data.ITEM_RECIPES plus
    every radiant item, artifact, and emblem the live tier list knows."""
    from game_data import ITEM_RECIPES, LIVE_ITEM_TIERS
    try:
        # Importing tftacademy_live fills LIVE_ITEM_TIERS from the cache.
        import tftacademy_live  # noqa: F401
    except Exception as e:
        logger.debug(f"tier cache unavailable ({e}); fetching craftables only")

    items = cdragon.get("items", [])
    by_norm = {normalize(it["name"]): it for it in items if it.get("name")}

    wanted = list(dict.fromkeys(
        [r["name"] for r in ITEM_RECIPES]
        + [e["name"] for e in LIVE_ITEM_TIERS.values()
           if e["kind"] in ("radiant", "artifact", "emblem")]
    ))

    ok = 0
    missing: list[str] = []
    for name in wanted:
        name = name.strip()
        safe = name.replace("/", "_")
        out_path = ITEM_TEMPLATE_DIR / f"{safe}.png"
        if out_path.exists() and not force:
            logger.info(f"  ✓ {safe}.png (exists, skipping)")
            ok += 1
            continue
        entry = by_norm.get(normalize(name))
        icon = entry.get("icon") if entry else None
        if not icon:
            logger.warning(f"  ✗ {name}: no item icon in CDragon items")
            missing.append(name)
            continue
        if download_to(out_path, cdragon_asset_url(icon), dry_run=dry_run):
            logger.info(f"  ✓ {safe}.png")
            ok += 1
        else:
            missing.append(name)
    return ok, missing


# ── Frontend icon sync ────────────────────────────────────────────────────────

FRONTEND_ICON_DIR = (
    Path(__file__).resolve().parent.parent / "frontend" / "public" / "game_icons"
)


def sync_frontend_icons() -> int:
    """
    Copy item/component icons into frontend/public so the overlay shows the
    real game art instead of emoji (which stay as offline fallback). Vite
    serves public/ in dev and bundles it into dist/ for the packaged app.
    """
    import shutil

    copied = 0
    for src_dir, sub in ((ITEM_TEMPLATE_DIR, "items"),
                         (COMPONENT_TEMPLATE_DIR, "components")):
        dest = FRONTEND_ICON_DIR / sub
        dest.mkdir(parents=True, exist_ok=True)
        for png in src_dir.glob("*.png"):
            target = dest / png.name
            if not target.exists() or target.stat().st_mtime < png.stat().st_mtime:
                shutil.copy2(png, target)
                copied += 1
    return copied


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch TFT templates from Data Dragon")
    parser.add_argument("--force", action="store_true", help="Re-download even if a file already exists")
    parser.add_argument("--components", action="store_true", help="Only fetch components")
    parser.add_argument("--champions", action="store_true", help="Only fetch champions")
    parser.add_argument("--traits", action="store_true", help="Only fetch trait icons (CDragon)")
    parser.add_argument("--items", action="store_true", help="Only fetch item icons (CDragon)")
    parser.add_argument("--dry-run", action="store_true", help="Print URLs without downloading")
    parser.add_argument("--version", help="Pin a specific Data Dragon version (default: latest)")
    parser.add_argument("--debug", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(message)s",
    )

    # If no category flag is given, fetch everything; otherwise only the named ones.
    selective = any((args.components, args.champions, args.traits, args.items))
    do_components = args.components or not selective
    do_champions = args.champions or not selective
    do_traits = args.traits or not selective
    do_items = args.items or not selective

    try:
        version = args.version or get_latest_version()
    except Exception as e:
        logger.error(f"Could not fetch Data Dragon version list: {e}")
        return 1
    logger.info(f"Data Dragon version: {version}")

    item_index: dict[str, dict] = {}
    champ_index: dict[str, dict] = {}
    lol_champ_index: dict[str, dict] = {}

    if do_components:
        try:
            item_index = build_item_index(version)
            logger.info(f"Loaded {len(item_index)} TFT items from Data Dragon")
        except Exception as e:
            logger.error(f"Failed to load tft-item.json: {e}")
            return 1

    if do_champions:
        try:
            champ_index = build_champion_index(version)
            logger.info(f"Loaded {len(champ_index)} TFT champions from Data Dragon")
        except Exception as e:
            logger.warning(f"Failed to load tft-champion.json ({e}); will rely on champion.json fallback")
        try:
            lol_champ_index = build_lol_champion_index(version)
            logger.info(f"Loaded {len(lol_champ_index)} League champions (fallback)")
        except Exception as e:
            logger.warning(f"Failed to load champion.json: {e}")

    cdragon: dict = {}
    if do_traits or do_items:
        try:
            cdragon = load_cdragon_tft()
            logger.info("Loaded Community Dragon TFT data")
        except Exception as e:
            logger.error(f"Failed to load Community Dragon TFT data: {e}")
            return 1

    comp_ok = champ_ok_count = trait_ok = item_ok = 0
    comp_missing_list: list[str] = []
    champ_missing_list: list[str] = []
    trait_missing_list: list[str] = []
    item_missing_list: list[str] = []

    if do_components:
        logger.info("\n── Components ──")
        comp_ok, comp_missing_list = fetch_components(
            version, item_index, force=args.force, dry_run=args.dry_run
        )

    if do_champions:
        logger.info("\n── Champions ──")
        champ_ok_count, champ_missing_list = fetch_champions(
            version, champ_index, lol_champ_index,
            force=args.force, dry_run=args.dry_run,
        )

    if do_traits:
        logger.info("\n── Traits (Community Dragon) ──")
        trait_ok, trait_missing_list = fetch_traits(
            cdragon, force=args.force, dry_run=args.dry_run
        )

    if do_items:
        logger.info("\n── Items (Community Dragon) ──")
        item_ok, item_missing_list = fetch_items(
            cdragon, force=args.force, dry_run=args.dry_run
        )

    logger.info("\n── Summary ──")
    if do_components:
        logger.info(f"  Components: {comp_ok}/{len(COMPONENT_NAMES)} ok")
        if comp_missing_list:
            logger.info(f"    missing: {', '.join(comp_missing_list)}")
    if do_champions:
        logger.info(f"  Champions:  {champ_ok_count}/{len(CHAMPIONS)} ok")
        if champ_missing_list:
            logger.info(f"    missing: {', '.join(champ_missing_list)}")
    if do_traits:
        logger.info(f"  Traits:     {trait_ok}/{len(TRAITS)} ok")
        if trait_missing_list:
            logger.info(f"    missing: {', '.join(trait_missing_list)}")
    if do_items:
        logger.info(f"  Items:      {item_ok} ok")
        if item_missing_list:
            logger.info(f"    missing: {', '.join(item_missing_list)}")

    if not args.dry_run:
        copied = sync_frontend_icons()
        logger.info(f"  Frontend icons synced ({copied} copied)")

    any_missing = any((comp_missing_list, champ_missing_list,
                       trait_missing_list, item_missing_list))
    return 0 if not any_missing else 2


if __name__ == "__main__":
    sys.exit(main())
