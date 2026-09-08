"""
Patch-Specific Game Data
Set 18: Enchanted Wilds  |  Patch 18.1  (launch data)


"""

# ── Item Components ───────────────────────────────────────────────────────────


COMPONENT_IDS: list[str] = [
    "bf_sword", "needlessly_large_rod", "giants_belt", "chain_vest",
    "negatron_cloak", "recurve_bow", "tear", "sparring_gloves",
    "spatula", "frying_pan",
]

COMPONENT_NAMES: dict[str, str] = {
    "bf_sword":             "B.F. Sword",
    "needlessly_large_rod": "Needlessly Large Rod",
    "giants_belt":          "Giant's Belt",
    "chain_vest":           "Chain Vest",
    "negatron_cloak":       "Negatron Cloak",
    "recurve_bow":          "Recurve Bow",
    "tear":                 "Tear of the Goddess",
    "sparring_gloves":      "Sparring Gloves",
    "spatula":              "Spatula",
    "frying_pan":           "Frying Pan",
}

# ── Item Recipes ──────────────────────────────────────────────────────────────
#
# tier:  S / A / B / C  — overall item strength this patch
# type:  carry / tank / support / utility / sustain
# slam:  True = always worth slamming early
# shred: True = reduces enemy Armor or MR — prioritize vs tanky lobbies
# burn:  True = applies Grievous Wounds, Wound, or DoT — counters healing

ITEM_RECIPES: list[dict] = [
    # ── B.F. Sword ────────────────────────────────────────────────────────────
    {"recipe": ("bf_sword", "bf_sword"),             "name": "Deathblade",         "tier": "S", "type": "carry",   "slam": True, "shred": False, "burn": False},
    {"recipe": ("bf_sword", "needlessly_large_rod"), "name": "Hextech Gunblade",   "tier": "A", "type": "sustain", "slam": False, "shred": False, "burn": False},
    {"recipe": ("bf_sword", "giants_belt"),          "name": "Sterak's Gage",      "tier": "A", "type": "sustain",    "slam": False, "shred": False, "burn": False},
    {"recipe": ("bf_sword", "chain_vest"),           "name": "Edge of Night",      "tier": "A", "type": "carry",   "slam": False, "shred": False, "burn": False},
    {"recipe": ("bf_sword", "negatron_cloak"),       "name": "Bloodthirster",      "tier": "B", "type": "carry",   "slam": False, "shred": False, "burn": False},
    {"recipe": ("bf_sword", "recurve_bow"),          "name": "Giant Slayer",       "tier": "A", "type": "carry",   "slam": True,  "shred": False,  "burn": False},
    {"recipe": ("bf_sword", "tear"),                 "name": "Spear of Shojin",    "tier": "A", "type": "carry",   "slam": True,  "shred": False, "burn": False},
    {"recipe": ("bf_sword", "sparring_gloves"),      "name": "Infinity Edge",      "tier": "B", "type": "carry",   "slam": False,  "shred": False, "burn": False},

    # ── Needlessly Large Rod ──────────────────────────────────────────────────
    {"recipe": ("needlessly_large_rod", "needlessly_large_rod"), "name": "Rabadon's Deathcap",    "tier": "S", "type": "carry",   "slam": True,  "shred": False, "burn": False},
    {"recipe": ("needlessly_large_rod", "giants_belt"),          "name": "Morellonomicon",         "tier": "S", "type": "utility", "slam": True,  "shred": False, "burn": True},
    {"recipe": ("needlessly_large_rod", "chain_vest"),           "name": "Crownguard",             "tier": "S", "type": "carry",   "slam": True, "shred": False, "burn": False},
    {"recipe": ("needlessly_large_rod", "negatron_cloak"),       "name": "Ionic Spark",            "tier": "A", "type": "utility", "slam": True, "shred": True,  "burn": False},
    {"recipe": ("needlessly_large_rod", "recurve_bow"),          "name": "Guinsoo's Rageblade",    "tier": "A", "type": "carry",   "slam": True,  "shred": False, "burn": False},
    {"recipe": ("needlessly_large_rod", "tear"),                 "name": "Archangel's Staff",      "tier": "B", "type": "carry",   "slam": False, "shred": False, "burn": False},
    {"recipe": ("needlessly_large_rod", "sparring_gloves"),      "name": "Jeweled Gauntlet",       "tier": "A", "type": "carry",   "slam": True,  "shred": False, "burn": False},

    # ── Giant's Belt ──────────────────────────────────────────────────────────
    {"recipe": ("giants_belt", "giants_belt"),       "name": "Warmog's Armor",     "tier": "B", "type": "tank",    "slam": False, "shred": False, "burn": False},
    {"recipe": ("giants_belt", "chain_vest"),        "name": "Sunfire Cape",       "tier": "A", "type": "tank",    "slam": True,  "shred": False, "burn": True},
    {"recipe": ("giants_belt", "negatron_cloak"),    "name": "Evenshroud",         "tier": "B", "type": "utility", "slam": False, "shred": True,  "burn": False},
    {"recipe": ("giants_belt", "recurve_bow"),       "name": "Nashor's Tooth",     "tier": "B", "type": "carry",   "slam": False, "shred": False, "burn": False},
    {"recipe": ("giants_belt", "tear"),              "name": "Spirit Visage",      "tier": "B", "type": "tank", "slam": False, "shred": False, "burn": False},
    {"recipe": ("giants_belt", "sparring_gloves"),   "name": "Striker's Flail",    "tier": "S", "type": "carry",   "slam": True, "shred": False, "burn": False},

    # ── Chain Vest ────────────────────────────────────────────────────────────
    {"recipe": ("chain_vest", "chain_vest"),         "name": "Bramble Vest",       "tier": "A", "type": "tank",    "slam": True, "shred": False, "burn": False},
    {"recipe": ("chain_vest", "negatron_cloak"),     "name": "Gargoyle Stoneplate","tier": "A", "type": "tank",    "slam": True,  "shred": False, "burn": False},
    {"recipe": ("chain_vest", "recurve_bow"),        "name": "Titan's Resolve",    "tier": "A", "type": "tank",    "slam": True, "shred": False, "burn": False},
    {"recipe": ("chain_vest", "tear"),               "name": "Protector's Vow",    "tier": "S", "type": "tank", "slam": True, "shred": False, "burn": False},
    {"recipe": ("chain_vest", "sparring_gloves"),    "name": "Steadfast Heart",    "tier": "B", "type": "tank",    "slam": False, "shred": False, "burn": False},

    # ── Negatron Cloak ────────────────────────────────────────────────────────
    {"recipe": ("negatron_cloak", "negatron_cloak"), "name": "Dragon's Claw",      "tier": "B", "type": "tank",    "slam": False, "shred": False, "burn": False},
    {"recipe": ("negatron_cloak", "recurve_bow"),    "name": "Kraken's Fury", "tier": "B", "type": "carry",   "slam": False, "shred": False, "burn": False},
    {"recipe": ("negatron_cloak", "tear"),           "name": "Adaptive Helm",   "tier": "A", "type": "support", "slam": True, "shred": False, "burn": False},
    {"recipe": ("negatron_cloak", "sparring_gloves"),"name": "Quicksilver",        "tier": "A", "type": "carry",   "slam": False, "shred": False, "burn": False},

    # ── Recurve Bow ───────────────────────────────────────────────────────────
    {"recipe": ("recurve_bow", "recurve_bow"),       "name": "Red Buff",           "tier": "A", "type": "carry",   "slam": True, "shred": False, "burn": True},
    {"recipe": ("recurve_bow", "tear"),              "name": "Void Staff",         "tier": "A", "type": "utility",   "slam": True, "shred": True,  "burn": False},
    {"recipe": ("recurve_bow", "sparring_gloves"),   "name": "Last Whisper",    "tier": "A", "type": "utility",   "slam": True,  "shred": True, "burn": False},

    # ── Tear of the Goddess ───────────────────────────────────────────────────
    {"recipe": ("tear", "tear"),                     "name": "Blue Buff",          "tier": "B", "type": "carry",   "slam": False, "shred": False, "burn": False},
    {"recipe": ("tear", "sparring_gloves"),          "name": "Hand of Justice","tier": "A", "type": "carry", "slam": True, "shred": False, "burn": False},

    # ── Sparring Gloves ───────────────────────────────────────────────────────
    {"recipe": ("sparring_gloves", "sparring_gloves"),"name": "Thief's Gloves",   "tier": "A", "type": "carry",   "slam": False, "shred": False, "burn": False},
    # ── Spatula (Class Emblems) ─────────────────────────────────────────────────

    # Frying Pan (Class Emblems + Board Slot) ─────────────────────────────────────────

    # add radiant items later
    # add artifcats later
]

# Quick lookup sets — derived automatically from ITEM_RECIPES for easy reference in logic later
SHRED_ITEMS: set[str] = {r["name"] for r in ITEM_RECIPES if r.get("shred")}
BURN_ITEMS:  set[str] = {r["name"] for r in ITEM_RECIPES if r.get("burn")}


# Live item tiers from TFT Academy (tftacademy_live.apply_items_to_game_data
# fills this in place). Covers the craftables above PLUS radiant items,
# artifacts ("ornn" items), and emblems — none of which have a component
# recipe, so they only exist here. {normalized name: {"name","tier","kind"}}
LIVE_ITEM_TIERS: dict[str, dict] = {}
# Current display name by Riot API identifier.  Comp-detail payloads can keep
# legacy labels after an item is renamed (for example Guardian Angel while
# the current item is Edge of Night), but the API identifier remains stable.
LIVE_ITEM_NAMES_BY_API: dict[str, str] = {}
# Set-specific items that do not appear in the general item tier-list API.
# These still occur in comp layouts and have real CDragon icons.
STATIC_ITEM_NAMES_BY_API: dict[str, str] = {}


def norm_item_key(name: str) -> str:
    """Item names differ in punctuation/case across sources — compare
    alphanumerics only."""
    return "".join(c for c in name.lower() if c.isalnum())


_RECIPE_BY_KEY = {norm_item_key(r["name"]): r for r in ITEM_RECIPES}


def find_item_tier(name: str) -> tuple[str | None, str | None]:
    """
    (tier, kind) for ANY item — craftable, radiant, artifact, or emblem.
    Live TFT Academy tiers win; the static recipe table is the fallback
    for craftables. (None, None) for unknown names.
    """
    key = norm_item_key(name)
    live = LIVE_ITEM_TIERS.get(key)
    if live:
        return live["tier"], live["kind"]
    static = _RECIPE_BY_KEY.get(key)
    if static:
        return static["tier"], "craftable"
    return None, None


def find_item_name_by_api(api_name: str, fallback: str = "") -> str:
    """Resolve an item API identifier to its current in-game display name."""
    return LIVE_ITEM_NAMES_BY_API.get(
        api_name,
        STATIC_ITEM_NAMES_BY_API.get(api_name, fallback),
    )


# Validated current-set roster, traits, and offline comp seeds.
from set18_data import (  # noqa: E402
    SET_NUMBER as ACTIVE_SET_NUMBER,
    SET_NAME as ACTIVE_SET_NAME,
    ENGINE as ACTIVE_ENGINE,
    CHAMPIONS as _CURRENT_CHAMPIONS,
    TRAITS as _CURRENT_TRAITS,
    COMPS as _CURRENT_COMPS,
    LUX_FORMS,
    canonical_training_label,
)

CHAMPIONS = _CURRENT_CHAMPIONS
TRAITS = _CURRENT_TRAITS


# Live sync updates these current-set seeds when online.
COMPS = _CURRENT_COMPS
TFTACADEMY_PATCH = "18.1"
TFTACADEMY_LAST_SYNCED = ""
TFTACADEMY_SOURCE_URL = "https://tftacademy.com/tierlist/comps"
# Curated tiers and augment ratings come from the current-set cache/live sync.
META_COMPS: list[dict] = []
META_COMPS_BY_CARRY: dict[str, list[dict]] = {}
AUGMENT_RATINGS: dict[str, dict] = {}


# ── Augment lookup ────────────────────────────────────────────────────────────
# OCR output is noisy ("Heroic Grab 8ag", stray punctuation, wrong case), so
# augment lookups go exact → normalized → fuzzy instead of a plain dict hit.
# AUGMENT_RATINGS is refreshed in place by tftacademy_live, so the normalized
# index is rebuilt whenever the dict's size changes.

import difflib as _difflib
import re as _re

_AUGMENT_NORM_RE = _re.compile(r"[^a-z0-9+]+")
_augment_norm_index: dict[str, str] = {}
_augment_norm_index_size = -1


def _normalize_augment_name(name: str) -> str:
    return _AUGMENT_NORM_RE.sub("", name.lower())


def _augment_index() -> dict[str, str]:
    global _augment_norm_index, _augment_norm_index_size
    if len(AUGMENT_RATINGS) != _augment_norm_index_size:
        _augment_norm_index = {
            _normalize_augment_name(k): k for k in AUGMENT_RATINGS
        }
        _augment_norm_index_size = len(AUGMENT_RATINGS)
    return _augment_norm_index


def find_augment_rating(name: str) -> tuple[str | None, dict | None]:
    """
    Look up an (possibly OCR-mangled) augment name in AUGMENT_RATINGS.

    Returns (canonical_name, rating_data), or (None, None) when nothing in
    the database is a plausible match.
    """
    if not name:
        return None, None
    data = AUGMENT_RATINGS.get(name)
    if data:
        return name, data

    index = _augment_index()
    norm = _normalize_augment_name(name)
    key = index.get(norm)
    if key:
        return key, AUGMENT_RATINGS[key]

    close = _difflib.get_close_matches(norm, list(index), n=1, cutoff=0.8)
    if close:
        key = index[close[0]]
        return key, AUGMENT_RATINGS[key]
    return None, None


# ── Champion name lookup ──────────────────────────────────────────────────────
# Shop-card OCR is noisy the same way augment OCR is; resolve reads against
# the champion roster with the same exact → normalized → fuzzy ladder.

_champion_norm_index: dict[str, str] = {}
_CHAMPION_OCR_ALIASES = {}


def _champion_index() -> dict[str, str]:
    global _champion_norm_index
    if not _champion_norm_index:
        _champion_norm_index = {
            _normalize_augment_name(k): k for k in CHAMPIONS
        }
    return _champion_norm_index


def find_champion_name(text: str) -> str | None:
    """
    Resolve OCR'd shop-card text to a champion name, or None when the text
    doesn't plausibly match any champion (empty slot, garbage read).
    """
    if not text:
        return None
    norm = _normalize_augment_name(text)
    if len(norm) < 3:
        return None
    alias = _CHAMPION_OCR_ALIASES.get(norm)
    if alias:
        return alias
    index = _champion_index()
    key = index.get(norm)
    if key:
        return key
    close = _difflib.get_close_matches(norm, list(index), n=1, cutoff=0.75)
    if close:
        return index[close[0]]
    return None
