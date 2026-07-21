import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import { useCoachSocket } from "./useCoachSocket";

//frontend made in help using ai

// ─── STATIC DATA (for manual fallback & display labels) ──────────────────────

const COMPONENTS = [
  { id: "bf_sword", name: "B.F. Sword", stat: "AD", icon: "⚔️" },
  { id: "needlessly_large_rod", name: "Large Rod", stat: "AP", icon: "🔮" },
  { id: "giants_belt", name: "Giant's Belt", stat: "HP", icon: "🟤" },
  { id: "chain_vest", name: "Chain Vest", stat: "Armor", icon: "🛡️" },
  { id: "negatron_cloak", name: "Neg. Cloak", stat: "MR", icon: "🧿" },
  { id: "recurve_bow", name: "Recurve Bow", stat: "AS", icon: "🏹" },
  { id: "tear", name: "Tear", stat: "Mana", icon: "💧" },
  { id: "sparring_gloves", name: "Gloves", stat: "Crit", icon: "🧤" },
  { id: "spatula", name: "Spatula", stat: "Trait", icon: "🥄" },
  { id: "frying_pan", name: "Frying Pan", stat: "Trait", icon: "pan:)"}
];

// Icon map — kept local since backend doesn't store UI icons.
// Matches every item currently in game_data.py (Set 17).
const ITEM_ICONS = {
  "Deathblade": "🗡️",
  "Hextech Gunblade": "💉",
  "Sterak's Gage": "🦾",
  "Edge of Night": "🌑",
  "Bloodthirster": "🩸",
  "Giant Slayer": "⚡",
  "Spear of Shojin": "🔱",
  "Infinity Edge": "💎",
  "Rabadon's Deathcap": "🎩",
  "Morellonomicon": "🔥",
  "Crownguard": "👑",
  "Ionic Spark": "⚡",
  "Guinsoo's Rageblade": "🌀",
  "Archangel's Staff": "📖",
  "Jeweled Gauntlet": "💍",
  "Warmog's Armor": "❤️",
  "Sunfire Cape": "🌞",
  "Evenshroud": "🌪️",
  "Nashor's Tooth": "🦷",
  "Spirit Visage": "🩺",
  "Striker's Flail": "🛡️",
  "Bramble Vest": "🌿",
  "Gargoyle Stoneplate": "🗿",
  "Titan's Resolve": "🏛️",
  "Protector's Vow": "🔵",
  "Steadfast Heart": "🫀",
  "Dragon's Claw": "🐉",
  "Kraken's Fury": "🦑",
  "Adaptive Helm": "🧊",
  "Quicksilver": "💨",
  "Red Buff": "🔴",
  "Statikk Shiv": "⚡",
  "Last Whisper": "🎯",
  "Blue Buff": "💙",
  "Hand of Justice": "⚖️",
  "Thief's Gloves": "🃏",
};


const STAGES = [
  "1-1","2-1","2-3","2-5","3-1","3-2","3-5","4-1","4-2","4-5","5-1","5-5"
];

// Layout convention:
//   Row 0 = top of display = your FRONT row (closest to enemy → tanks)
//   Row 3 = bottom of display = your BACK row (farthest from enemy → carries)
const POSITIONING_TEMPLATES = [
  {
    name: "Standard Frontline",
    desc: "Tanks soak center, carry tucked in the back corner",
    layout: [
      [0,"T","T","T","T",0,0],
      [0,0,0,0,0,"T",0],
      [0,0,0,0,0,"S","S"],
      [0,0,0,0,"S","C","C"],
    ],
    tips: [
      "Main carry second-from-corner — the true corner eats assassin jumps and Zephyr first",
      "Tanks slightly off-center toward the carry side shorten the enemy's path to them, not to your carry",
      "Supports adjacent to the carry so aura items (Protector's Vow, Evenshroud, Spirit Visage) cover them",
      "Mirror the whole shape left if the strongest enemy carry sits on your right",
    ],
  },
  {
    name: "Anti-Assassin",
    desc: "Corner clump — no landing hexes next to your carry",
    layout: [
      [0,0,0,0,0,0,0],
      [0,0,0,0,"T","T","T"],
      [0,0,0,0,"S","C","S"],
      [0,0,0,0,"S","C","S"],
    ],
    tips: [
      "Assassins leap to the hex behind your backline — fill every hex around the carry so there's nowhere to land",
      "Pull the clump one row forward (rows 1-3, not the wall) so divers can't wrap behind it",
      "Quicksilver on the carry blocks the opening CC chain that usually kills them",
      "Scout: if no assassins/divers this lobby, switch back to Standard — clumping loses to AoE",
    ],
  },
  {
    name: "Spread",
    desc: "One-hex gaps vs AoE, burn, and Ionic Spark",
    layout: [
      ["T",0,"T",0,"T",0,"T"],
      [0,0,0,0,0,0,0],
      ["S",0,0,"S",0,0,"S"],
      [0,"C",0,0,0,"C",0],
    ],
    tips: [
      "Counters Morellonomicon, Sunfire, Statikk Shiv chains, and big AoE ults",
      "Keep at least one empty hex between every pair of units — splash needs adjacency",
      "Split your two damage threats to opposite sides so one ult can't hit both",
      "Aura items lose value spread out — swap them onto the frontline before committing",
    ],
  },
  {
    name: "Backline Stack",
    desc: "Everything on the back wall for max distance",
    layout: [
      [0,0,0,0,0,0,0],
      [0,0,0,0,0,0,0],
      [0,0,0,0,0,0,0],
      ["T","T","S","S","C","C","T"],
    ],
    tips: [
      "Maximizes time before melee can reach your carries",
      "Best paired with displacement (knock-ups, stuns) to disrupt approach",
      "Vulnerable to Zephyr — scout opponents' items before committing",
    ],
  },
];

const TIER_COLORS = { S: "#ff4757", A: "#ffa502", B: "#2ed573", C: "#747d8c", X: "#5a5e6b" };
const ACCENT = "#00d2ff";
const ACCENT2 = "#7c5cfc";

// Backend payload schema version this overlay is built for. Must match
// backend config.PROTOCOL_VERSION — a red header badge appears when the
// running backend disagrees (stale process or unmerged code).
const BACKEND_PROTOCOL_EXPECTED = 3;

// TFT cost-tier colors used to outline unit chips and cells
const COST_COLORS = {
  1: "#9ca3af", 2: "#1f9d55", 3: "#2563eb", 4: "#9333ea", 5: "#d97706",
};
const STAR_COLORS = { 1: "#9ca3af", 2: "#fbbf24", 3: "#fb923c" };

// Tips that talk about positioning — surfaced inside the Position tab.
const POSITIONING_KEYWORDS = /\b(front\s*row|backline|frontline|spread|clump|corner|position|move\s+(?:your|the|at)|carry|tank|assassin|aoe|column|row|adjacent|hex|zephyr)\b/i;

// Trend marker shown next to TFT Academy tier badges
const TREND_GLYPH = {
  rising:  { icon: "▲", color: "#2ed573", label: "rising" },
  falling: { icon: "▼", color: "#ff6348", label: "falling" },
  new:     { icon: "✦", color: "#ffd32a", label: "new" },
};

// ─── HELPERS ─────────────────────────────────────────────────────────────────

function getCraftableItems(componentIds, recipes) {
  const items = [];
  for (let i = 0; i < componentIds.length; i++) {
    for (let j = i + 1; j < componentIds.length; j++) {
      const pair = [componentIds[i], componentIds[j]].sort();
      const match = recipes.find(
        (it) => [...it.recipe].sort().join() === pair.join()
      );
      if (match) items.push(match);
    }
  }
  const tierOrder = { S: 0, A: 1, B: 2, C: 3 };
  items.sort((a, b) => (tierOrder[a.tier] ?? 4) - (tierOrder[b.tier] ?? 4));
  return items;
}

function getSlamUrgencyFromStage(stage) {
  const num = parseFloat(stage?.replace("-", ".") || "1.1");
  if (num < 2.3) return { level: "low", color: "#2ed573" };
  if (num < 3.5) return { level: "medium", color: "#ffa502" };
  if (num < 4.5) return { level: "high", color: "#ff6348" };
  return { level: "critical", color: "#ff4757" };
}

// ─── SUB-COMPONENTS ──────────────────────────────────────────────────────────

function ConnectionBadge({ isConnected, isDemo }) {
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: "8px"
    }}>
      <div style={{
        background: isConnected ? "#2ed57322" : "#ff475722",
        color: isConnected ? "#2ed573" : "#ff4757",
        padding: "3px 10px", borderRadius: "20px", fontSize: "10px",
        fontWeight: 700, fontFamily: "var(--mono)", letterSpacing: "1px",
        border: `1px solid ${isConnected ? "#2ed57344" : "#ff475744"}`,
      }}>
        {isConnected ? "● LIVE" : "● OFFLINE"}
      </div>
      {isDemo && (
        <div style={{
          background: "#ffa50222", color: "#ffa502",
          padding: "3px 8px", borderRadius: "20px", fontSize: "9px",
          fontWeight: 700, fontFamily: "var(--mono)", letterSpacing: "1px",
          border: "1px solid #ffa50233",
        }}>
          DEMO
        </div>
      )}
    </div>
  );
}

function StatBox({ label, value, color }) {
  return (
    <div style={{ textAlign: "center" }}>
      <div style={{ fontSize: "10px", color: "#8b8fa3", fontFamily: "var(--mono)", letterSpacing: "1px" }}>{label}</div>
      <div style={{ fontSize: "18px", fontWeight: 700, color }}>{value}</div>
    </div>
  );
}

// Lobby standings strip: every player's HP in standings order (from the
// backend's player-list read), our own chip highlighted, dead players dimmed.
function StandingsStrip({ lobbyHp, ourHp }) {
  if (!lobbyHp || lobbyHp.length === 0) return null;
  const alive = lobbyHp.filter((h) => h > 0);
  const rank = 1 + alive.filter((h) => h > ourHp).length;
  // Highlight the first chip matching our HP (ties are rare and harmless).
  const ourIdx = lobbyHp.indexOf(ourHp);
  const hpColor = (h) => (h > 50 ? "#2ed573" : h > 25 ? "#ffa502" : "#ff4757");
  return (
    <div style={{
      padding: "6px 16px", display: "flex", gap: "6px", alignItems: "center",
      borderBottom: "1px solid #1e2028", background: "rgba(16,17,23,0.95)",
      fontFamily: "var(--mono)",
    }}>
      <span style={{ fontSize: "9px", color: "#8b8fa3", letterSpacing: "1px", marginRight: "4px" }}>
        LOBBY&nbsp;
        <span style={{ color: "#c8cad0", fontWeight: 700 }}>#{rank}</span>
        <span style={{ color: "#5a5d6b" }}>/8</span>
      </span>
      {lobbyHp.map((h, i) => (
        <span
          key={i}
          title={i === ourIdx ? `You — ${h} HP` : h < 0 ? "Unreadable" : h > 0 ? `${h} HP` : "Eliminated"}
          style={{
            fontSize: "10px", fontWeight: 700, padding: "2px 6px",
            borderRadius: "4px", minWidth: "24px", textAlign: "center",
            color: h > 0 ? hpColor(h) : h < 0 ? "#777b8c" : "#4a4d5a",
            background: i === ourIdx ? `${ACCENT}18` : "rgba(255,255,255,0.03)",
            border: `1px solid ${i === ourIdx ? ACCENT : "transparent"}`,
            opacity: h > 0 ? 1 : h < 0 ? 0.75 : 0.55,
          }}
        >
          {h > 0 ? h : h < 0 ? "?" : "💀"}
        </span>
      ))}
    </div>
  );
}

// Shop buy calls: cards in the current shop the coach says to buy right
// now (2-star completions, comp units), strongest first.
function ShopBuyCalls({ actions }) {
  if (!actions || actions.length === 0) return null;
  return (
    <div className="card" style={{
      borderColor: "#ffd32a33", marginBottom: "12px",
      background: "linear-gradient(135deg, #ffd32a08, transparent)",
    }}>
      <div style={{
        fontSize: "10px", fontWeight: 700, letterSpacing: "1px",
        color: "#ffd32a", fontFamily: "var(--mono)", marginBottom: "8px",
      }}>
        🛒 SHOP — BUY NOW
      </div>
      {actions.slice(0, 3).map((a, i) => (
        <div key={i} style={{
          display: "flex", alignItems: "baseline", gap: "8px",
          padding: "4px 0", borderTop: i > 0 ? "1px solid #1e2028" : "none",
        }}>
          <span style={{ fontSize: "13px" }}>{a.priority <= 2 ? "⭐" : "🎯"}</span>
          {Number.isInteger(a.slot) && (
            <span style={{
              fontFamily: "var(--mono)", fontSize: "9px", fontWeight: 700,
              color: "#ffd32a", border: "1px solid #ffd32a44", borderRadius: "4px",
              padding: "1px 5px", letterSpacing: "0.5px",
            }}>
              SLOT {a.slot + 1}
            </span>
          )}
          <span style={{ fontSize: "13px", fontWeight: 700, color: "#e4e5ea" }}>{a.name}</span>
          <span style={{ fontSize: "11px", color: "#8b8fa3", flex: 1 }}>{a.reason}</span>
        </div>
      ))}
    </div>
  );
}

// Card-style chip showing a single champion with their stars, cost color, and items.
function UnitChip({ unit, itemIcons = {}, dim = false }) {
  if (!unit) return null;
  const cost = unit.cost || 1;
  const stars = unit.star_level || 1;
  const costColor = COST_COLORS[cost] || "#666";
  const starColor = STAR_COLORS[stars] || "#fbbf24";
  return (
    <div style={{
      display: "flex", flexDirection: "column",
      padding: "5px 7px", borderRadius: "6px",
      background: dim ? "rgba(0,0,0,0.2)" : `${costColor}15`,
      border: `1px solid ${costColor}55`,
      opacity: dim ? 0.75 : 1,
      minWidth: "78px", maxWidth: "140px",
    }}>
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        gap: "4px",
      }}>
        <span style={{
          fontSize: "11px", fontWeight: 600, color: "#e4e5ea",
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        }}>
          {unit.name}
        </span>
        <span style={{
          fontSize: "8px", color: starColor, fontFamily: "var(--mono)",
          flexShrink: 0, letterSpacing: "-1px",
        }}>
          {"★".repeat(stars)}
        </span>
      </div>
      {unit.items && unit.items.length > 0 && (
        <div style={{ display: "flex", gap: "2px", marginTop: "3px", flexWrap: "wrap" }}>
          {unit.items.map((it, i) => (
            <GameIcon key={i} kind="items" name={it} emoji={itemIcons[it] || "🔧"} size={13} />
          ))}
        </div>
      )}
    </div>
  );
}

// Renders the player's actual board (4 rows × 7 cols) using detected champions.
// Convention: row 0 = top of display = closest to enemy (your frontline).
function LiveBoard({ champions, itemIcons = {}, highlightTemplate = null }) {
  const grid = Array.from({ length: 4 }, () => Array(7).fill(null));
  for (const c of champions || []) {
    if (c.board_row == null || c.board_col == null) continue;
    const r = Math.max(0, Math.min(3, c.board_row));
    const col = Math.max(0, Math.min(6, c.board_col));
    grid[r][col] = c;
  }
  return (
    <div style={{
      background: "#0a0b0f", borderRadius: "8px", padding: "12px",
      border: "1px solid #1e2028",
    }}>
      <div style={{
        fontSize: "8px", color: "#ff475744",
        fontFamily: "var(--mono)", letterSpacing: "2px",
        textAlign: "center", marginBottom: "8px",
      }}>
        ▲ ENEMY ▲
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: "3px", alignItems: "center" }}>
        {grid.map((row, ri) => (
          <div key={ri} style={{
            display: "flex", gap: "3px",
            marginLeft: ri % 2 === 1 ? "22px" : "0",
          }}>
            {row.map((cell, ci) => {
              const isUnit = !!cell;
              const cost = cell?.cost || 1;
              const color = isUnit ? (COST_COLORS[cost] || "#9ca3af") : "transparent";
              const ghost = !isUnit && highlightTemplate?.[ri]?.[ci];
              const ghostColor = ghost === "T" ? "#ff6348"
                : ghost === "C" ? "#ffd32a"
                : ghost === "S" ? "#2ed573"
                : "transparent";
              return (
                <div key={ci} style={{
                  width: "46px", height: "46px", borderRadius: "6px",
                  border: isUnit ? `2px solid ${color}`
                    : ghost ? `1px dashed ${ghostColor}66`
                    : "1px solid #1a1b21",
                  background: isUnit ? `${color}18`
                    : ghost ? `${ghostColor}06`
                    : "#13141a",
                  display: "flex", flexDirection: "column",
                  alignItems: "center", justifyContent: "center",
                  padding: "2px",
                }}>
                  {isUnit ? (
                    <>
                      <span style={{
                        fontSize: "8px", fontWeight: 700, color,
                        fontFamily: "var(--mono)", lineHeight: 1,
                        width: "42px", textAlign: "center",
                        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                      }}>
                        {cell.name}
                      </span>
                      {cell.star_level > 1 && (
                        <span style={{
                          fontSize: "7px", marginTop: "1px",
                          color: STAR_COLORS[cell.star_level] || "#fbbf24",
                          letterSpacing: "-1px",
                        }}>
                          {"★".repeat(cell.star_level)}
                        </span>
                      )}
                      {cell.items && cell.items.length > 0 && (
                        <div style={{ display: "flex", gap: "1px", marginTop: "1px" }}>
                          {cell.items.slice(0, 3).map((it, i) => (
                            <GameIcon key={i} kind="items" name={it} emoji={itemIcons[it] || "•"} size={10} />
                          ))}
                        </div>
                      )}
                    </>
                  ) : ghost ? (
                    <span style={{
                      fontSize: "7px", color: `${ghostColor}99`,
                      fontFamily: "var(--mono)", letterSpacing: "0.5px",
                    }}>
                      {ghost === "T" ? "TANK" : ghost === "C" ? "CARRY" : "SUPP"}
                    </span>
                  ) : null}
                </div>
              );
            })}
          </div>
        ))}
      </div>
      <div style={{
        fontSize: "8px", color: `${ACCENT}55`,
        fontFamily: "var(--mono)", letterSpacing: "2px",
        textAlign: "center", marginTop: "8px",
      }}>
        ▼ YOUR SIDE ▼
      </div>
    </div>
  );
}

function TierBadge({ tier }) {
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", justifyContent: "center",
      width: "22px", height: "22px", borderRadius: "5px",
      background: `${TIER_COLORS[tier] || "#555"}22`,
      border: `1px solid ${TIER_COLORS[tier] || "#555"}55`,
      color: TIER_COLORS[tier] || "#555",
      fontSize: "10px", fontWeight: 800, fontFamily: "var(--mono)",
    }}>
      {tier}
    </span>
  );
}

function TabBtn({ active, onClick, children }) {
  return (
    <button onClick={onClick} style={{
      padding: "8px 14px", background: active ? `${ACCENT}18` : "transparent",
      border: active ? `1px solid ${ACCENT}` : "1px solid #2a2d35",
      borderRadius: "7px", color: active ? ACCENT : "#8b8fa3",
      fontFamily: "var(--mono)", fontSize: "11px",
      fontWeight: active ? 700 : 500, cursor: "pointer",
      textTransform: "uppercase", letterSpacing: "1px",
      transition: "all 0.15s ease",
    }}>
      {children}
    </button>
  );
}

// Compact pill showing a trait's current count vs. the next breakpoint.
// Active traits (count >= first breakpoint) are highlighted in accent color.
function SynergyPill({ synergy }) {
  const active = synergy.is_active;
  const reachedBp = synergy.count >= synergy.breakpoint;
  const color = active ? ACCENT : "#8b8fa3";
  return (
    <div style={{
      display: "inline-flex", alignItems: "center", gap: "6px",
      padding: "5px 10px", borderRadius: "6px",
      border: `1px solid ${active ? `${ACCENT}55` : "#2a2d35"}`,
      background: active ? `${ACCENT}10` : "rgba(0,0,0,0.2)",
      fontFamily: "var(--mono)",
    }}>
      <span style={{
        fontSize: "11px", color, fontWeight: active ? 700 : 500,
      }}>
        {synergy.name}
      </span>
      <span style={{
        fontSize: "10px",
        color: reachedBp ? "#2ed573" : color,
        opacity: 0.85,
      }}>
        {synergy.count}/{synergy.breakpoint}
      </span>
    </div>
  );
}

// TFT Academy tier badge with optional trend marker (rising/falling/new).
function MetaTierBadge({ tier, trend }) {
  const color = TIER_COLORS[tier] || "#555";
  const t = TREND_GLYPH[trend];
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: "4px",
      padding: "2px 8px", borderRadius: "4px",
      background: `${color}18`, border: `1px solid ${color}55`,
      fontFamily: "var(--mono)", fontSize: "9px", fontWeight: 800,
      letterSpacing: "1px",
    }}>
      <span style={{ color }}>{tier}</span>
      <span style={{ color: "#666", fontSize: "8px" }}>TFT.A</span>
      {t && (
        <span title={t.label} style={{
          color: t.color, fontSize: "9px", fontWeight: 700,
        }}>
          {t.icon}
        </span>
      )}
    </span>
  );
}

// Real game-art icon with emoji fallback. Icons are synced into
// public/game_icons/ by backend/fetch_templates.py; when a file is
// missing (fresh clone, renamed item) the emoji keeps working.
function GameIcon({ kind, name, emoji, size = 18 }) {
  const [failed, setFailed] = useState(false);
  if (failed || !name) {
    return <span style={{ fontSize: `${Math.round(size * 0.85)}px`, lineHeight: 1 }}>{emoji || "•"}</span>;
  }
  return (
    <img
      src={`game_icons/${kind}/${encodeURIComponent(name)}.png`}
      alt={name}
      title={name}
      onError={() => setFailed(true)}
      style={{
        width: `${size}px`, height: `${size}px`, borderRadius: "3px",
        objectFit: "cover", display: "block", flexShrink: 0,
      }}
    />
  );
}

// Item plan for the locked comp: each carry with its target build, and
// whether you can complete each item from the components you're holding.
function ItemPlan({ suggestion, componentIds, itemRecipes }) {
  const recipeByName = useMemo(
    () => Object.fromEntries(itemRecipes.map((r) => [r.name, r.recipe])),
    [itemRecipes]
  );
  const held = useMemo(() => {
    const c = {};
    for (const id of componentIds) c[id] = (c[id] || 0) + 1;
    return c;
  }, [componentIds]);

  const carriers = suggestion.board_layout.filter((u) => u.items?.length > 0);
  if (carriers.length === 0) return null;

  const craftable = (itemName) => {
    const recipe = recipeByName[itemName];
    if (!recipe) return { known: false, can: false };
    const pool = { ...held };
    for (const comp of recipe) {
      if (!pool[comp]) return { known: true, can: false, recipe };
      pool[comp] -= 1;
    }
    return { known: true, can: true, recipe };
  };

  return (
    <>
      <div style={{
        fontSize: "9px", color: "#f5b942", margin: "14px 0 8px",
        fontFamily: "var(--mono)", letterSpacing: "2px",
      }}>
        📌 ITEM PLAN — {(suggestion.tftacademy_name || suggestion.name).toUpperCase()}
      </div>
      <div className="card" style={{ borderColor: "#f5b94233" }}>
        {carriers.map((u, i) => (
          <div key={i} style={{
            display: "flex", alignItems: "center", gap: "8px",
            padding: "7px 0",
            borderBottom: i < carriers.length - 1 ? "1px solid #1e2028" : "none",
          }}>
            <span style={{
              fontSize: "11px", fontWeight: 700, color: "#c8cad0",
              width: "84px", flexShrink: 0, overflow: "hidden",
              textOverflow: "ellipsis", whiteSpace: "nowrap",
            }}>
              {u.name}{u.stars > 1 ? ` ${"★".repeat(u.stars)}` : ""}
            </span>
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
              {u.items.map((it, j) => {
                const c = craftable(it);
                return (
                  <span key={j}
                    title={c.can
                      ? `${it} — craftable NOW from your components`
                      : c.known
                      ? `${it} — needs ${c.recipe.join(" + ")}`
                      : it}
                    style={{
                      display: "inline-flex", alignItems: "center", gap: "4px",
                      padding: "3px 6px", borderRadius: "5px",
                      border: c.can ? "1px solid #2ed57366" : "1px solid #2a2d35",
                      background: c.can ? "#2ed5730d" : "transparent",
                      opacity: c.can ? 1 : 0.75,
                    }}>
                    <GameIcon kind="items" name={it} emoji="🔧" size={18} />
                    <span style={{
                      fontSize: "9px", fontFamily: "var(--mono)",
                      color: c.can ? "#2ed573" : "#8b8fa3",
                    }}>
                      {c.can ? "CRAFT" : it.length > 14 ? `${it.slice(0, 13)}…` : it}
                    </span>
                  </span>
                );
              })}
            </div>
          </div>
        ))}
        <div style={{ marginTop: "8px", fontSize: "9px", color: "#5a5e6b", lineHeight: 1.5 }}>
          Green = both components are in your inventory right now. Hover an
          item for its recipe.
        </div>
      </div>
    </>
  );
}

// Single-pixel progress bar visualizing match_score (0-1).
function MatchScoreBar({ score }) {
  const pct = Math.max(0, Math.min(1, score)) * 100;
  return (
    <div style={{
      width: "60px", height: "4px", borderRadius: "2px",
      background: "#1a1b21", overflow: "hidden",
    }}>
      <div style={{
        width: `${pct}%`, height: "100%",
        background: `linear-gradient(90deg, ${ACCENT2}, ${ACCENT})`,
      }} />
    </div>
  );
}

function formatMetaGames(value) {
  if (!value) return null;
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M games`;
  if (value >= 1_000) return `${Math.round(value / 1_000)}K games`;
  return `${value} games`;
}

function formatMetaAge(epochSeconds) {
  if (!epochSeconds) return "cached data";
  const elapsed = Math.max(0, Math.floor(Date.now() / 1000) - epochSeconds);
  if (elapsed < 60) return "updated now";
  if (elapsed < 3600) return `updated ${Math.floor(elapsed / 60)}m ago`;
  if (elapsed < 86400) return `updated ${Math.floor(elapsed / 3600)}h ago`;
  return `updated ${Math.floor(elapsed / 86400)}d ago`;
}

function BoardStrengthCard({ score, breakdown, stage }) {
  if (!breakdown || breakdown.source === "none") return null;
  const color = breakdown.label === "Strong"
    ? "#2ed573"
    : breakdown.label === "Weak" ? "#ff6348" : "#ffa502";
  const rows = [
    { label: "UNITS + STARS", value: breakdown.champion_base || 0, max: 45 },
    { label: "UNIT META", value: breakdown.meta_bonus || 0, max: 8, signed: true },
    { label: "ACTIVE TRAITS", value: breakdown.synergy_bonus || 0, max: 20 },
    { label: "COMP FIT", value: breakdown.composition_bonus || 0, max: 10 },
    {
      label: "ITEMS",
      value: breakdown.item_bonus || 0,
      max: 25,
      unknown: !breakdown.item_data_known,
    },
    { label: "AUGMENTS", value: breakdown.augment_bonus || 0, max: 10 },
  ];
  const sourceLabel = breakdown.source === "detected_board"
    ? "live board"
    : breakdown.source === "roster_estimate" ? "roster estimate" : "traits estimate";
  const gamesLabel = formatMetaGames(breakdown.meta_games_analyzed);
  const ageLabel = formatMetaAge(breakdown.meta_updated_at);

  return (
    <div className="card" style={{
      marginBottom: "14px", borderColor: `${color}44`,
      background: `linear-gradient(135deg, ${color}0d, rgba(21,22,28,0.95))`,
    }}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: "12px" }}>
        <div style={{ minWidth: "82px" }}>
          <div style={{
            fontFamily: "var(--mono)", fontSize: "30px", fontWeight: 800,
            lineHeight: 1, color,
          }}>
            {Math.round(score || 0)}
            <span style={{ fontSize: "11px", color: "#666" }}>/100</span>
          </div>
          <div style={{
            marginTop: "5px", fontSize: "9px", fontFamily: "var(--mono)",
            color, fontWeight: 700, letterSpacing: "1px",
          }}>
            {breakdown.label?.toUpperCase()} @ {stage}
          </div>
        </div>
        <div style={{ flex: 1 }}>
          {rows.map((row) => (
            <div key={row.label} style={{ marginBottom: "5px" }}>
              <div style={{
                display: "flex", justifyContent: "space-between", marginBottom: "2px",
                fontFamily: "var(--mono)", fontSize: "8px", color: "#777b8c",
              }}>
                <span>{row.label}</span>
                <span>{row.unknown
                  ? "?"
                  : `${row.signed && row.value > 0 ? "+" : ""}${row.value.toFixed(1)}`}</span>
              </div>
              <div style={{ height: "3px", borderRadius: "2px", background: "#1a1b21" }}>
                <div style={{
                  height: "100%", borderRadius: "2px",
                  background: row.signed && row.value < 0 ? "#ff6348" : color,
                  width: `${Math.max(0, Math.min(100, Math.abs(row.value) / row.max * 100))}%`,
                }} />
              </div>
            </div>
          ))}
        </div>
      </div>
      <div style={{
        marginTop: "8px", paddingTop: "7px", borderTop: "1px solid #2a2d35",
        display: "flex", justifyContent: "space-between", gap: "8px", flexWrap: "wrap",
        fontFamily: "var(--mono)", fontSize: "8px", color: "#666",
      }}>
        <span>
          {sourceLabel} · {Math.round((breakdown.confidence || 0) * 100)}% confidence
          {breakdown.meta_bonus
            ? ` · META ${breakdown.meta_bonus > 0 ? "+" : ""}${breakdown.meta_bonus.toFixed(1)}`
            : ""}
        </span>
        <span>
          <span style={{ color: "#2ed573" }}>● AUTO META</span>
          {breakdown.meta_patch ? ` · PATCH ${breakdown.meta_patch}` : ""}
          {breakdown.meta_rank ? ` · ${breakdown.meta_rank}` : ""}
          {gamesLabel ? ` · ${gamesLabel}` : ""}
          {` · ${ageLabel}`}
          {" · "}<a href="https://tactics.tools/units/sett/latest" target="_blank" rel="noreferrer"
            style={{ color: "#7a8090" }}>tactics.tools</a>
        </span>
      </div>
      {breakdown.source === "roster_estimate" && (
        <div style={{ marginTop: "6px", fontSize: "9px", color: "#8b8fa3", lineHeight: 1.4 }}>
          Uses your strongest level-sized roster subset until board classification is active.
        </div>
      )}
      {!breakdown.item_data_known && (
        <div style={{ marginTop: "4px", fontSize: "9px", color: "#666", lineHeight: 1.4 }}>
          Equipped-item contribution is not scored until item assignment is detected.
        </div>
      )}
    </div>
  );
}

// Comp suggestion card: shows comp name, internal+TFT Academy tier,
// progress, held/missing units, and the composed direction tip.
function CompCard({ comp, primary, pinned = false, onPin }) {
  const accent = pinned ? "#f5b942" : primary ? ACCENT : "#5a5e6b";
  return (
    <div
      className="card"
      style={{
        marginBottom: "8px",
        borderColor: pinned ? "#f5b94266" : primary ? `${ACCENT}55` : "#2a2d35",
        borderLeft: `3px solid ${accent}`,
        ...(pinned && { background: "rgba(245,185,66,0.05)" }),
      }}>
      <div style={{
        display: "flex", alignItems: "center", gap: "8px",
        marginBottom: "6px", flexWrap: "wrap",
      }}>
        <span style={{
          fontWeight: 700, fontSize: primary ? "14px" : "12px",
          color: primary ? "#e4e5ea" : "#c8cad0",
        }}>
          {comp.name}
        </span>
        {onPin && (
          <button
            onClick={(e) => { e.stopPropagation(); onPin(); }}
            title={pinned
              ? "Locked as your comp — click to unlock"
              : "Lock this as your comp: advice, augments, and the item plan follow it"}
            style={{
              fontSize: "8px", fontWeight: 800, cursor: "pointer",
              color: pinned ? "#f5b942" : "#8b8fa3",
              background: pinned ? "#f5b94218" : "transparent",
              padding: "2px 7px", borderRadius: "3px",
              fontFamily: "var(--mono)", letterSpacing: "1px",
              border: pinned ? "1px solid #f5b94244" : "1px solid #2a2d35",
            }}>
            {pinned ? "📌 LOCKED" : "📌 PIN"}
          </button>
        )}
        {comp.tftacademy_tier && (
          <MetaTierBadge tier={comp.tftacademy_tier} trend={comp.tftacademy_trend} />
        )}
        <div style={{ flex: 1 }} />
        <MatchScoreBar score={comp.match_score} />
        <span style={{
          fontFamily: "var(--mono)", fontSize: "10px", color: "#8b8fa3",
        }}>
          {Math.round((comp.match_score || 0) * 100)}%
        </span>
      </div>

      {comp.progress && (
        <div style={{
          fontSize: "10px", color: "#8b8fa3", fontFamily: "var(--mono)",
          marginBottom: "6px",
        }}>
          {comp.progress}
        </div>
      )}

      {comp.held_units && comp.held_units.length > 0 && (
        <div style={{
          display: "flex", flexWrap: "wrap", gap: "4px", marginBottom: "6px",
        }}>
          {comp.held_units.map((u, i) => (
            <span key={i} style={{
              fontSize: "10px", padding: "2px 6px", borderRadius: "4px",
              background: `${ACCENT}10`, border: `1px solid ${ACCENT}33`,
              color: ACCENT,
            }}>
              {u}
            </span>
          ))}
        </div>
      )}

      {comp.missing_units && comp.missing_units.length > 0 && (
        <div style={{
          display: "flex", flexWrap: "wrap", gap: "4px", marginBottom: "6px",
        }}>
          <span style={{
            fontSize: "9px", color: "#666", fontFamily: "var(--mono)",
            alignSelf: "center", letterSpacing: "1px",
          }}>NEED:</span>
          {comp.missing_units.slice(0, 5).map((u, i) => (
            <span key={i} style={{
              fontSize: "10px", padding: "2px 6px", borderRadius: "4px",
              background: "rgba(0,0,0,0.25)", border: "1px solid #2a2d35",
              color: "#8b8fa3",
            }}>
              {u}
            </span>
          ))}
        </div>
      )}

      {comp.direction_tip && primary && (
        <p style={{
          fontSize: "11px", color: "#a0a3b0", lineHeight: 1.45,
          marginTop: "4px",
        }}>
          💡 {comp.direction_tip}
        </p>
      )}
    </div>
  );
}

// ─── DEV PANEL (demo mode only) ──────────────────────────────────────────────

function NumberStepper({ label, value, min, max, step = 1, onChange, suffix = "" }) {
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: "6px", marginBottom: "6px",
    }}>
      <span style={{
        fontSize: "10px", color: "#8b8fa3", fontFamily: "var(--mono)",
        letterSpacing: "1px", width: "44px",
      }}>{label}</span>
      <button onClick={() => onChange(Math.max(min, value - step))} style={{
        background: "#1a1b21", border: "1px solid #2a2d35", borderRadius: "4px",
        color: "#c8cad0", width: "22px", height: "22px", cursor: "pointer",
        fontFamily: "var(--mono)", fontSize: "11px",
      }}>−</button>
      <input
        type="range" min={min} max={max} step={step} value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        style={{ flex: 1, accentColor: ACCENT, height: "4px" }}
      />
      <button onClick={() => onChange(Math.min(max, value + step))} style={{
        background: "#1a1b21", border: "1px solid #2a2d35", borderRadius: "4px",
        color: "#c8cad0", width: "22px", height: "22px", cursor: "pointer",
        fontFamily: "var(--mono)", fontSize: "11px",
      }}>+</button>
      <span style={{
        fontFamily: "var(--mono)", fontSize: "10px", color: ACCENT,
        width: "44px", textAlign: "right",
      }}>{value}{suffix}</span>
    </div>
  );
}

function PanelSection({ title, children }) {
  return (
    <div style={{ marginBottom: "14px" }}>
      <div style={{
        fontSize: "9px", color: "#8b8fa3", marginBottom: "6px",
        fontFamily: "var(--mono)", letterSpacing: "2px",
      }}>
        {title}
      </div>
      {children}
    </div>
  );
}

function DevPanel({
  open, onClose, demoInfo, gameState, sendCommand,
}) {
  const scenarios = demoInfo?.scenarios || [];
  const currentScenario = demoInfo?.current_scenario;
  const paused = !!demoInfo?.paused;
  const tickMs = demoInfo?.tick_ms ?? 500;
  const [minTick, maxTick] = demoInfo?.tick_bounds || [50, 5000];

  const hp = gameState?.player_hp ?? 100;
  const gold = gameState?.gold ?? 0;
  const level = gameState?.level ?? 1;
  const stage = gameState?.stage ?? "1-1";

  const componentIds = gameState?.component_ids ?? [];

  if (!open) return null;

  const phases = [
    { id: "planning", label: "Planning" },
    { id: "combat", label: "Combat" },
    { id: "augment_select", label: "Augment" },
    { id: "carousel", label: "Carousel" },
  ];

  const allStages = [
    "1-1", "1-4", "2-1", "2-3", "2-5", "3-1", "3-2", "3-5",
    "4-1", "4-2", "4-5", "5-1", "5-5", "6-1",
  ];

  return (
    <div style={{
      position: "fixed", top: 0, right: 0, bottom: 0, width: "320px",
      background: "rgba(13,14,18,0.98)",
      borderLeft: `1px solid ${ACCENT}33`,
      boxShadow: "-8px 0 24px rgba(0,0,0,0.4)",
      zIndex: 100, overflowY: "auto",
      padding: "14px 14px 20px", animation: "slideIn 0.2s ease",
    }}>
      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        marginBottom: "12px", paddingBottom: "10px",
        borderBottom: `1px solid ${ACCENT}22`,
      }}>
        <div style={{
          fontFamily: "'Orbitron', sans-serif", fontSize: "12px", fontWeight: 900,
          color: ACCENT, letterSpacing: "3px",
        }}>
          DEV PANEL
        </div>
        <button onClick={onClose} style={{
          background: "transparent", border: "1px solid #2a2d35",
          borderRadius: "4px", color: "#8b8fa3", padding: "2px 8px",
          cursor: "pointer", fontFamily: "var(--mono)", fontSize: "10px",
        }}>CLOSE</button>
      </div>

      <PanelSection title="SCENARIO">
        <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
          {scenarios.map((s) => {
            const active = s.index === currentScenario;
            return (
              <button
                key={s.index}
                onClick={() => sendCommand("restart_game", { scenario: s.index })}
                title={s.desc}
                style={{
                  padding: "6px 8px", borderRadius: "5px", cursor: "pointer",
                  textAlign: "left", fontSize: "11px",
                  border: active ? `1px solid ${ACCENT}` : "1px solid #2a2d35",
                  background: active ? `${ACCENT}12` : "rgba(0,0,0,0.2)",
                  color: active ? ACCENT : "#c8cad0",
                  fontWeight: active ? 700 : 500,
                  fontFamily: "var(--mono)", letterSpacing: "1px",
                }}>
                {active ? "● " : "  "}{s.name}
              </button>
            );
          })}
        </div>
      </PanelSection>

      <PanelSection title="SIM CONTROL">
        <div style={{ display: "flex", gap: "4px", marginBottom: "8px" }}>
          <button onClick={() => sendCommand("pause")} style={devBtnStyle(paused ? "#2ed573" : "#ffa502")}>
            {paused ? "▶ RESUME" : "❚❚ PAUSE"}
          </button>
          <button onClick={() => sendCommand("step")} disabled={!paused} style={{
            ...devBtnStyle("#8b8fa3"),
            opacity: paused ? 1 : 0.4,
            cursor: paused ? "pointer" : "not-allowed",
          }}>▶| STEP</button>
        </div>
        <div style={{ display: "flex", gap: "4px", marginBottom: "8px" }}>
          <button onClick={() => sendCommand("next_round")} style={devBtnStyle("#7c5cfc")}>
            SKIP ROUND
          </button>
          <button
            onClick={() => sendCommand("restart_game", { scenario: currentScenario })}
            style={devBtnStyle("#ff6348")}>
            RESTART
          </button>
        </div>
        <NumberStepper
          label="tick"
          value={tickMs}
          min={minTick}
          max={maxTick}
          step={50}
          onChange={(v) => sendCommand("set_tick_speed", { tick_ms: v })}
          suffix="ms"
        />
      </PanelSection>

      <PanelSection title="FORCE PHASE">
        <div style={{ display: "flex", gap: "4px", flexWrap: "wrap" }}>
          {phases.map((p) => (
            <button key={p.id}
              onClick={() => sendCommand("force_phase", { phase: p.id })}
              style={{
                ...devBtnStyle("#a29bfe"),
                flex: "1 1 calc(50% - 4px)", minWidth: "120px",
                background: gameState?.phase === p.id ? "#a29bfe22" : "rgba(0,0,0,0.2)",
                borderColor: gameState?.phase === p.id ? "#a29bfe" : "#2a2d35",
                color: gameState?.phase === p.id ? "#a29bfe" : "#c8cad0",
              }}>
              {p.label}
            </button>
          ))}
        </div>
      </PanelSection>

      <PanelSection title={`STAGE — current: ${stage}`}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "3px" }}>
          {allStages.map((s) => {
            const active = s === stage;
            return (
              <button key={s}
                onClick={() => sendCommand("override_stage", { stage: s })}
                style={{
                  padding: "3px 8px", borderRadius: "4px", cursor: "pointer",
                  fontSize: "10px", fontFamily: "var(--mono)",
                  border: active ? `1px solid ${ACCENT}` : "1px solid #2a2d35",
                  background: active ? `${ACCENT}12` : "transparent",
                  color: active ? ACCENT : "#8b8fa3",
                }}>{s}</button>
            );
          })}
        </div>
      </PanelSection>

      <PanelSection title="RESOURCES">
        <NumberStepper
          label="HP" value={hp} min={0} max={100}
          onChange={(v) => sendCommand("set_hp", { hp: v })}
        />
        <NumberStepper
          label="GOLD" value={gold} min={0} max={150}
          onChange={(v) => sendCommand("set_gold", { gold: v })}
        />
        <NumberStepper
          label="LVL" value={level} min={1} max={10}
          onChange={(v) => sendCommand("set_level", { level: v })}
        />
      </PanelSection>

      <PanelSection title={`COMPONENTS (${componentIds.length})`}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "3px", marginBottom: "6px" }}>
          {COMPONENTS.map((c) => (
            <button key={c.id}
              onClick={() => sendCommand("override_components", {
                components: [...componentIds, c.id],
              })}
              title={`Add ${c.name}`}
              style={{
                width: "34px", height: "34px", borderRadius: "5px",
                border: "1px solid #2a2d35", background: "rgba(0,0,0,0.2)",
                cursor: "pointer", fontSize: "16px",
                display: "flex", alignItems: "center", justifyContent: "center",
              }}>
              <GameIcon kind="components" name={c.id} emoji={c.icon} size={22} />
            </button>
          ))}
        </div>
        <div style={{ display: "flex", gap: "4px" }}>
          <button
            onClick={() => sendCommand("override_components", { components: [] })}
            style={devBtnStyle("#ff6348")}>
            CLEAR
          </button>
          <button
            onClick={() => sendCommand("override_components", {
              components: COMPONENTS.slice(0, 5).map((c) => c.id),
            })}
            style={devBtnStyle(ACCENT)}>
            FILL 5
          </button>
        </div>
      </PanelSection>
    </div>
  );
}

function devBtnStyle(color) {
  return {
    flex: 1, padding: "6px 8px", borderRadius: "5px", cursor: "pointer",
    border: `1px solid ${color}55`,
    background: `${color}10`,
    color,
    fontFamily: "var(--mono)", fontSize: "10px",
    fontWeight: 700, letterSpacing: "1px",
  };
}

// ─── MAIN APP ────────────────────────────────────────────────────────────────

export default function App() {
  const { gameState, gameData, backendProtocol, isConnected, isDemo, demoInfo, serverStats, sendCommand } = useCoachSocket();
  const [devOpen, setDevOpen] = useState(false);

  // Electron overlay: hover-to-interact. The window is click-through by
  // default so game clicks pass underneath; mouse-over the panel asks the
  // main process to capture the mouse, mouse-out releases it again.
  const inElectron = typeof window !== "undefined" && !!window.electronAPI;
  const [isInteractive, setIsInteractive] = useState(!inElectron);
  const [hoverLocked, setHoverLocked] = useState(false);
  const [shareMode, setShareMode] = useState(false);
  useEffect(() => {
    if (!inElectron) return;
    window.electronAPI.onInteractionMode?.((interactive) =>
      setIsInteractive(interactive)
    );
    window.electronAPI.onHoverLock?.((locked) => setHoverLocked(locked));
    window.electronAPI.onShareMode?.((enabled) => setShareMode(enabled));
    window.electronAPI.getShareMode?.().then((enabled) => setShareMode(enabled));
  }, [inElectron]);
  // Only request interactivity on enter — release is handled by the main
  // process polling the cursor position, since renderer mouseleave events
  // fire spuriously when the click-through state toggles.
  const handleMouseEnter = () => inElectron && window.electronAPI.setInteractive?.(true);
  const handleMouseLeave = () => {};

  const itemRecipes = useMemo(
    () => (gameData?.item_recipes ?? []).map((r) => ({ ...r, icon: ITEM_ICONS[r.name] || "🔧" })),
    [gameData]
  );

  const [tab, setTab] = useState("items");
  const [manualComponents, setManualComponents] = useState([]);
  const [manualStage, setManualStage] = useState("2-5");
  const [selectedTemplate, setSelectedTemplate] = useState(0);
  const [collapsed, setCollapsed] = useState(false);

  // Decide data source: live game state or manual input
  const isLive = isConnected && gameState && gameState.phase !== "not_in_game";

  const stage = isLive ? gameState.stage : manualStage;
  const hp = isLive ? gameState.player_hp : 100;
  const gold = isLive ? gameState.gold : 0;
  const level = isLive ? gameState.level : 1;
  const componentIds = isLive ? (gameState.component_ids || []) : manualComponents;

  // Use backend coaching if available, otherwise compute client-side
  const backendAdvice = isLive ? gameState.advice : null;
  const slamUrgency = backendAdvice
    ? { level: backendAdvice.slam_urgency_level, color: getSlamUrgencyFromStage(stage).color }
    : getSlamUrgencyFromStage(stage);
  const slamMessage = backendAdvice?.slam_urgency_message || "";
  const slamRecs = backendAdvice?.slam_recommendations || [];
  const tips = backendAdvice?.tips || [];
  const augmentRatings = backendAdvice?.augment_ratings || [];
  const selectedAugments = isLive ? (gameState?.selected_augments || []) : [];
  const [lastAugmentRatings, setLastAugmentRatings] = useState([]);
  useEffect(() => {
    if (augmentRatings.length > 0) setLastAugmentRatings(augmentRatings);
  }, [augmentRatings]);
  const shownAugmentRatings = augmentRatings.length > 0
    ? augmentRatings : lastAugmentRatings;
  const compSuggestions = backendAdvice?.comp_suggestions || [];
  const shopActions = backendAdvice?.shop_actions || [];
  const boardPower = backendAdvice?.board_power ?? null;
  const boardPowerBreakdown = backendAdvice?.board_power_breakdown ?? null;
  const lobbyHp = isLive ? (gameState?.lobby_hp || []) : [];
  const heldItems = isLive ? (gameState?.held_items || []) : [];
  const activeSynergies = isLive ? (gameState?.active_synergies || []) : [];
  const captureMethod = isLive ? (gameState?.capture_method || "screen") : "screen";

  // Champion data for the Comp/Position tabs
  const boardChampions = isLive ? (gameState?.board_champions || []) : [];
  const benchChampions = isLive ? (gameState?.bench_champions || []) : [];

  // Comp pinning — clicking a suggestion locks it as "my comp"; the
  // backend then keeps it first and boosts its augments. Local state is
  // the source for manual mode; live mode reflects the server's echo.
  const [localPin, setLocalPin] = useState(null);
  const pinnedComp = (isLive ? gameState?.pinned_comp : localPin) ?? localPin;
  const togglePin = (c) => {
    const name = c.tftacademy_name || c.name;
    const next = pinnedComp === name ? null : name;
    setLocalPin(next);
    sendCommand("pin_comp", { name: next });
  };
  const pinnedSuggestion = compSuggestions.find(
    (c) => (c.tftacademy_name || c.name) === pinnedComp
  );

  // During augment selection, jump to the Augments tab automatically and
  // return to wherever the player was afterwards.
  const preAugmentTabRef = useRef(null);
  useEffect(() => {
    if (isLive && gameState?.phase === "augment_select") {
      if (preAugmentTabRef.current === null) {
        preAugmentTabRef.current = tab;
        setTab("augments");
      }
    } else if (preAugmentTabRef.current !== null) {
      setTab(preAugmentTabRef.current);
      preAugmentTabRef.current = null;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gameState?.phase, isLive]);

  // Positioning-specific data (drives the Position tab)
  const recommendedTemplateName = backendAdvice?.positioning_template || null;
  const positioningTips = useMemo(
    () => tips.filter(t => POSITIONING_KEYWORDS.test(t)),
    [tips]
  );
  const positioningSuggestions = backendAdvice?.positioning_suggestions || [];

  // When the backend recommends a template, auto-select it
  useEffect(() => {
    if (!recommendedTemplateName) return;
    const idx = POSITIONING_TEMPLATES.findIndex(
      t => t.name.toLowerCase() === recommendedTemplateName.toLowerCase()
    );
    if (idx >= 0) setSelectedTemplate(idx);
  }, [recommendedTemplateName]);

  const craftableItems = useMemo(
    () => getCraftableItems(componentIds, itemRecipes),
    [componentIds, itemRecipes]
  );

  const toggleManualComponent = (id) => {
    setManualComponents((prev) =>
      prev.includes(id) ? prev.filter((c) => c !== id) : prev.length < 10 ? [...prev, id] : prev
    );
  };

  // Warn color for slam urgency
  const warn = slamUrgency.color;

  return (
    <div
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      style={{
        minHeight: "100vh",
        background: "rgba(13, 14, 18, 0.92)",
        color: "#e4e5ea",
        fontFamily: "'Inter', 'Segoe UI', system-ui, sans-serif",
      }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700;800&family=Inter:wght@400;500;600;700&family=Orbitron:wght@700;900&display=swap');
        :root { --mono: 'JetBrains Mono', 'Fira Code', monospace; }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        ::-webkit-scrollbar { width: 5px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #3a3d4a; border-radius: 3px; }
        @keyframes slideIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes blink { 0%,100% { opacity: 1; } 50% { opacity: 0.5; } }
        .card { background: rgba(21,22,28,0.95); border: 1px solid #2a2d35; border-radius: 10px; padding: 14px; }
        .item-row:hover { background: rgba(255,255,255,0.03); }
      `}</style>

      {/* ── HEADER ── */}
      <div style={{
        background: "rgba(13,14,18,0.98)", borderBottom: `1px solid ${ACCENT}15`,
        padding: "14px 16px", display: "flex", alignItems: "center",
        justifyContent: "space-between", position: "sticky", top: 0, zIndex: 10,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          <div style={{
            fontFamily: "'Orbitron', sans-serif", fontSize: "16px", fontWeight: 900,
            background: `linear-gradient(135deg, ${ACCENT}, ${ACCENT2})`,
            WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent",
            letterSpacing: "2px",
          }}>
            TFT COACH
          </div>
          {isConnected && backendProtocol !== null && backendProtocol !== BACKEND_PROTOCOL_EXPECTED && (
            <span
              title={`The running backend speaks payload v${backendProtocol}, this overlay expects v${BACKEND_PROTOCOL_EXPECTED}. Pull the latest code and restart the backend (and this overlay) — data fields will be missing or wrong until then.`}
              style={{
                fontFamily: "var(--mono)", fontSize: "9px", fontWeight: 700,
                letterSpacing: "1px", padding: "3px 8px", borderRadius: "5px",
                color: "#ff4757", border: "1px solid #ff475766",
                background: "#ff475712", animation: "blink 1.6s infinite",
              }}
            >
              ⚠ BACKEND OUTDATED (v{backendProtocol}≠v{BACKEND_PROTOCOL_EXPECTED})
            </span>
          )}
          <ConnectionBadge isConnected={isConnected} isDemo={isDemo} />
          {inElectron && (
            <span
              title={hoverLocked
                ? "Ghost lock — overlay never captures the mouse; scout and click the game freely. Ctrl+Shift+G to unlock."
                : isInteractive
                ? "Interactive — clicks stay on the overlay. Hotkeys: Ctrl+Shift+G ghost lock · Ctrl+Shift+H hide · Ctrl+Shift+Q quit"
                : "Ghost mode — clicks pass through to the game (hover to interact). Hotkeys: Ctrl+Shift+G ghost lock · Ctrl+Shift+H hide · Ctrl+Shift+Q quit"}
              style={{
                fontFamily: "var(--mono)", fontSize: "9px", fontWeight: 700,
                letterSpacing: "1px", padding: "3px 8px", borderRadius: "5px",
                color: hoverLocked ? "#f59e0b" : isInteractive ? "#4ade80" : "#8b8fa3",
                border: `1px solid ${hoverLocked ? "#f59e0b55" : isInteractive ? "#4ade8040" : "#2a2d35"}`,
              }}
            >
              {hoverLocked ? "🔒 LOCKED" : isInteractive ? "🖱 ACTIVE" : "👻 GHOST"}
            </span>
          )}
        </div>
        <div style={{ display: "flex", gap: "6px" }}>
          {inElectron && (
            <button
              onClick={() => window.electronAPI.setShareMode?.(!shareMode)}
              title="Ctrl+Shift+R · Toggle visibility in Discord streams and screenshots"
              style={{
                background: shareMode ? "#2ed57318" : "none",
                border: `1px solid ${shareMode ? "#2ed57366" : "#2a2d35"}`,
                borderRadius: "6px", color: shareMode ? "#2ed573" : "#8b8fa3",
                padding: "4px 10px", cursor: "pointer",
                fontFamily: "var(--mono)", fontSize: "10px", fontWeight: 700,
              }}
            >
              {shareMode ? "📡 SHARE ON" : "SHARE"}
            </button>
          )}
          {isDemo && (
            <button
              onClick={() => setDevOpen(!devOpen)}
              style={{
                background: devOpen ? `${ACCENT}18` : "none",
                border: `1px solid ${devOpen ? ACCENT : "#2a2d35"}`,
                borderRadius: "6px",
                color: devOpen ? ACCENT : "#8b8fa3",
                padding: "4px 10px", cursor: "pointer",
                fontFamily: "var(--mono)", fontSize: "10px",
                fontWeight: 700, letterSpacing: "1px",
              }}
            >
              DEV
            </button>
          )}
          <button
            onClick={() => setCollapsed(!collapsed)}
            style={{
              background: "none", border: "1px solid #2a2d35", borderRadius: "6px",
              color: "#8b8fa3", padding: "4px 10px", cursor: "pointer",
              fontFamily: "var(--mono)", fontSize: "10px",
            }}
          >
            {collapsed ? "EXPAND" : "MINIMIZE"}
          </button>
        </div>
      </div>

      {isDemo && (
        <DevPanel
          open={devOpen}
          onClose={() => setDevOpen(false)}
          demoInfo={demoInfo}
          gameState={gameState}
          sendCommand={sendCommand}
        />
      )}

      {collapsed ? null : (
        <>
          {/* ── STAT BAR ── */}
          <div style={{
            padding: "10px 16px", display: "flex", gap: "16px",
            alignItems: "center", borderBottom: "1px solid #1e2028",
            background: "rgba(18,19,26,0.95)",
          }}>
            <StatBox label="HP" value={hp} color={hp > 50 ? "#2ed573" : hp > 25 ? "#ffa502" : "#ff4757"} />
            <div style={{ width: "1px", height: "24px", background: "#2a2d35" }} />
            <StatBox label="GOLD" value={gold} color="#ffd32a" />
            <div style={{ width: "1px", height: "24px", background: "#2a2d35" }} />
            <StatBox label="LVL" value={level} color="#c8cad0" />
            <div style={{ width: "1px", height: "24px", background: "#2a2d35" }} />
            <StatBox label="STAGE" value={stage} color={ACCENT} />
            {boardPower !== null && boardPowerBreakdown?.source !== "none" && (
              <>
                <div style={{ width: "1px", height: "24px", background: "#2a2d35" }} />
                <StatBox
                  label="BOARD"
                  value={Math.round(boardPower)}
                  color={boardPowerBreakdown?.label === "Strong"
                    ? "#2ed573"
                    : boardPowerBreakdown?.label === "Weak" ? "#ff6348" : "#ffa502"}
                />
              </>
            )}
          </div>

          {/* ── LOBBY STANDINGS ── */}
          <StandingsStrip lobbyHp={lobbyHp} ourHp={hp} />

          {/* ── MODE INDICATOR ── */}
          {!isLive && (
            <div style={{
              padding: "8px 16px", background: "#ffa50208",
              borderBottom: "1px solid #ffa50222", fontSize: "11px",
              color: "#ffa502", fontFamily: "var(--mono)",
              display: "flex", alignItems: "center", gap: "6px",
            }}>
              <span style={{ animation: "blink 2s infinite" }}>◉</span>
              Manual mode — select components below. Connect backend for live detection.
            </div>
          )}

          {/* ── TAB NAV ── */}
          {shareMode && isLive && (
            <div style={{
              padding: "7px 16px",
              background: captureMethod === "window" ? "#2ed5730b" : "#ff63480d",
              borderBottom: `1px solid ${captureMethod === "window" ? "#2ed5732b" : "#ff634833"}`,
              color: captureMethod === "window" ? "#2ed573" : "#ff8a75",
              fontFamily: "var(--mono)", fontSize: "9px", letterSpacing: "0.5px",
            }}>
              {captureMethod === "window"
                ? "● SHARE MODE · Direct League capture active · detection remains overlay-safe"
                : "⚠ SHARE MODE · Screen fallback active · overlay may affect covered detection regions"}
            </div>
          )}

          <div style={{ padding: "10px 16px", display: "flex", gap: "6px", borderBottom: "1px solid #1e2028", flexWrap: "wrap" }}>
            <TabBtn active={tab === "items"} onClick={() => setTab("items")}>⚔️ Items</TabBtn>
            {boardPowerBreakdown?.source !== "none" && (
              <TabBtn active={tab === "strength"} onClick={() => setTab("strength")}>
                📈 Strength {Math.round(boardPower || 0)}
              </TabBtn>
            )}
            <TabBtn active={tab === "comp"} onClick={() => setTab("comp")}>
              🎯 Comp{compSuggestions.length > 0 && ` (${compSuggestions.length})`}
            </TabBtn>
            <TabBtn active={tab === "position"} onClick={() => setTab("position")}>🗺️ Position</TabBtn>
            <TabBtn active={tab === "augments"} onClick={() => setTab("augments")}>🔮 Augments</TabBtn>
            {tips.length > 0 && (
              <TabBtn active={tab === "tips"} onClick={() => setTab("tips")}>💡 Tips ({tips.length})</TabBtn>
            )}
          </div>

          {/* ── CONTENT ── */}
          <div style={{ padding: "12px 16px", overflowY: "auto" }}>

            {tab === "strength" && (
              <div style={{ animation: "slideIn 0.25s ease" }}>
                <BoardStrengthCard
                  score={boardPower}
                  breakdown={boardPowerBreakdown}
                  stage={stage}
                />
                <div className="card" style={{ color: "#8b8fa3", fontSize: "10px", lineHeight: 1.55 }}>
                  The score updates every detected frame. Unit strength is compared with
                  same-cost champions on the latest tactics.tools patch; stars, active
                  traits, TFT Academy comp fit, equipped items, and marked augments add
                  the remaining combat value.
                </div>
              </div>
            )}

            {/* ═══ ITEMS TAB ═══ */}
            {tab === "items" && (
              <div style={{ animation: "slideIn 0.25s ease" }}>

                {/* Shop Buy Calls */}
                <ShopBuyCalls actions={shopActions} />

                {/* Slam Urgency Banner */}
                <div className="card" style={{
                  borderColor: `${warn}33`, background: `linear-gradient(135deg, ${warn}06, transparent)`,
                  marginBottom: "12px",
                }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "6px" }}>
                    <div style={{
                      width: "8px", height: "8px", borderRadius: "50%", background: warn,
                      boxShadow: `0 0 10px ${warn}66`,
                      animation: slamUrgency.level === "critical" ? "blink 0.8s infinite" : "none",
                    }} />
                    <span style={{
                      fontFamily: "var(--mono)", fontSize: "10px", fontWeight: 700,
                      color: warn, textTransform: "uppercase", letterSpacing: "2px",
                    }}>
                      {slamUrgency.level}
                    </span>
                  </div>
                  <p style={{ color: "#b0b3bf", fontSize: "12px", lineHeight: 1.5 }}>
                    {slamMessage || (slamUrgency.level === "low"
                      ? "Early game — hold components, only slam S-tier."
                      : slamUrgency.level === "medium"
                      ? "Mid game — consider slamming. Holding costs HP."
                      : slamUrgency.level === "high"
                      ? "Slam NOW. Every round without items is lost HP."
                      : "CRITICAL — Slam everything. No more holding."
                    )}
                  </p>
                </div>

                {/* Manual Component Picker (only in manual mode) */}
                {!isLive && (
                  <div className="card" style={{ marginBottom: "12px" }}>
                    <div style={{ fontSize: "9px", color: "#8b8fa3", marginBottom: "8px", fontFamily: "var(--mono)", letterSpacing: "2px" }}>
                      YOUR COMPONENTS (tap to toggle)
                    </div>
                    <div style={{ display: "flex", gap: "6px", flexWrap: "wrap" }}>
                      {COMPONENTS.map((c) => {
                        const count = manualComponents.filter((h) => h === c.id).length;
                        const active = count > 0;
                        return (
                          <button key={c.id} onClick={() => toggleManualComponent(c.id)} style={{
                            width: "48px", height: "48px", borderRadius: "8px",
                            border: active ? `2px solid ${ACCENT}` : "2px solid #2a2d35",
                            background: active ? `${ACCENT}12` : "#1a1b21",
                            display: "flex", flexDirection: "column", alignItems: "center",
                            justifyContent: "center", cursor: "pointer", transition: "all 0.1s",
                            position: "relative",
                          }}>
                            <GameIcon kind="components" name={c.id} emoji={c.icon} size={22} />
                            <span style={{ fontSize: "7px", color: active ? ACCENT : "#555", fontFamily: "var(--mono)" }}>{c.stat}</span>
                            {count > 1 && (
                              <span style={{
                                position: "absolute", top: -3, right: -3, background: ACCENT,
                                color: "#0d0e12", borderRadius: "50%", width: 14, height: 14,
                                fontSize: 9, fontWeight: 800, display: "flex", alignItems: "center",
                                justifyContent: "center",
                              }}>{count}</span>
                            )}
                          </button>
                        );
                      })}
                    </div>

                    {/* Stage selector in manual mode */}
                    <div style={{ marginTop: "10px", display: "flex", gap: "4px", flexWrap: "wrap" }}>
                      {STAGES.map((s) => (
                        <button key={s} onClick={() => setManualStage(s)} style={{
                          padding: "4px 8px", borderRadius: "5px", fontSize: "10px",
                          fontFamily: "var(--mono)", cursor: "pointer",
                          border: manualStage === s ? `1px solid ${ACCENT}` : "1px solid #2a2d35",
                          background: manualStage === s ? `${ACCENT}12` : "transparent",
                          color: manualStage === s ? ACCENT : "#555",
                        }}>{s}</button>
                      ))}
                    </div>
                  </div>
                )}

                {/* Live detected components display */}
                {isLive && componentIds.length > 0 && (
                  <div className="card" style={{ marginBottom: "12px" }}>
                    <div style={{ fontSize: "9px", color: "#8b8fa3", marginBottom: "8px", fontFamily: "var(--mono)", letterSpacing: "2px" }}>
                      DETECTED COMPONENTS ({componentIds.length})
                    </div>
                    <div style={{ display: "flex", gap: "6px", flexWrap: "wrap" }}>
                      {componentIds.map((id, idx) => {
                        const comp = COMPONENTS.find((c) => c.id === id);
                        return comp ? (
                          <div key={idx} style={{
                            padding: "6px 10px", borderRadius: "6px",
                            background: `${ACCENT}10`, border: `1px solid ${ACCENT}33`,
                            display: "flex", alignItems: "center", gap: "4px",
                          }}>
                            <GameIcon kind="components" name={comp.id} emoji={comp.icon} size={16} />
                            <span style={{ fontSize: "10px", color: ACCENT, fontFamily: "var(--mono)" }}>{comp.stat}</span>
                          </div>
                        ) : null;
                      })}
                    </div>
                  </div>
                )}

                {/* Held completed items (artifacts, radiants, specials) */}
                {isLive && heldItems.length > 0 && (
                  <div className="card" style={{ marginBottom: "12px" }}>
                    <div style={{ fontSize: "9px", color: "#8b8fa3", marginBottom: "8px", fontFamily: "var(--mono)", letterSpacing: "2px" }}>
                      HELD ITEMS ({heldItems.length})
                    </div>
                    <div style={{ display: "flex", gap: "6px", flexWrap: "wrap" }}>
                      {heldItems.map((name, idx) => (
                        <div key={idx} style={{
                          padding: "6px 10px", borderRadius: "6px",
                          background: "#ffd32a10", border: "1px solid #ffd32a33",
                          display: "flex", alignItems: "center", gap: "4px",
                        }}>
                          <GameIcon kind="items" name={name} emoji="🗡️" size={16} />
                          <span style={{ fontSize: "10px", color: "#ffd32a", fontFamily: "var(--mono)" }}>{name}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Craftable Items */}
                <div style={{ fontSize: "9px", color: "#8b8fa3", marginBottom: "8px", fontFamily: "var(--mono)", letterSpacing: "2px" }}>
                  CRAFTABLE ITEMS ({craftableItems.length})
                </div>

                {craftableItems.length === 0 ? (
                  <div className="card" style={{ textAlign: "center", color: "#555", padding: "24px", fontSize: "12px" }}>
                    {isLive ? "No components detected" : "Select 2+ components above"}
                  </div>
                ) : (
                  <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                    {craftableItems.map((item, idx) => {
                      // Check if backend recommends slamming this item
                      const rec = slamRecs.find((r) => r.item_name === item.name);
                      const shouldSlam = item.slam || rec?.slam_urgency === "slam_now";

                      return (
                        <div key={idx} className="card item-row" style={{
                          borderColor: shouldSlam ? `${warn}44` : "#2a2d35",
                          padding: "10px 12px", transition: "all 0.15s",
                          display: "flex", alignItems: "center", gap: "10px",
                        }}>
                          <GameIcon kind="items" name={item.name} emoji={item.icon} size={26} />
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{ display: "flex", alignItems: "center", gap: "6px", flexWrap: "wrap" }}>
                              <span style={{ fontWeight: 600, fontSize: "13px" }}>{item.name}</span>
                              <TierBadge tier={item.tier} />
                              {shouldSlam && (
                                <span style={{
                                  fontSize: "8px", fontWeight: 700, color: warn,
                                  background: `${warn}15`, padding: "1px 6px",
                                  borderRadius: "3px", fontFamily: "var(--mono)",
                                  border: `1px solid ${warn}33`, letterSpacing: "1px",
                                }}>SLAM</span>
                              )}
                              {item.shred && (
                                <span style={{
                                  fontSize: "8px", fontWeight: 700, color: "#a29bfe",
                                  background: "#a29bfe15", padding: "1px 6px",
                                  borderRadius: "3px", fontFamily: "var(--mono)",
                                  border: "1px solid #a29bfe33", letterSpacing: "1px",
                                }}>SHRED</span>
                              )}
                              {item.burn && (
                                <span style={{
                                  fontSize: "8px", fontWeight: 700, color: "#ff7675",
                                  background: "#ff767515", padding: "1px 6px",
                                  borderRadius: "3px", fontFamily: "var(--mono)",
                                  border: "1px solid #ff767533", letterSpacing: "1px",
                                }}>BURN</span>
                              )}
                            </div>
                            {rec?.reason && (
                              <div style={{ fontSize: "10px", color: "#888", marginTop: "3px", lineHeight: 1.4 }}>
                                {rec.reason}
                              </div>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            )}

            {/* ═══ COMP TAB ═══ */}
            {tab === "comp" && (
              <div style={{ animation: "slideIn 0.25s ease" }}>

                {/* Your Current Units */}
                <div style={{
                  fontSize: "9px", color: "#8b8fa3", marginBottom: "8px",
                  fontFamily: "var(--mono)", letterSpacing: "2px",
                }}>
                  YOUR UNITS ({boardChampions.length} board{benchChampions.length > 0 ? ` · ${benchChampions.length} bench` : ""})
                </div>

                {boardChampions.length === 0 && benchChampions.length === 0 ? (
                  <div className="card" style={{
                    textAlign: "center", padding: "16px", color: "#555",
                    fontSize: "11px", marginBottom: "12px",
                  }}>
                    {isLive
                      ? "No units detected yet — buy or place units to see your roster."
                      : "Connect backend to see your live roster."}
                  </div>
                ) : (
                  <div className="card" style={{ marginBottom: "14px" }}>
                    {boardChampions.length > 0 && (
                      <>
                        <div style={{
                          fontSize: "8px", color: "#666", marginBottom: "6px",
                          fontFamily: "var(--mono)", letterSpacing: "2px",
                        }}>BOARD</div>
                        <div style={{ display: "flex", flexWrap: "wrap", gap: "5px" }}>
                          {boardChampions.map((u, i) => (
                            <UnitChip key={`b-${i}`} unit={u} itemIcons={ITEM_ICONS} />
                          ))}
                        </div>
                      </>
                    )}
                    {benchChampions.length > 0 && (
                      <>
                        <div style={{
                          fontSize: "8px", color: "#666", margin: "10px 0 6px",
                          fontFamily: "var(--mono)", letterSpacing: "2px",
                        }}>BENCH</div>
                        <div style={{ display: "flex", flexWrap: "wrap", gap: "5px" }}>
                          {benchChampions.map((u, i) => (
                            <UnitChip key={`be-${i}`} unit={u} itemIcons={ITEM_ICONS} dim />
                          ))}
                        </div>
                      </>
                    )}
                  </div>
                )}

                {/* Active Synergies */}
                <div style={{
                  fontSize: "9px", color: "#8b8fa3", marginBottom: "8px",
                  fontFamily: "var(--mono)", letterSpacing: "2px",
                }}>
                  ACTIVE SYNERGIES ({activeSynergies.filter(s => s.is_active).length} active)
                </div>

                {activeSynergies.length === 0 ? (
                  <div className="card" style={{
                    textAlign: "center", padding: "16px", color: "#555",
                    fontSize: "11px", marginBottom: "12px",
                  }}>
                    {isLive
                      ? "Place units on the board to see active traits."
                      : "Connect backend for live synergy detection."}
                  </div>
                ) : (
                  <div className="card" style={{ marginBottom: "14px" }}>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
                      {activeSynergies.map((s, i) => (
                        <SynergyPill key={i} synergy={s} />
                      ))}
                    </div>
                  </div>
                )}

                {/* Comp Suggestions */}
                <div style={{
                  fontSize: "9px", color: "#8b8fa3", marginBottom: "8px",
                  fontFamily: "var(--mono)", letterSpacing: "2px",
                }}>
                  COMP DIRECTION
                </div>

                {compSuggestions.length === 0 ? (
                  <div className="card" style={{
                    textAlign: "center", padding: "30px", color: "#555",
                  }}>
                    <div style={{ fontSize: "28px", marginBottom: "8px" }}>🎯</div>
                    <div style={{ fontSize: "12px", lineHeight: 1.5 }}>
                      Comp suggestions appear once you have a few units on the board.
                      {!isLive && " (connect backend for live detection)"}
                    </div>
                  </div>
                ) : (
                  <>
                    <div style={{
                      fontSize: "9px", color: "#5a5e6b", marginBottom: "8px",
                      fontFamily: "var(--mono)",
                    }}>
                      📌 PIN a comp to lock it — advice, augments, and the item
                      plan will follow it.
                    </div>
                    {compSuggestions.map((c, i) => (
                      <CompCard
                        key={i}
                        comp={c}
                        primary={c.is_primary}
                        pinned={c.is_pinned || (c.tftacademy_name || c.name) === pinnedComp}
                        onPin={() => togglePin(c)}
                      />
                    ))}
                  </>
                )}

                {/* Item plan for the locked comp */}
                {pinnedSuggestion?.board_layout?.length > 0 && (
                  <ItemPlan
                    suggestion={pinnedSuggestion}
                    componentIds={componentIds}
                    itemRecipes={itemRecipes}
                  />
                )}

                {/* Footnote when at least one comp had a TFT Academy match */}
                {compSuggestions.some(c => c.tftacademy_tier) && (
                  <div style={{
                    marginTop: "8px", padding: "8px 10px",
                    fontSize: "10px", color: "#5a5e6b", fontFamily: "var(--mono)",
                    textAlign: "right",
                  }}>
                    Tier ratings from{" "}
                    <a href="https://tftacademy.com/tierlist/comps"
                       target="_blank" rel="noreferrer"
                       style={{ color: "#7a8090", textDecoration: "underline" }}>
                      tftacademy.com
                    </a>
                  </div>
                )}
              </div>
            )}

            {/* ═══ POSITIONING TAB ═══ */}
            {tab === "position" && (
              <div style={{ animation: "slideIn 0.25s ease" }}>

                {/* ── LIVE BOARD ── */}
                {isLive && boardChampions.length > 0 ? (
                  <>
                    <div style={{
                      fontSize: "9px", color: "#8b8fa3", marginBottom: "8px",
                      fontFamily: "var(--mono)", letterSpacing: "2px",
                      display: "flex", alignItems: "center", gap: "8px",
                    }}>
                      <span style={{ color: "#2ed573" }}>●</span>
                      YOUR CURRENT BOARD ({boardChampions.filter(c => c.board_row != null).length} placed)
                    </div>
                    <div className="card" style={{ marginBottom: "14px" }}>
                      <LiveBoard
                        champions={boardChampions}
                        itemIcons={ITEM_ICONS}
                        highlightTemplate={
                          recommendedTemplateName
                            ? POSITIONING_TEMPLATES[selectedTemplate]?.layout
                            : null
                        }
                      />
                      {recommendedTemplateName && (
                        <div style={{
                          marginTop: "10px", padding: "6px 10px",
                          background: `${ACCENT}10`, border: `1px solid ${ACCENT}33`,
                          borderRadius: "5px", fontSize: "10px",
                          color: ACCENT, fontFamily: "var(--mono)",
                          display: "flex", alignItems: "center", gap: "6px",
                        }}>
                          <span>💡</span>
                          <span>Coach suggests: <strong>{recommendedTemplateName}</strong> — see dashed cells for target positions.</span>
                        </div>
                      )}
                    </div>

                    {/* ── LIVE POSITIONING ADVICE ── */}
                    {(positioningTips.length > 0 || positioningSuggestions.length > 0) && (
                      <>
                        <div style={{
                          fontSize: "9px", color: ACCENT, marginBottom: "8px",
                          fontFamily: "var(--mono)", letterSpacing: "2px",
                        }}>
                          COACH SAYS
                        </div>
                        <div className="card" style={{
                          marginBottom: "14px", borderLeft: `3px solid ${ACCENT}`,
                        }}>
                          {positioningSuggestions.map((s, i) => (
                            <div key={`s-${i}`} style={{
                              display: "flex", gap: "8px", padding: "6px 0",
                              borderBottom: i < positioningSuggestions.length - 1 ? "1px solid #1e2028" : "none",
                            }}>
                              <span style={{
                                fontSize: "10px", color: ACCENT2, fontWeight: 700,
                                fontFamily: "var(--mono)", flexShrink: 0,
                              }}>
                                {s.champion_name}
                              </span>
                              <span style={{ fontSize: "11px", color: "#b0b3bf", lineHeight: 1.4 }}>
                                → ({s.to_row}, {s.to_col}): {s.reason}
                              </span>
                            </div>
                          ))}
                          {positioningTips.map((tip, i) => (
                            <div key={`t-${i}`} style={{
                              display: "flex", gap: "8px", padding: "6px 0",
                              borderTop: (i > 0 || positioningSuggestions.length > 0) ? "1px solid #1e2028" : "none",
                            }}>
                              <span style={{
                                color: ACCENT, fontSize: "10px", fontWeight: 700,
                                fontFamily: "var(--mono)", flexShrink: 0,
                              }}>
                                ▸
                              </span>
                              <span style={{ fontSize: "11px", color: "#b0b3bf", lineHeight: 1.4 }}>
                                {tip}
                              </span>
                            </div>
                          ))}
                        </div>
                      </>
                    )}
                  </>
                ) : (
                  <div className="card" style={{
                    textAlign: "center", padding: "20px", marginBottom: "14px",
                    color: "#666", fontSize: "11px",
                  }}>
                    {isLive
                      ? "Place units on the board to see live positioning analysis."
                      : "Connect backend for live positioning advice. Reference templates below."}
                  </div>
                )}

                {/* ── META LAYOUT — TFT Academy's board for your comp ── */}
                {compSuggestions[0]?.board_layout?.length > 0 && (
                  <>
                    <div style={{
                      fontSize: "9px", color: ACCENT2, marginBottom: "8px",
                      fontFamily: "var(--mono)", letterSpacing: "2px",
                      display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap",
                    }}>
                      META LAYOUT — {(compSuggestions[0].tftacademy_name || compSuggestions[0].name).toUpperCase()}
                      {compSuggestions[0].tftacademy_tier && (
                        <TierBadge tier={compSuggestions[0].tftacademy_tier} />
                      )}
                    </div>
                    <div className="card" style={{ marginBottom: "14px" }}>
                      <LiveBoard
                        champions={compSuggestions[0].board_layout.map((u) => ({
                          name: u.name,
                          board_row: Math.floor(u.board_index / 7),
                          board_col: u.board_index % 7,
                          star_level: u.stars,
                          items: u.items,
                          cost: u.cost,
                        }))}
                        itemIcons={ITEM_ICONS}
                      />
                      <div style={{
                        marginTop: "8px", fontSize: "10px", color: "#8b8fa3",
                        lineHeight: 1.5,
                      }}>
                        TFT Academy's recommended final board for your top comp —
                        stars show the target star level, icons the target items.
                      </div>
                    </div>
                  </>
                )}

                {/* ── REFERENCE TEMPLATES ── */}
                <div style={{
                  fontSize: "9px", color: "#8b8fa3", marginBottom: "8px",
                  fontFamily: "var(--mono)", letterSpacing: "2px",
                }}>
                  REFERENCE TEMPLATES
                </div>

                <div style={{ display: "flex", gap: "6px", marginBottom: "12px", flexWrap: "wrap" }}>
                  {POSITIONING_TEMPLATES.map((t, i) => {
                    const isRecommended = recommendedTemplateName
                      && t.name.toLowerCase() === recommendedTemplateName.toLowerCase();
                    return (
                      <button key={i} onClick={() => setSelectedTemplate(i)} style={{
                        padding: "7px 12px", borderRadius: "6px", fontSize: "11px",
                        cursor: "pointer", transition: "all 0.15s",
                        border: selectedTemplate === i ? `1px solid ${ACCENT2}` : "1px solid #2a2d35",
                        background: selectedTemplate === i ? `${ACCENT2}15` : "transparent",
                        color: selectedTemplate === i ? ACCENT2 : "#8b8fa3",
                        fontWeight: selectedTemplate === i ? 700 : 400,
                        display: "inline-flex", alignItems: "center", gap: "5px",
                      }}>
                        {t.name}
                        {isRecommended && (
                          <span style={{
                            fontSize: "7px", padding: "1px 4px", borderRadius: "3px",
                            background: `${ACCENT}25`, color: ACCENT,
                            fontFamily: "var(--mono)", letterSpacing: "1px",
                          }}>REC</span>
                        )}
                      </button>
                    );
                  })}
                </div>

                <div className="card" style={{ marginBottom: "12px" }}>
                  <div style={{ fontWeight: 700, fontSize: "14px", marginBottom: "2px" }}>
                    {POSITIONING_TEMPLATES[selectedTemplate].name}
                  </div>
                  <div style={{ fontSize: "11px", color: "#8b8fa3", marginBottom: "12px" }}>
                    {POSITIONING_TEMPLATES[selectedTemplate].desc}
                  </div>

                  {/* Template Grid */}
                  <div style={{
                    background: "#0a0b0f", borderRadius: "8px", padding: "16px",
                    border: "1px solid #1e2028", marginBottom: "12px",
                  }}>
                    <div style={{ fontSize: "8px", color: "#ff475733", fontFamily: "var(--mono)", letterSpacing: "2px", textAlign: "center", marginBottom: "10px" }}>
                      ▲ ENEMY ▲
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", gap: "3px", alignItems: "center" }}>
                      {POSITIONING_TEMPLATES[selectedTemplate].layout.map((row, ri) => (
                        <div key={ri} style={{ display: "flex", gap: "3px", marginLeft: ri % 2 === 1 ? "22px" : "0" }}>
                          {row.map((cell, ci) => {
                            const isUnit = cell !== 0;
                            const color = cell === "T" ? "#ff6348" : cell === "C" ? "#ffd32a" : cell === "S" ? "#2ed573" : "transparent";
                            return (
                              <div key={ci} style={{
                                width: "40px", height: "40px", borderRadius: "6px",
                                border: isUnit ? `2px solid ${color}` : "1px solid #1a1b21",
                                background: isUnit ? `${color}12` : "#13141a",
                                display: "flex", flexDirection: "column",
                                alignItems: "center", justifyContent: "center",
                              }}>
                                {isUnit && (
                                  <>
                                    <div style={{ width: 10, height: 10, borderRadius: "50%", background: color, boxShadow: `0 0 6px ${color}44` }} />
                                    <span style={{ fontSize: "6px", fontWeight: 700, color, fontFamily: "var(--mono)", marginTop: 1 }}>
                                      {cell === "T" ? "TANK" : cell === "C" ? "CARRY" : "SUPP"}
                                    </span>
                                  </>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      ))}
                    </div>
                    <div style={{ fontSize: "8px", color: `${ACCENT}33`, fontFamily: "var(--mono)", letterSpacing: "2px", textAlign: "center", marginTop: "10px" }}>
                      ▼ YOUR SIDE ▼
                    </div>
                  </div>

                  {POSITIONING_TEMPLATES[selectedTemplate].tips.map((tip, i) => (
                    <div key={i} style={{
                      display: "flex", gap: "8px", padding: "8px 10px",
                      background: "#0a0b0f", borderRadius: "6px", border: "1px solid #1e2028",
                      marginBottom: "4px",
                    }}>
                      <span style={{ color: ACCENT2, fontSize: "10px", fontWeight: 700, fontFamily: "var(--mono)" }}>
                        {String(i + 1).padStart(2, "0")}
                      </span>
                      <span style={{ fontSize: "11px", color: "#b0b3bf", lineHeight: 1.4 }}>{tip}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* ═══ AUGMENTS TAB ═══ */}
            {tab === "augments" && (
              <div style={{ animation: "slideIn 0.25s ease" }}>
                {shownAugmentRatings.length > 0 ? (
                  <>
                    <div style={{ fontSize: "9px", color: augmentRatings.length > 0 ? "#2ed573" : "#8b8fa3", fontFamily: "var(--mono)", letterSpacing: "2px", marginBottom: "10px" }}>
                      {augmentRatings.length > 0
                        ? "● AUGMENT SELECTION DETECTED"
                        : "LAST AUGMENT OPTIONS — MARK YOUR PICK"}
                    </div>
                    {shownAugmentRatings.map((aug, i) => {
                      const tierColor = aug.tier === "Prismatic" ? "#ff4757" : aug.tier === "Gold" ? "#ffd32a" : "#c0c0c0";
                      const isTaken = selectedAugments.includes(aug.name);
                      return (
                        <div key={i} className="card" style={{
                          marginBottom: "8px",
                          borderLeft: `3px solid ${TIER_COLORS[aug.rating] || "#555"}`,
                          ...(aug.pick && {
                            border: "1px solid #2ed57355",
                            borderLeft: "3px solid #2ed573",
                            background: "rgba(46,213,115,0.05)",
                          }),
                        }}>
                          <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "6px", flexWrap: "wrap" }}>
                            <span style={{ fontWeight: 600, fontSize: "14px" }}>{aug.name}</span>
                            <TierBadge tier={aug.rating} />
                            <span style={{
                              fontSize: "8px", fontWeight: 700, color: tierColor,
                              background: `${tierColor}12`, padding: "2px 6px",
                              borderRadius: "3px", fontFamily: "var(--mono)",
                              letterSpacing: "1px", border: `1px solid ${tierColor}22`,
                            }}>{aug.tier?.toUpperCase()}</span>
                            {aug.pick && (
                              <span style={{
                                fontSize: "8px", fontWeight: 800, color: "#2ed573",
                                background: "#2ed57318", padding: "2px 7px",
                                borderRadius: "3px", fontFamily: "var(--mono)",
                                letterSpacing: "1px", border: "1px solid #2ed57344",
                              }}>★ PICK</span>
                            )}
                            <div style={{ flex: 1 }} />
                            <button
                              onClick={() => sendCommand("select_augment", {
                                name: aug.name,
                                selected: !isTaken,
                              })}
                              style={{
                                fontSize: "8px", fontWeight: 800, cursor: "pointer",
                                color: isTaken ? "#2ed573" : "#8b8fa3",
                                background: isTaken ? "#2ed57318" : "transparent",
                                padding: "3px 7px", borderRadius: "3px",
                                fontFamily: "var(--mono)", letterSpacing: "1px",
                                border: isTaken ? "1px solid #2ed57355" : "1px solid #3a3d4a",
                              }}>
                              {isTaken ? "✓ TAKEN" : "MARK TAKEN"}
                            </button>
                          </div>
                          {(aug.reasons || []).map((reason, ri) => (
                            <div key={ri} style={{
                              fontSize: "10px", color: "#2ed573", marginBottom: "4px",
                              display: "flex", gap: "5px", alignItems: "center",
                            }}>
                              <span>▸</span><span>{reason}</span>
                            </div>
                          ))}
                          <p style={{ fontSize: "11px", color: "#a0a3b0", lineHeight: 1.4 }}>
                            💡 {aug.tip}
                          </p>
                        </div>
                      );
                    })}
                  </>
                ) : (
                  <div className="card" style={{ textAlign: "center", padding: "30px", color: "#555" }}>
                    <div style={{ fontSize: "28px", marginBottom: "8px" }}>🔮</div>
                    <div style={{ fontSize: "12px", lineHeight: 1.5 }}>
                      Augment advice will appear here when the augment selection screen is detected
                      {!isLive && " (connect backend for live detection)"}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* ═══ TIPS TAB ═══ */}
            {tab === "tips" && (
              <div style={{ animation: "slideIn 0.25s ease" }}>
                {tips.length > 0 ? tips.map((tip, i) => (
                  <div key={i} className="card" style={{ marginBottom: "8px", borderLeft: `3px solid ${ACCENT}` }}>
                    <p style={{ fontSize: "12px", color: "#c8cad0", lineHeight: 1.5 }}>{tip}</p>
                  </div>
                )) : (
                  <div className="card" style={{ textAlign: "center", padding: "30px", color: "#555", fontSize: "12px" }}>
                    No tips at the moment
                  </div>
                )}
              </div>
            )}
          </div>

          {/* ── FOOTER ── */}
          <div style={{
            padding: "8px 16px", borderTop: "1px solid #1e2028",
            display: "flex", justifyContent: "space-between",
            fontSize: "9px", color: "#2a2d35", fontFamily: "var(--mono)",
          }}>
            <span>v0.1</span>
            {gameData?.classifier_status && (
              <span title={gameData.classifier_status.active
                ? "Unit classifier model is active"
                : "No model is installed yet; collecting labeled bench crops for later training"}>
                ML {gameData.classifier_status.active ? "ON" : "COLLECTING"}
                {` · ${gameData.classifier_status.crops} crops · ${gameData.classifier_status.ready_classes} ready`}
              </span>
            )}
            {serverStats && (
              <span>
                {serverStats.avg_detection_ms?.toFixed(0)}ms · f{serverStats.frames_processed}
              </span>
            )}
          </div>
        </>
      )}
    </div>
  );
}
