"""Set 18 (Enchanted Wilds) roster and trait data.

The Unreal migration changed Riot's identifiers from ``TFT18_*`` to a mix of
``DA_*`` identifiers and, at launch, CommunityDragon's normal set payload only
contains a small subset of the shop roster.  Keep the launch roster here so the
runtime never silently falls back to Set 17 when that upstream payload is
incomplete.  ``scripts/sync_set_data.py`` validates names/costs/API identifiers
against Riot Data Dragon.

Lux is deliberately represented two ways:

* ``Lux`` is the shop-OCR/training label.  Every Avatar form contributes crops
  to this one visual class; splitting nine very similar models would starve each
  class of data and is not needed when the live trait HUD supplies her origin.
* ``Lux (<Origin>)`` entries preserve exact Avatar gameplay semantics for
  fixtures, classifier imports with form labels, and trait calculations.  Her
  selected origin contributes two trait points.
"""

from __future__ import annotations

SET_NUMBER = 18
SET_NAME = "Enchanted Wilds"
ENGINE = "unreal"


# name, cost, traits, Riot Data Dragon id (when exposed there)
_ROSTER: list[tuple[str, int, tuple[str, ...], str]] = [
    # 1-cost
    ("Akali", 1, ("Inferno", "Adaptor", "Ravager"), "DA_18_Akali_AD"),
    ("Camille", 1, ("Coven", "Ravager"), "DA_18_Camille"),
    ("Cinderling", 1, ("Riftbeast", "Hunter"), "DA_18_Cinderling"),
    ("Karma", 1, ("Blossom", "Spellweaver"), "DA_Karma18"),
    ("Kobuko", 1, ("Sprykin", "Brawler"), "DA_18_Kobuko"),
    ("Leona", 1, ("Solar", "Defender"), "DA_18_Leona"),
    ("Ornn", 1, ("Elderwood", "Defender"), "DA_18_Ornn"),
    ("Pebbles", 1, ("Riftbeast", "Invoker"), "DA_18_Sentry"),
    ("Rakan", 1, ("Fae", "Juggernaut", "Vanguard"), "DA_18_Rakan"),
    ("Rek'Sai", 1, ("Blackthorn", "Brawler"), "DA_18_RekSai"),
    ("Varus", 1, ("Inferno", "Rapidfire"), "DA_18_Varus"),
    ("Veigar", 1, ("Blackthorn", "Sprykin", "Spellweaver"), "DA_18_Veigar"),
    ("Xayah", 1, ("Elderwood", "Fae", "Rapidfire"), "DA_18_Xayah"),
    ("Yorick", 1, ("Blossom", "Juggernaut", "Summoner"), "DA_18_Yorick"),

    # 2-cost
    ("Alistar", 2, ("Elderwood", "Brawler"), "DA_18_Alistar"),
    ("Caitlyn", 2, ("Coven", "Hunter"), "DA_18_Caitlyn"),
    ("Elise", 2, ("Coven", "Vanguard"), "DA_18_Elise"),
    ("Gromp", 2, ("Riftbeast", "Adaptor"), "DA_Gromp18_AP"),
    ("Kayle", 2, ("Solar", "Rapidfire"), "DA_18_Kayle"),
    ("LeBlanc", 2, ("Elderwood", "Spellweaver"), "DA_18_LeBlanc"),
    ("Murkwolf", 2, ("Riftbeast", "Ravager"), "DA_Murkwolf18"),
    ("Scuttlecrab", 2, ("Riftbeast", "Juggernaut"), "DA_Scuttlecrab18"),
    ("Sejuani", 2, ("Solar", "Juggernaut"), "DA_18_Sejuani"),
    ("Shen", 2, ("Inferno", "Defender"), "DA_18_Shen"),
    ("Teemo", 2, ("Sprykin", "Invoker"), "DA_18_Teemo"),
    ("Warwick", 2, ("Blackthorn", "Ravager"), "DA_18_Warwick"),
    ("Yunara", 2, ("Blossom", "Executioner"), "DA_18_Yunara"),

    # 3-cost
    ("Azir", 3, ("Blackthorn", "Executioner", "Summoner"), "DA_18_Azir"),
    ("Cassiopeia", 3, ("Coven", "Spellweaver"), "DA_18_Cassiopeia"),
    ("Diana", 3, ("Lunar", "Ravager", "Vanguard"), "DA_18_Diana"),
    ("Fiddlesticks", 3, ("Flora Fatalis", "Defender", "Spellweaver"), "DA_Fiddlesticks18"),
    ("Hecarim", 3, ("Elderwood", "Vanguard"), "DA_18_Hecarim"),
    ("Kha'Zix", 3, ("Rival",), "DA_18_KhaZix"),
    ("Kog'Maw", 3, ("Caustic", "Invoker", "Adaptor"), "DA_KogMaw18_AD"),
    ("Krug", 3, ("Riftbeast", "Brawler"), "DA_Krug18"),
    ("Master Yi", 3, ("Blossom", "Adaptor"), "DA_18_MasterYi_AD"),
    ("Rammus", 3, ("Sprykin", "Defender"), "DA_18_Rammus"),
    ("Mama Beak", 3, ("Riftbeast", "Summoner", "Rapidfire"), "DA_CrimsonRaptor18"),
    ("Rengar", 3, ("Rival",), "DA_18_Rengar"),
    ("Tristana", 3, ("Fae", "Sprykin", "Hunter"), "DA_18_Tristana"),
    ("Vi", 3, ("Primal", "Juggernaut"), "DA_Vi18"),

    # 4-cost
    ("Ahri", 4, ("Blossom", "Spellweaver"), "DA_18_Ahri"),
    ("Amumu", 4, ("Inferno", "Juggernaut"), "DA_Amumu18"),
    ("Ancient Sentinel", 4, ("Riftbeast", "Vanguard", "Invoker"), "DA_Sentinel18"),
    ("Aphelios", 4, ("Lunar", "Rapidfire"), "DA_18_Aphelios"),
    ("Brambleback", 4, ("Riftbeast", "Ravager"), "DA_Brambleback18"),
    ("Ezreal", 4, ("Elderwood", "Executioner"), "DA_18_Ezreal"),
    ("Lillia", 4, ("Fae", "Defender"), "DA_18_Lillia"),
    ("Malphite", 4, ("Blackthorn", "Monolith"), "DA_18_Malphite"),
    ("Morgana", 4, ("Coven", "Invoker"), "DA_18_Morgana"),
    ("Nidalee", 4, ("Primal", "Adaptor"), "DA_Nidalee18_AP"),
    ("Sett", 4, ("Blossom", "Brawler"), "DA_18_Sett"),
    ("Sivir", 4, ("Primal", "Hunter"), "DA_18_Sivir"),
    ("Soraka", 4, ("Flora Fatalis", "Executioner"), "DA_18_Soraka"),
    ("Zyra", 4, ("Thornmaiden", "Summoner"), "DA_18_Zyra"),

    # 5-cost (Lux forms are added below)
    ("Alune", 5, ("Attuned", "Lunar", "Spellweaver"), "DA_18_Alune"),
    ("Ashe", 5, ("Blossom", "Hunter"), "DA_18_Ashe"),
    ("Draven", 5, ("Bounty Seeker",), "DA_Draven18"),
    ("Elder Dragon", 5, ("Riftbeast", "Apex Predator"), "DA_18_ElderDragon"),
    ("Gnar", 5, ("Elderwood", "Sprykin", "Brawler"), "DA_18_GnarSmall"),
    ("Ivern", 5, ("Greenfather",), "DA_18_Ivern"),
    ("Kennen", 5, ("Inferno", "Executioner"), "DA_18_Kennen"),
    ("Maokai", 5, ("Old Growth", "Juggernaut"), "DA_18_Maokai"),
    ("Taric", 5, ("Emerald Aspect", "Vanguard"), "DA_Taric18"),
]


LUX_FORMS: dict[str, str] = {
    "Blackthorn": "DA_Lux18_Blackthorn",
    "Blossom": "DA_Lux18_Blossom",
    "Coven": "DA_18_Lux_Coven",
    "Elderwood": "DA_18_Lux_Elderwood",
    "Fae": "DA_18_Lux_Fae",
    "Inferno": "DA_18_Lux_Inferno",
    "Lunar": "DA_18_Lux_Moonbeam",
    "Primal": "DA_18_Lux_Primal",
    "Solar": "DA_18_Lux_Sunbeam",
}


def _power(cost: int) -> int:
    return 4 + cost * 2


CHAMPIONS: dict[str, dict] = {
    name: {
        "cost": cost,
        "traits": list(traits),
        "base_power": _power(cost),
        "api_name": api_name,
    }
    for name, cost, traits, api_name in _ROSTER
}

# Generic shop/training identity. Exact form entries below are for gameplay
# semantics; OCR intentionally resolves a card reading of just "Lux" here.
CHAMPIONS["Lux"] = {
    "cost": 5,
    "traits": ["Avatar"],
    "base_power": _power(5),
    "api_name": "DA_Lux18_Base",
    "forms": list(LUX_FORMS),
    "unique_group": "Lux",
}
for _origin, _api_name in LUX_FORMS.items():
    CHAMPIONS[f"Lux ({_origin})"] = {
        "cost": 5,
        "traits": [_origin, "Avatar"],
        "trait_points": {_origin: 2},
        "base_power": _power(5),
        "api_name": _api_name,
        "training_label": "Lux",
        "unique_group": "Lux",
    }

# Elder Dragon occupies two team slots and supplies three Riftbeast points.
CHAMPIONS["Elder Dragon"].update({
    "board_slots": 2,
    "trait_points": {"Riftbeast": 3},
})


_TRAIT_BREAKPOINTS: dict[str, list[int]] = {
    "Adaptor": [2, 3, 4],
    "Apex Predator": [1],
    "Attuned": [1],
    "Avatar": [1],
    "Blackthorn": [2, 4, 6],
    "Blossom": [3, 5, 7, 9, 11],
    "Bounty Seeker": [1],
    "Brawler": [2, 4, 6],
    "Caustic": [1],
    "Coven": [3, 4, 5, 7],
    "Defender": [2, 4, 6],
    "Eclipse": [1],
    "Elderwood": [3, 5, 7, 9, 11],
    "Emerald Aspect": [1],
    "Executioner": [2, 3, 4],
    "Fae": [2, 4],
    "Flora Fatalis": [1, 2],
    "Greenfather": [1],
    "Hunter": [2, 3, 4, 5],
    "Inferno": [2, 3, 5, 7],
    "Invoker": [2, 3, 4, 5],
    "Juggernaut": [2, 4, 6],
    "Lunar": [2, 3, 4, 5],
    "Monolith": [1],
    "Old Growth": [1],
    "Primal": [2, 4],
    "Rapidfire": [2, 3, 4, 5],
    "Ravager": [2, 4, 6],
    "Riftbeast": [3, 5, 7, 10],
    "Rival": [1, 2],
    "Solar": [3],
    "Spellweaver": [2, 4, 6],
    "Sprykin": [3, 5, 7],
    "Summoner": [2, 3],
    "Thornmaiden": [1],
    "Vanguard": [2, 4, 6],
}

_CLASSES = {
    "Adaptor", "Brawler", "Defender", "Executioner", "Hunter", "Invoker",
    "Juggernaut", "Rapidfire", "Ravager", "Spellweaver", "Summoner", "Vanguard",
}

_DESCRIPTIONS = {
    "Avatar": "Lux appears as one of nine origins; her selected origin counts twice.",
    "Blossom": "Empowers Wisps and grants Blossom champions scaling combat stats.",
    "Coven": "Gather Essence from takedowns and losses, then cash out or push for larger rewards.",
    "Elderwood": "Gain placeable plants; higher breakpoints add and star up the summons.",
    "Fae": "Damage, healing, and shielding attract Pixies that empower Fae champions.",
    "Inferno": "Burn and Wound enemies; additional burn sources stack with the trait.",
    "Riftbeast": "Field jungle monsters, culminating in the two-slot Elder Dragon.",
}

TRAITS: dict[str, dict] = {}
for _name, _breakpoints in _TRAIT_BREAKPOINTS.items():
    TRAITS[_name] = {
        "breakpoints": _breakpoints,
        "power_per_breakpoint": [8 + 10 * i for i in range(len(_breakpoints))],
        "synergy_type": "class" if _name in _CLASSES else "origin",
        "description": _DESCRIPTIONS.get(_name, "Set 18 Enchanted Wilds trait."),
    }


COMPS: list[dict] = [
    {
        "name": "Blossom Flex",
        "target_traits": [("Blossom", 7)],
        "core_units": ["Ahri", "Sett", "Ashe"],
        "flex_units": ["Karma", "Yorick", "Yunara", "Master Yi"],
        "playstyle": "Use upgraded Wisps for tempo, then cap around Ashe and a Blossom Avatar Lux.",
        "items": ["Spear of Shojin", "Jeweled Gauntlet", "Giant Slayer"],
    },
    {
        "name": "Elderwood Executioners",
        "target_traits": [("Elderwood", 7), ("Executioner", 3)],
        "core_units": ["Ezreal", "Gnar", "Hecarim"],
        "flex_units": ["Xayah", "Ornn", "Alistar", "LeBlanc"],
        "playstyle": "Build around Elderwood summons and use Ezreal as the mid-game carry.",
        "items": ["Infinity Edge", "Last Whisper", "Giant Slayer"],
    },
    {
        "name": "Coven Invokers",
        "target_traits": [("Coven", 5), ("Invoker", 3)],
        "core_units": ["Morgana", "Cassiopeia", "Caitlyn"],
        "flex_units": ["Camille", "Elise", "Kog'Maw"],
        "playstyle": "Preserve HP during the Essence cashout line and transition into Morgana.",
        "items": ["Spear of Shojin", "Jeweled Gauntlet", "Morellonomicon"],
    },
    {
        "name": "Riftbeast",
        "target_traits": [("Riftbeast", 10)],
        "core_units": ["Elder Dragon", "Ancient Sentinel", "Brambleback"],
        "flex_units": ["Krug", "Mama Beak", "Gromp", "Pebbles"],
        "playstyle": "Develop the monster board and account for Elder Dragon consuming two team slots.",
        "items": ["Warmog's Armor", "Gargoyle Stoneplate", "Spear of Shojin"],
    },
    {
        "name": "Solar Kayle",
        "target_traits": [("Solar", 3), ("Rapidfire", 4)],
        "core_units": ["Kayle", "Leona", "Sejuani"],
        "flex_units": ["Varus", "Xayah", "Aphelios"],
        "playstyle": "Reroll Kayle while preserving a durable Solar frontline.",
        "items": ["Guinsoo's Rageblade", "Kraken's Fury", "Quicksilver"],
    },
    {
        "name": "Sprykin Tristana",
        "target_traits": [("Sprykin", 5), ("Hunter", 3)],
        "core_units": ["Tristana", "Rammus", "Teemo"],
        "flex_units": ["Kobuko", "Veigar", "Gnar"],
        "playstyle": "Reroll Tristana with Sprykin utility and a stable front line.",
        "items": ["Infinity Edge", "Last Whisper", "Giant Slayer"],
    },
]


def canonical_training_label(name: str) -> str:
    """Collapse all Avatar spellings/forms into the single visual class Lux."""
    compact = "".join(ch for ch in name.lower() if ch.isalnum())
    return "Lux" if compact.startswith("lux") else name
