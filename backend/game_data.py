"""
Patch-Specific Game Data
Set 17: Space Gods  |  Patch 17.2b  (current as of May 2026)


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
    {"recipe": ("giants_belt", "sparring_gloves"),   "name": "Guardbreaker",       "tier": "S", "type": "carry",   "slam": True, "shred": False, "burn": True},

    # ── Chain Vest ────────────────────────────────────────────────────────────
    {"recipe": ("chain_vest", "chain_vest"),         "name": "Bramble Vest",       "tier": "A", "type": "tank",    "slam": True, "shred": False, "burn": False},
    {"recipe": ("chain_vest", "negatron_cloak"),     "name": "Gargoyle Stoneplate","tier": "A", "type": "tank",    "slam": True,  "shred": False, "burn": False},
    {"recipe": ("chain_vest", "recurve_bow"),        "name": "Titan's Resolve",    "tier": "A", "type": "tank",    "slam": True, "shred": False, "burn": False},
    {"recipe": ("chain_vest", "tear"),               "name": "Protector's Vow",    "tier": "S", "type": "tank", "slam": True, "shred": False, "burn": False},
    {"recipe": ("chain_vest", "sparring_gloves"),    "name": "Steadfast Heart",    "tier": "B", "type": "tank",    "slam": False, "shred": False, "burn": False},

    # ── Negatron Cloak ────────────────────────────────────────────────────────
    {"recipe": ("negatron_cloak", "negatron_cloak"), "name": "Dragon's Claw",      "tier": "B", "type": "tank",    "slam": False, "shred": False, "burn": False},
    {"recipe": ("negatron_cloak", "recurve_bow"),    "name": "Kraken Slayer ", "tier": "B", "type": "carry",   "slam": False, "shred": False, "burn": False},
    {"recipe": ("negatron_cloak", "tear"),           "name": "Jaksho",   "tier": "A", "type": "support", "slam": True, "shred": False, "burn": False},
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


# ── Champion Data  (Set 17: Space Gods) ───────────────────────────────────────
# cost:       1–5 gold cost tier
# traits:     trait names this champion contributes to (from in-game data)
# base_power: rough relative strength 1–15 (used in board power calc) #fix later
# TODO: add what type they are such as magic/physical and positions -> tank or caster or attacker
# !! UPDATE THIS DICT each new set — add/remove units, verify trait lists !!

CHAMPIONS: dict[str, dict] = {
    # ── Cost 1 (14 units) ─────────────────────────────────────────────────────
    "Aatrox":        {"cost": 1, "traits": ["N.O.V.A.", "Bastion"],               "base_power": 6},
    "Briar":         {"cost": 1, "traits": ["Anima", "Primordian", "Rogue"],      "base_power": 6},
    "Caitlyn":       {"cost": 1, "traits": ["N.O.V.A.", "Fateweaver"],            "base_power": 6},
    "Cho'Gath":      {"cost": 1, "traits": ["Dark Star", "Brawler"],              "base_power": 6},
    "Ezreal":        {"cost": 1, "traits": ["Timebreaker", "Sniper"],             "base_power": 6},
    "Leona":         {"cost": 1, "traits": ["Arbiter", "Vanguard"],               "base_power": 6},
    "Lissandra":     {"cost": 1, "traits": ["Dark Star", "Shepherd", "Replicator"],"base_power": 6},
    "Nasus":         {"cost": 1, "traits": ["Space Groove", "Vanguard"],          "base_power": 6},
    "Poppy":         {"cost": 1, "traits": ["Meeple", "Bastion"],                 "base_power": 6},
    "Rek'Sai":       {"cost": 1, "traits": ["Primordian", "Brawler"],             "base_power": 5},
    "Talon":         {"cost": 1, "traits": ["Stargazer", "Rogue"],                "base_power": 6},
    "Teemo":         {"cost": 1, "traits": ["Space Groove", "Shepherd"],          "base_power": 5},
    "Twisted Fate":  {"cost": 1, "traits": ["Stargazer", "Fateweaver"],           "base_power": 6},
    "Veigar":        {"cost": 1, "traits": ["Meeple", "Replicator"],              "base_power": 5},

    # ── Cost 2 (13 units) ─────────────────────────────────────────────────────
    "Akali":         {"cost": 2, "traits": ["N.O.V.A.", "Marauder"],              "base_power": 8},
    "Bel'Veth":      {"cost": 2, "traits": ["Primordian", "Challenger", "Marauder"],"base_power": 8},
    "Gnar":          {"cost": 2, "traits": ["Meeple", "Sniper"],                  "base_power": 7},
    "Gragas":        {"cost": 2, "traits": ["Psionic", "Brawler"],                "base_power": 7},
    "Gwen":          {"cost": 2, "traits": ["Space Groove", "Rogue"],             "base_power": 8},
    "Jax":           {"cost": 2, "traits": ["Stargazer", "Bastion"],              "base_power": 7},
    "Jinx":          {"cost": 2, "traits": ["Anima", "Challenger"],               "base_power": 8},
    "Meepsie":       {"cost": 2, "traits": ["Meeple", "Shepherd", "Voyager"],     "base_power": 7},
    "Milio":         {"cost": 2, "traits": ["Timebreaker", "Fateweaver"],         "base_power": 7},
    "Mordekaiser":   {"cost": 2, "traits": ["Dark Star", "Conduit", "Vanguard"],  "base_power": 8},
    "Pantheon":      {"cost": 2, "traits": ["Timebreaker", "Brawler", "Replicator"],"base_power": 7},
    "Pyke":          {"cost": 2, "traits": ["Psionic", "Voyager"],                "base_power": 7},
    "Zoe":           {"cost": 2, "traits": ["Arbiter", "Conduit"],                "base_power": 8},

    # ── Cost 3 (13 units) ─────────────────────────────────────────────────────
    "Aurora":        {"cost": 3, "traits": ["Anima", "Voyager"],                  "base_power": 9},
    "Diana":         {"cost": 3, "traits": ["Arbiter", "Challenger"],             "base_power": 9},
    "Fizz":          {"cost": 3, "traits": ["Meeple", "Rogue"],                   "base_power": 8},
    "Illaoi":        {"cost": 3, "traits": ["Anima", "Vanguard", "Shepherd"],     "base_power": 9},
    "Kai'Sa":        {"cost": 3, "traits": ["Dark Star", "Rogue"],                "base_power": 10},
    "Lulu":          {"cost": 3, "traits": ["Stargazer", "Replicator"],           "base_power": 8},
    "Maokai":        {"cost": 3, "traits": ["N.O.V.A.", "Brawler"],               "base_power": 8},
    "Miss Fortune":  {"cost": 3, "traits": ["Gun Goddess"],                       "base_power": 11},
    "Ornn":          {"cost": 3, "traits": ["Space Groove", "Bastion"],           "base_power": 8},
    "Rhaast":        {"cost": 3, "traits": ["Redeemer"],                          "base_power": 9},
    "Samira":        {"cost": 3, "traits": ["Space Groove", "Sniper"],            "base_power": 9},
    "Urgot":         {"cost": 3, "traits": ["Mecha", "Brawler", "Marauder"],      "base_power": 9},
    "Viktor":        {"cost": 3, "traits": ["Psionic", "Conduit"],                "base_power": 10},

    # ── Cost 4 (13 units) ─────────────────────────────────────────────────────
    "Aurelion Sol":  {"cost": 4, "traits": ["Mecha", "Conduit"],                  "base_power": 11},
    "Corki":         {"cost": 4, "traits": ["Meeple", "Fateweaver"],              "base_power": 11},
    "Karma":         {"cost": 4, "traits": ["Dark Star", "Voyager"],              "base_power": 12},
    "Kindred":       {"cost": 4, "traits": ["N.O.V.A.", "Challenger"],            "base_power": 11},
    "LeBlanc":       {"cost": 4, "traits": ["Arbiter", "Shepherd"],               "base_power": 11},
    "Master Yi":     {"cost": 4, "traits": ["Psionic", "Marauder"],               "base_power": 11},
    "Nami":          {"cost": 4, "traits": ["Space Groove", "Replicator"],        "base_power": 10},
    "Nunu":          {"cost": 4, "traits": ["Stargazer", "Vanguard"],             "base_power": 10},
    "Rammus":        {"cost": 4, "traits": ["Meeple", "Bastion"],                 "base_power": 10},
    "Riven":         {"cost": 4, "traits": ["Timebreaker", "Rogue"],              "base_power": 12},
    "Tahm Kench":    {"cost": 4, "traits": ["Oracle", "Brawler"],                 "base_power": 10},
    "The Mighty Mech":{"cost": 4, "traits": ["Mecha", "Voyager"],                 "base_power": 12},
    "Xayah":         {"cost": 4, "traits": ["Stargazer", "Sniper"],               "base_power": 12},

    # ── Cost 5 (10 units) ─────────────────────────────────────────────────────
    "Bard":          {"cost": 5, "traits": ["Meeple", "Conduit"],                 "base_power": 12},
    "Blitzcrank":    {"cost": 5, "traits": ["Party Animal", "Space Groove", "Vanguard"],"base_power": 15},
    "Fiora":         {"cost": 5, "traits": ["Divine Duelist", "Anima", "Marauder"],"base_power": 14},
    "Graves":        {"cost": 5, "traits": ["Factory New"],                       "base_power": 14},
    "Jhin":          {"cost": 5, "traits": ["Dark Star", "Eradicator", "Sniper"], "base_power": 15},
    "Morgana":       {"cost": 5, "traits": ["Dark Lady"],                         "base_power": 14},
    "Shen":          {"cost": 5, "traits": ["Bulwark", "Bastion"],                "base_power": 13},
    "Sona":          {"cost": 5, "traits": ["Commander", "Psionic", "Shepherd"],  "base_power": 14},
    "Vex":           {"cost": 5, "traits": ["Doomer"],                            "base_power": 14},
    "Zed":           {"cost": 5, "traits": ["Galaxy Hunter"],                     "base_power": 13},
}


# ── Trait Data  (Set 17: Space Gods) ─────────────────────────────────────────
# breakpoints:          unit counts that activate each tier
# power_per_breakpoint: board power bonus added at each tier **edit later
# synergy_type:         "origin" or "class"
# description:          in-game effect summary
#
# !! UPDATE THIS DICT each new set !!

TRAITS: dict[str, dict] = {
    # ── Origins ───────────────────────────────────────────────────────────────
    "Anima": {
        "breakpoints": [3, 6],
        "power_per_breakpoint": [12, 30],
        "synergy_type": "origin",
        "description": "Loss-streak trait: gain Tech on losses, prototype Anima Weapons at 100 Tech. (3) start researching; (6) gain loot orb on wins too.",
    },
    "Arbiter": {
        "breakpoints": [2, 3],
        "power_per_breakpoint": [10, 22],
        "synergy_type": "origin",
        "description": "Subscribe to a divine law — choose a trigger and effect. (3) effects become stronger.",
    },
    "Dark Star": {
        "breakpoints": [2, 4, 6, 9],
        "power_per_breakpoint": [15, 35, 60, 100],
        "synergy_type": "origin",
        "description": "Create a black hole that executes enemies below threshold HP. (4) +45% AD/AP; (6) strongest unit goes supermassive; (9) all supermassive — at lvl 10, CONSUME EVERYONE.",
    },
    "Mecha": {
        "breakpoints": [3, 4, 6],
        "power_per_breakpoint": [20, 35, 60],
        "synergy_type": "origin",
        "description": "Transform into Ultimate Form (+40% HP, upgraded ability, uses 2 board slots). (3) +25% AD/AP; (4) +45% AD/AP; (6) +1 max team size.",
    },
    "Meeple": {
        "breakpoints": [3, 5, 7, 10],
        "power_per_breakpoint": [10, 25, 45, 80],
        "synergy_type": "origin",
        "description": "Attract Meeps that empower abilities; Meeples gain bonus HP. (7) creates a Cloning Slot on bench; (10) SUMMON THE FOUR MEEPLORDS.",
    },
    "N.O.V.A.": {
        "breakpoints": [2, 5],
        "power_per_breakpoint": [12, 35],
        "synergy_type": "origin",
        "description": "6s into combat, grant power surge to allies based on champion count. (5) gain a Striker selector — chosen N.O.V.A. activates their Strike during surge.",
    },
    "Primordian": {
        "breakpoints": [2, 3],
        "power_per_breakpoint": [10, 25],
        "synergy_type": "origin",
        "description": "Dealing damage spawns Swarmlings based on star level. (3) spawn 45% more; gain a random 1-2 cost unit after player combat.",
    },
    "Space Groove": {
        "breakpoints": [1, 3, 5, 7, 10],
        "power_per_breakpoint": [5, 15, 30, 50, 80],
        "synergy_type": "origin",
        "description": "Groovians enter The Groove, gaining stacking AS and HP Regen. (3) all start in Groove; (5) each second in Groove grants +5% stacking AD/AP; (7) +10% to all effects; (10) MAXIMIZE the Groove.",
    },
    "Stargazer": {
        "breakpoints": [3, 4, 5, 6],
        "power_per_breakpoint": [12, 22, 35, 50],
        "synergy_type": "origin",
        "description": "Chart a random constellation each game (Altar/Boar/Fountain/Huntress/Medallion/Mountain/Serpent); units in empowered hexes gain constellation-specific bonuses.",
    },
    "Timebreaker": {
        "breakpoints": [2, 3, 4],
        "power_per_breakpoint": [10, 20, 40],
        "synergy_type": "origin",
        "description": "(2) allies gain 15% AS; (3) lose → free rerolls, win → store XP in Temporal Core; (4) Timebreakers gain additional 50% AS.",
    },

    # ── Classes ───────────────────────────────────────────────────────────────
    "Bastion": {
        "breakpoints": [2, 4, 6],
        "power_per_breakpoint": [8, 20, 40],
        "synergy_type": "class",
        "description": "Stacking Armor and Magic Resist. (2) 16; (4) 40; (6) 60 — non-Bastions also gain 20 Armor/MR at (6).",
    },
    "Brawler": {
        "breakpoints": [2, 4, 6],
        "power_per_breakpoint": [5, 15, 30],
        "synergy_type": "class",
        "description": "Bonus max HP for all units. (2) +25%; (4) +45%; (6) +65%.",
    },
    "Challenger": {
        "breakpoints": [2, 3, 4, 5],
        "power_per_breakpoint": [10, 18, 30, 45],
        "synergy_type": "class",
        "description": "Team gains AS; Challengers gain more. On kill, dash and boost AS bonus by 50% for 2.5s. (2) 15%; (3) 22%; (4) 40%; (5) 55%.",
    },
    "Conduit": {
        "breakpoints": [2, 3, 4, 5],
        "power_per_breakpoint": [8, 15, 25, 40],
        "synergy_type": "class",
        "description": "Innate: Conduits gain 20% extra Mana from all sources. Team gains Mana Regen (more for Conduits). (2/3/4/5) 1-3/1-5/2-7/3-9 regen.",
    },
    "Fateweaver": {
        "breakpoints": [2, 4],
        "power_per_breakpoint": [10, 25],
        "synergy_type": "class",
        "description": "(2) Chance effects on abilities are Lucky; (4) +20% Crit Chance/Damage — critical strikes are also Lucky.",
    },
    "Marauder": {
        "breakpoints": [2, 4, 6],
        "power_per_breakpoint": [8, 18, 35],
        "synergy_type": "class",
        "description": "Team gains Omnivamp; Marauders gain more Omnivamp, AD, and overheal → shield. (2) 5% Omni/20% AD; (4) 7%/40%; (6) 10%/60%.",
    },
    "Psionic": {
        "breakpoints": [2, 4],
        "power_per_breakpoint": [15, 35],
        "synergy_type": "class",
        "description": "(2) Gain Psionic item 1; (4) Gain Psionic item 2 — Psionic items gain extra effects on Psionic units.",
    },
    "Replicator": {
        "breakpoints": [2, 4],
        "power_per_breakpoint": [8, 20],
        "synergy_type": "class",
        "description": "Replicator abilities trigger a second time at reduced effectiveness. (2) 22% strength; (4) 45% strength.",
    },
    "Rogue": {
        "breakpoints": [2, 3, 4, 5],
        "power_per_breakpoint": [10, 22, 38, 55],
        "synergy_type": "class",
        "description": "Gain AD/AP. First time below 50% HP, slip into shadows and redirect enemy targeting. (2) 12%; (3) 25%; (4) 40%; (5) 55%.",
    },
    "Shepherd": {
        "breakpoints": [3, 5, 7],
        "power_per_breakpoint": [12, 28, 50],
        "synergy_type": "class",
        "description": "Summon Bond of the Stars units to fight alongside your team. (3) summon Bia; (5) summon Bayin; (7) Bia and Bayin's bond grows deeper.",
    },
    "Sniper": {
        "breakpoints": [2, 3, 4, 5],
        "power_per_breakpoint": [10, 20, 32, 45],
        "synergy_type": "class",
        "description": "Damage amp, increased the farther away the target. (2) 18%+2%/hex; (3) 24%+3%/hex; (4) 28%+4%/hex; (5) 32%+5%/hex.",
    },
    "Vanguard": {
        "breakpoints": [2, 4, 6],
        "power_per_breakpoint": [8, 18, 32],
        "synergy_type": "class",
        "description": "+5% Durability while shielded. At combat start and 50% HP, gain max HP shield for 10s. (2) 16% HP; (4) 30%; (6) 40% + 8% DR while shielded.",
    },
    "Voyager": {
        "breakpoints": [2, 3, 4, 5, 6],
        "power_per_breakpoint": [8, 15, 22, 32, 45],
        "synergy_type": "class",
        "description": "Combat start: tanks gain Shield; other allies gain Damage Amp; Voyagers get double. (2) 175 shield/9% DA; up to (6) 700 shield/27% DA.",
    },

    # ── Unique (1-unit) traits — automatically active when the unit is fielded ──
    "Bulwark": {
        "breakpoints": [1],
        "power_per_breakpoint": [20],
        "synergy_type": "origin",
        "description": "Shen: summon a placeable relic granting adjacent allies 18% max HP shield and 20% AS.",
    },
    "Commander": {
        "breakpoints": [1],
        "power_per_breakpoint": [18],
        "synergy_type": "origin",
        "description": "Sona: grants a random Command Mod every 2 rounds to alter an ally's combat behavior.",
    },
    "Dark Lady": {
        "breakpoints": [1],
        "power_per_breakpoint": [15],
        "synergy_type": "origin",
        "description": "Morgana: allies take 5% less ability damage, increased to 10% while Morgana is in Dark Form.",
    },
    "Divine Duelist": {
        "breakpoints": [1],
        "power_per_breakpoint": [20],
        "synergy_type": "origin",
        "description": "Fiora: heals tactician for 15% of player damage on wins; Fiora always wins a 1v1 duel.",
    },
    "Doomer": {
        "breakpoints": [1],
        "power_per_breakpoint": [18],
        "synergy_type": "origin",
        "description": "Vex: marks all enemies with Doom; first damage taken steals 12% AD/AP from each enemy.",
    },
    "Eradicator": {
        "breakpoints": [1],
        "power_per_breakpoint": [20],
        "synergy_type": "origin",
        "description": "Jhin: enemies have 10% less Armor and Magic Resist (passive shred for the whole team).",
    },
    "Factory New": {
        "breakpoints": [1],
        "power_per_breakpoint": [15],
        "synergy_type": "origin",
        "description": "Graves: after combat, open armory to purchase permanent upgrades for Graves.",
    },
    "Galaxy Hunter": {
        "breakpoints": [1],
        "power_per_breakpoint": [15],
        "synergy_type": "origin",
        "description": "Zed: while at least one clone is alive, Zed gains 40% bonus AD.",
    },
    "Gun Goddess": {
        "breakpoints": [1],
        "power_per_breakpoint": [18],
        "synergy_type": "origin",
        "description": "Miss Fortune: choose Conduit/Challenger/Replicator Mode, granting a unique ability and the chosen trait.",
    },
    "Oracle": {
        "breakpoints": [1],
        "power_per_breakpoint": [15],
        "synergy_type": "origin",
        "description": "Tahm Kench: every 3 rounds, grants a random reward.",
    },
    "Party Animal": {
        "breakpoints": [1],
        "power_per_breakpoint": [15],
        "synergy_type": "origin",
        "description": "Blitzcrank: once per combat, below 45% HP become untargetable and repair 15% max HP/second.",
    },
    "Redeemer": {
        "breakpoints": [1],
        "power_per_breakpoint": [12],
        "synergy_type": "origin",
        "description": "Rhaast: for each non-unique active trait, team gains 2-4% AS and 2-4 Armor/MR.",
    },
}


# ── Comp Templates  (Set 17: Space Gods) ─────────────────────────────────────
# Each comp lists the traits it wants and the key champions that fill it.
# `target_traits` are (trait_name, target_count) — the headline breakpoint
# the comp aims to hit. `core_units` are the carries / keystone units; the
# comp is identifiable as soon as 2-3 of these are on the board.
# `flex_units` round out the comp once the cores are found.
#
# !! UPDATE per patch as the meta shifts !!

COMPS: list[dict] = [
    {
        "name": "5 Meeple Reroll",
        "target_traits": [("Meeple", 5)],
        "core_units": ["Veigar", "Poppy", "Gnar", "Fizz", "Meepsie"],
        "flex_units": ["Corki", "Rammus", "Bard"],
        "playstyle": "Slow-roll level 6-7 to 3-star Meeple 1-cost units. Meeps stack damage on abilities — itemize Veigar or Fizz as primary carry.",
        "items": ["Jeweled Gauntlet", "Spear of Shojin", "Crownguard"],
    },
    {
        "name": "6 Dark Star",
        "target_traits": [("Dark Star", 6)],
        "core_units": ["Kai'Sa", "Karma", "Jhin"],
        "flex_units": ["Lissandra", "Mordekaiser", "Bard"],
        "playstyle": "Fast-8 comp. Black holes execute low-HP enemies and supermassive units carry late game. Jhin/Kai'Sa as carries.",
        "items": ["Guinsoo's Rageblade", "Last Whisper", "Infinity Edge"],
    },
    {
        "name": "5 Space Groove",
        "target_traits": [("Space Groove", 5)],
        "core_units": ["Samira", "Ornn", "Nami"],
        "flex_units": ["Nasus", "Teemo", "Gwen", "Blitzcrank"],
        "playstyle": "Stacking AS/AD/AP scales hard the longer combat goes. Frontline-heavy comp — itemize Samira or Gwen as primary carry.",
        "items": ["Guinsoo's Rageblade", "Bloodthirster", "Sterak's Gage"],
    },
    {
        "name": "5 N.O.V.A.",
        "target_traits": [("N.O.V.A.", 5)],
        "core_units": ["Kindred", "Akali", "Maokai"],
        "flex_units": ["Aatrox", "Caitlyn"],
        "playstyle": "Pick a Striker (usually Kindred or Akali) for the chosen-Strike at 5-trait. Surge timing wins fights at 6 seconds.",
        "items": ["Giant Slayer", "Infinity Edge", "Spear of Shojin"],
    },
    {
        "name": "6 Brawler",
        "target_traits": [("Brawler", 6)],
        "core_units": ["Tahm Kench", "Urgot", "Maokai"],
        "flex_units": ["Cho'Gath", "Rek'Sai", "Gragas", "Pantheon"],
        "playstyle": "65% bonus HP makes any unit a tank. Stack a 4-cost AD carry like Urgot or splash a backline carry behind 6 Brawler frontline.",
        "items": ["Warmog's Armor", "Sunfire Cape", "Bramble Vest"],
    },
    {
        "name": "Stargazer Sniper",
        "target_traits": [("Stargazer", 5), ("Sniper", 4)],
        "core_units": ["Xayah", "Samira"],
        "flex_units": ["Talon", "Twisted Fate", "Jax", "Lulu", "Nunu", "Gnar", "Ezreal"],
        "playstyle": "Constellation-buffed Xayah carry from the corner. Snipers amp damage by hex distance — keep her far from melee.",
        "items": ["Giant Slayer", "Last Whisper", "Infinity Edge"],
    },
    {
        "name": "Anima Loss-Streak",
        "target_traits": [("Anima", 6)],
        "core_units": ["Jinx", "Aurora", "Illaoi"],
        "flex_units": ["Briar"],
        "playstyle": "Loss-streak through stage 2-3 to stack Tech, then transition. Jinx with Anima Weapons is a primary carry late.",
        "items": ["Guinsoo's Rageblade", "Last Whisper", "Bloodthirster"],
    },
    {
        "name": "6 Vanguard",
        "target_traits": [("Vanguard", 6), ("Bastion", 4)],
        "core_units": ["Blitzcrank", "Nunu", "Mordekaiser"],
        "flex_units": ["Leona", "Nasus", "Illaoi"],
        "playstyle": "Wall of shields. Pair with a flex 4-5-cost backline carry — itemize the carry, not the tanks.",
        "items": ["Crownguard", "Sunfire Cape", "Protector's Vow"],
    },
    {
        "name": "Mecha Voyagers",
        "target_traits": [("Mecha", 4), ("Voyager", 4)],
        "core_units": ["Aurelion Sol", "The Mighty Mech", "Urgot"],
        "flex_units": ["Pyke", "Meepsie", "Karma"],
        "playstyle": "Mecha Ultimate Form (4) makes The Mighty Mech a monster. Voyager (4) shields tanks and amps backline. Itemize Aurelion Sol.",
        "items": ["Jeweled Gauntlet", "Rabadon's Deathcap", "Spear of Shojin"],
    },
    {
        "name": "4 Psionic",
        "target_traits": [("Psionic", 4)],
        "core_units": ["Viktor", "Sona", "Master Yi"],
        "flex_units": ["Gragas", "Pyke"],
        "playstyle": "Free Psionic items at 2 and 4 traits — they grow stronger on Psionic units. Viktor or Master Yi as carry.",
        "items": ["Jeweled Gauntlet", "Hand of Justice", "Quicksilver"],
    },
    {
        "name": "Marauder Reroll",
        "target_traits": [("Marauder", 6)],
        "core_units": ["Akali", "Bel'Veth", "Urgot"],
        "flex_units": ["Master Yi", "Fiora"],
        "playstyle": "Reroll level 7 for 2-cost Marauder 3-stars. Omnivamp + AD scaling makes Bel'Veth a frontline-bruiser carry.",
        "items": ["Bloodthirster", "Sterak's Gage", "Hand of Justice"],
    },
    {
        "name": "Gun Goddess Flex",
        "target_traits": [("Gun Goddess", 1)],
        "core_units": ["Miss Fortune"],
        "flex_units": ["Samira", "Caitlyn", "Gnar", "Xayah", "Ezreal"],
        "playstyle": "Miss Fortune picks a mode (Conduit/Challenger/Replicator) — build her trait around it. Versatile flex carry into many trait shells.",
        "items": ["Spear of Shojin", "Guinsoo's Rageblade", "Last Whisper"],
    },
]


# ── TFT Academy Tier Data  (Set 17: Space Gods, Patch 17.2b) ─────────────────
# Source: tftacademy.com/tierlist/comps
# Last synced: 2026-05-08
#
# Their tier list is curated by Frodan/Dishsoap and updated each patch. Refresh
# by running:  python scripts/sync_tftacademy.py
#
# Notes on the ratings:
#   tier:   S / A / B / C / X (X = situational / portal-only / niche carry)
#   trend:  rising / falling / new / "" (no marker on TFT Academy)
#   carry:  primary carry the comp is built around — used to match this entry
#           against detected board champions
#   match_traits: which trait names are diagnostic of this comp; helps map
#           detected synergies onto the right entry when names diverge
#
# !! KEEP NAMES EXACTLY AS THEY APPEAR ON TFT ACADEMY so the sync script can
#    update entries in place rather than introducing duplicates !!

TFTACADEMY_PATCH = "17.2b"
TFTACADEMY_LAST_SYNCED = "2026-05-08"
TFTACADEMY_SOURCE_URL = "https://tftacademy.com/tierlist/comps"

META_COMPS: list[dict] = [
    # ── S Tier ────────────────────────────────────────────────────────────────
    {"name": "Yi Marawlers",       "tier": "S", "trend": "rising",  "carry": "Master Yi",     "match_traits": ["Marauder", "Psionic"]},
    {"name": "Dark Star",          "tier": "S", "trend": "rising",  "carry": "Jhin",          "match_traits": ["Dark Star"]},
    {"name": "Primordian Reroll",  "tier": "S", "trend": "",        "carry": "Briar",         "match_traits": ["Primordian"]},

    # ── A Tier ────────────────────────────────────────────────────────────────
    {"name": "Fountain Lulu",      "tier": "A", "trend": "rising",  "carry": "Lulu",          "match_traits": ["Stargazer"]},
    {"name": "Vanguard Teemo",     "tier": "A", "trend": "",        "carry": "Teemo",         "match_traits": ["Vanguard", "Space Groove"]},
    {"name": "TF Reroll",          "tier": "A", "trend": "",        "carry": "Twisted Fate",  "match_traits": ["Stargazer", "Fateweaver"]},
    {"name": "Corki Riven",        "tier": "A", "trend": "rising",  "carry": "Corki",         "match_traits": ["Meeple", "Fateweaver"]},
    {"name": "Graves Vex 9.5",     "tier": "A", "trend": "falling", "carry": "Vex",           "match_traits": ["Doomer", "Factory New"]},

    # ── B Tier ────────────────────────────────────────────────────────────────
    {"name": "Voyager Crab",       "tier": "B", "trend": "falling", "carry": "Urgot",         "match_traits": ["Voyager", "Mecha"]},
    {"name": "Fast 9 Jhin Stargazer","tier": "B","trend": "falling","carry": "Xayah",         "match_traits": ["Stargazer", "Sniper"]},
    {"name": "Kaisa Karma",        "tier": "B", "trend": "new",     "carry": "Kai'Sa",        "match_traits": ["Dark Star"]},
    {"name": "Veigar Printer",     "tier": "B", "trend": "",        "carry": "Veigar",        "match_traits": ["Meeple", "Replicator"]},
    {"name": "Samira Knock-Up",    "tier": "B", "trend": "falling", "carry": "Samira",        "match_traits": ["Space Groove", "Sniper"]},

    # ── C Tier ────────────────────────────────────────────────────────────────
    {"name": "Karma LB Duo",       "tier": "C", "trend": "",        "carry": "LeBlanc",       "match_traits": ["Dark Star", "Arbiter"]},
    {"name": "Mecha Sol",          "tier": "C", "trend": "",        "carry": "Aurelion Sol",  "match_traits": ["Mecha", "Conduit"]},
    {"name": "Ez Cho",             "tier": "C", "trend": "",        "carry": "Cho'Gath",      "match_traits": ["Brawler", "Dark Star"]},
    {"name": "Karnami Flex",       "tier": "C", "trend": "",        "carry": "Karma",         "match_traits": ["Dark Star", "Space Groove"]},
    {"name": "In the Groove",      "tier": "C", "trend": "falling", "carry": "Nami",          "match_traits": ["Space Groove"]},
    {"name": "Vanguard Zoe",       "tier": "C", "trend": "",        "carry": "Zoe",           "match_traits": ["Vanguard", "Arbiter"]},
    {"name": "Viktor B4L",         "tier": "C", "trend": "falling", "carry": "Viktor",        "match_traits": ["Psionic", "Conduit"]},
    {"name": "Anima Reroll",       "tier": "C", "trend": "",        "carry": "Aurora",        "match_traits": ["Anima"]},

    # ── X Tier (situational / portal-or-augment-only carries) ─────────────────
    {"name": "Invader Zed",            "tier": "X", "trend": "", "carry": "Zed",          "match_traits": ["Galaxy Hunter"]},
    {"name": "Shieldmaiden Leona",     "tier": "X", "trend": "", "carry": "Leona",        "match_traits": ["Arbiter", "Vanguard"]},
    {"name": "Self-Destruct Gragas",   "tier": "X", "trend": "", "carry": "Gragas",       "match_traits": ["Psionic", "Brawler"]},
    {"name": "Terminal Velocity Poppy","tier": "X", "trend": "", "carry": "Poppy",        "match_traits": ["Meeple", "Bastion"]},
    {"name": "Bonk Nasus",             "tier": "X", "trend": "", "carry": "Nasus",        "match_traits": ["Space Groove", "Vanguard"]},
    {"name": "Contract Killer Pyke",   "tier": "X", "trend": "", "carry": "Pyke",         "match_traits": ["Psionic", "Voyager"]},
    {"name": "The Big Bang Meepsie",   "tier": "X", "trend": "", "carry": "Meepsie",      "match_traits": ["Meeple"]},
    {"name": "Stellar Combo Aatrox",   "tier": "X", "trend": "", "carry": "Aatrox",       "match_traits": ["N.O.V.A.", "Bastion"]},
    {"name": "Reach for the Stars Jax","tier": "X", "trend": "", "carry": "Jax",          "match_traits": ["Stargazer", "Bastion"]},
    {"name": "Heat Death Mordekaiser", "tier": "X", "trend": "", "carry": "Mordekaiser",  "match_traits": ["Dark Star", "Vanguard"]},
]

# Helpers built off META_COMPS — derived once at import.
META_COMPS_BY_CARRY: dict[str, list[dict]] = {}
for _entry in META_COMPS:
    META_COMPS_BY_CARRY.setdefault(_entry["carry"], []).append(_entry)


# ── Augment Ratings  (Set 17: Space Gods, Patch 17.2b) ───────────────────────
# rating: S / A / B / C
# tip:    concise strategic advice for this augment
# Change later, not fully correct wth all augments or rating

AUGMENT_RATINGS: dict[str, dict] = {
    # ── S Tier ────────────────────────────────────────────────────────────────
    "A Magic Roll":         {"rating": "S", "tip": "Free rolls — accelerate your comp without spending gold. Nearly always correct to take."},
    "Cosmic Restart":       {"rating": "S", "tip": "Econ and trait reset — excellent for pivoting into a stronger late-game comp."},
    "Feed the Flames":      {"rating": "S", "tip": "Items and combat synergy. Strong at all stages of the game."},
    "Heroic Grab Bag":      {"rating": "S", "tip": "Free high-value components — speeds up item completion by a full round."},
    "Heroic Grab Bag+":     {"rating": "S", "tip": "Upgraded Heroic Grab Bag; even more components. Take whenever offered."},
    "Rolling For Days I":   {"rating": "S", "tip": "Extra rerolls per round — great for reroll comps or finding key upgrades."},
    "Band of Thieves":      {"rating": "S", "tip": "Free items after player combat. Slam immediately — more items = more board power."},
    "Replication":          {"rating": "S", "tip": "Item duplication — effectively doubles your best item's contribution."},
    "Patient Study":        {"rating": "S", "tip": "Passive econ augment. Scale toward 50g interest with less pressure."},
    "Exiles II":            {"rating": "S", "tip": "Huge combat advantage when isolating units. Pairs well with corner-carry positioning."},

    # ── A Tier ────────────────────────────────────────────────────────────────
    "Best Friends I":       {"rating": "A", "tip": "Combat enhancement for paired units. Strong in 2-star-heavy boards."},
    "Bonk!":                {"rating": "A", "tip": "Trait carry bonus. Excellent when you are already committed to a synergy."},
    "Component Grab Bag":   {"rating": "A", "tip": "More components = more completed items. Good at any stage."},
    "Exclusive Customization":{"rating": "A", "tip": "Economy tool for flexible item building — helps complete your carry's kit."},
    "Group Hug I":          {"rating": "A", "tip": "Healing after combat. Useful when loss-streaking to buy extra time."},
    "Legion of Threes":     {"rating": "A", "tip": "Item rewards for running 3-star units. Scales with reroll comps."},
    "Patience is a Virtue": {"rating": "A", "tip": "Economy augment. Hold 50g+ and this pays for itself quickly."},
    "Slice of Life":        {"rating": "A", "tip": "Sustain between rounds — gives extra HP room to play econ."},
    "Small Grab Bag":       {"rating": "A", "tip": "Free components early. Accelerates item completion on your carry."},
    "Restart Mission":      {"rating": "A", "tip": "Currency generation for pivoting mid-game. Good flexibility tool."},

    # Trait-specific augments (examples — pool is large, update per patch)
    "Dark Star I":          {"rating": "A", "tip": "Dark Star comp enabler. Great if you already have 4+ Dark Star units."},
    "Dark Star II":         {"rating": "S", "tip": "Strong Dark Star boost. Prioritize if running 6+ Dark Stars."},
    "Space Groove I":       {"rating": "A", "tip": "AS and AD/AP scaling for Groove comps. Good with 5+ Groovers."},
    "Meeple I":             {"rating": "A", "tip": "Accelerates Meeple stacking. Excellent in dedicated Meeple boards."},
    "Challenger I":         {"rating": "A", "tip": "AS stacking for Challenger units. Strong with Diana/Kindred/Bel'Veth carries."},
    "Primordian I":         {"rating": "A", "tip": "Best opener trait. Free 1-2 cost units per round — great early econ/units."},
    "Timebreaker I":        {"rating": "A", "tip": "Top opener: free rerolls on loss + XP on win. Strong econ and tempo."},
    "Anima I":              {"rating": "A", "tip": "Good if you plan to loss-streak early. Tech stacks quickly on a streak."},

    # ── B Tier ────────────────────────────────────────────────────────────────
    "Titanic Force":        {"rating": "B", "tip": "HP scaling. Decent if you are already stacking Brawler or Vanguard."},
    "Item Grab Bag":        {"rating": "B", "tip": "Components mid-game. Not as efficient as Heroic Grab Bag but fine in a pinch."},
    "Electrocharge":        {"rating": "B", "tip": "AoE damage. Better with Ionic Spark/Evenshroud shred already on your board."},
    "Pandora's Items":      {"rating": "B", "tip": "Randomizes items each round. High variance — avoid if you need specific items."},

    # ── X Tier (Carry-Specific / Situational — from TFT Academy comps page) ──
    # These augments enable specific situational comps from TFT Academy's X-tier.
    # Only take them if you can commit to the carry they unlock.
    "Aura Farming":         {"rating": "A", "tip": "Enables Graves Vex 9.5 — a 4-cost carry comp that's currently A-tier on TFT Academy. Take it if you can fast-9 with Graves."},
    "Portable Forge":       {"rating": "A", "tip": "Free artifact item — strong with Voyager Crab Urgot. B-tier carry comp on TFT Academy."},
    "Two Tanky":            {"rating": "B", "tip": "Bonus tank stats. Pairs with Samira Knock-Up B-tier comp on TFT Academy."},
    "Expedition":           {"rating": "B", "tip": "Mecha Sol enabler — currently C-tier on TFT Academy. Niche pick."},
    "Invader Zed":          {"rating": "B", "tip": "Carry augment — turns Zed into a viable carry. Situational X-tier on TFT Academy."},
    "Shieldmaiden":         {"rating": "B", "tip": "Carry augment — Leona becomes a frontline carry. Situational X-tier on TFT Academy."},
    "Self-Destruct":        {"rating": "B", "tip": "Carry augment — Gragas detonates. Pairs with Sympathetic Implant Mod radiant."},
    "Terminal Velocity":    {"rating": "B", "tip": "Carry augment — turns Poppy into a carry. Situational X-tier on TFT Academy."},
    "Bonk":                 {"rating": "A", "tip": "Trait carry bonus — also enables Bonk Nasus comp. Excellent when committed to a synergy."},
    "Contract Killer":      {"rating": "B", "tip": "Carry augment — enables Pyke as a primary carry. Situational X-tier on TFT Academy."},
    "The Big Bang":         {"rating": "B", "tip": "Carry augment — Ivern's minion (via Meepsie) becomes a carry. Niche."},
    "Stellar Combo":        {"rating": "B", "tip": "Carry augment — Aatrox combo carry. Situational X-tier on TFT Academy."},
    "Reach for the Stars":  {"rating": "B", "tip": "Carry augment — Jax becomes a primary carry. Situational X-tier on TFT Academy."},
    "Heat Death":           {"rating": "B", "tip": "Carry augment — Mordekaiser carry. Situational X-tier on TFT Academy."},
}
