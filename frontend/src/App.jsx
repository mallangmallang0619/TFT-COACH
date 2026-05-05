import { useState, useEffect, useMemo, useCallback } from "react";
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
  "Guardbreaker": "🛡️",
  "Bramble Vest": "🌿",
  "Gargoyle Stoneplate": "🗿",
  "Titan's Resolve": "🏛️",
  "Protector's Vow": "🔵",
  "Steadfast Heart": "🫀",
  "Dragon's Claw": "🐉",
  "Kraken Slayer": "🦑",
  "Jaksho": "🧊",
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

//TODO: NEED TO CHANGE POSITIONING TEMPLATES AS THIS DOESN'T WORK... just a temp work
const POSITIONING_TEMPLATES = [
  {
    name: "Standard Frontline",
    desc: "2-3 tanks front, carries backline corners",
    layout: [[0,0,0,0,0,0,0],[0,0,0,0,0,0,0],[0,0,0,0,"S","S",0],["T","T","T",0,0,"C","C"]],
    tips: ["Main carry in far corner (bottom-right)","Tanks absorb aggro and buy time","Support units adjacent to carry for aura items"],
  },
  {
    name: "Anti-Assassin",
    desc: "Clump in corner to block assassin jumps",
    layout: [[0,0,0,0,0,0,0],[0,0,0,0,0,0,0],[0,0,0,0,"S","T","T"],[0,0,0,0,"S","C","T"]],
    tips: ["Assassins target furthest unit — cornering protects carry","Surround carry so assassins can't reach","Consider Quicksilver on carry for CC immunity"],
  },
  {
    name: "Spread",
    desc: "Spread to minimize AoE damage",
    layout: [[0,0,0,0,0,0,0],[0,0,0,0,0,0,0],[0,"S",0,"S",0,"C",0],["T",0,"T",0,"T",0,0]],
    tips: ["Counters AoE abilities and burn items","Leave gaps between units to limit splash","Sacrifice some synergy for survivability"],
  },
  {
    name: "Backline Stack",
    desc: "All units back row for max distance",
    layout: [[0,0,0,0,0,0,0],[0,0,0,0,0,0,0],[0,0,0,0,0,0,0],["T","T",0,"S","S","C","C"]],
    tips: ["Maximizes time before melee contact","Works best with strong CC or shields","Vulnerable to Zephyr — scout opponents"],
  },
];

const TIER_COLORS = { S: "#ff4757", A: "#ffa502", B: "#2ed573", C: "#747d8c" };
const ACCENT = "#00d2ff";
const ACCENT2 = "#7c5cfc";

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

// ─── MAIN APP ────────────────────────────────────────────────────────────────

export default function App() {
  const { gameState, gameData, isConnected, isDemo, serverStats } = useCoachSocket();

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
    <div style={{
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
          <ConnectionBadge isConnected={isConnected} isDemo={isDemo} />
        </div>
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
          </div>

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
          <div style={{ padding: "10px 16px", display: "flex", gap: "6px", borderBottom: "1px solid #1e2028", flexWrap: "wrap" }}>
            <TabBtn active={tab === "items"} onClick={() => setTab("items")}>⚔️ Items</TabBtn>
            <TabBtn active={tab === "position"} onClick={() => setTab("position")}>🗺️ Position</TabBtn>
            <TabBtn active={tab === "augments"} onClick={() => setTab("augments")}>🔮 Augments</TabBtn>
            {tips.length > 0 && (
              <TabBtn active={tab === "tips"} onClick={() => setTab("tips")}>💡 Tips ({tips.length})</TabBtn>
            )}
          </div>

          {/* ── CONTENT ── */}
          <div style={{ padding: "12px 16px", overflowY: "auto" }}>

            {/* ═══ ITEMS TAB ═══ */}
            {tab === "items" && (
              <div style={{ animation: "slideIn 0.25s ease" }}>

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
                            <span style={{ fontSize: "18px" }}>{c.icon}</span>
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
                            <span style={{ fontSize: "14px" }}>{comp.icon}</span>
                            <span style={{ fontSize: "10px", color: ACCENT, fontFamily: "var(--mono)" }}>{comp.stat}</span>
                          </div>
                        ) : null;
                      })}
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
                          <span style={{ fontSize: "22px", flexShrink: 0 }}>{item.icon}</span>
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

            {/* ═══ POSITIONING TAB ═══ */}
            {tab === "position" && (
              <div style={{ animation: "slideIn 0.25s ease" }}>
                <div style={{ display: "flex", gap: "6px", marginBottom: "12px", flexWrap: "wrap" }}>
                  {POSITIONING_TEMPLATES.map((t, i) => (
                    <button key={i} onClick={() => setSelectedTemplate(i)} style={{
                      padding: "7px 12px", borderRadius: "6px", fontSize: "11px",
                      cursor: "pointer", transition: "all 0.15s",
                      border: selectedTemplate === i ? `1px solid ${ACCENT2}` : "1px solid #2a2d35",
                      background: selectedTemplate === i ? `${ACCENT2}15` : "transparent",
                      color: selectedTemplate === i ? ACCENT2 : "#8b8fa3",
                      fontWeight: selectedTemplate === i ? 700 : 400,
                    }}>{t.name}</button>
                  ))}
                </div>

                <div className="card" style={{ marginBottom: "12px" }}>
                  <div style={{ fontWeight: 700, fontSize: "14px", marginBottom: "2px" }}>
                    {POSITIONING_TEMPLATES[selectedTemplate].name}
                  </div>
                  <div style={{ fontSize: "11px", color: "#8b8fa3", marginBottom: "12px" }}>
                    {POSITIONING_TEMPLATES[selectedTemplate].desc}
                  </div>

                  {/* Grid */}
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
                {augmentRatings.length > 0 ? (
                  <>
                    <div style={{ fontSize: "9px", color: "#2ed573", fontFamily: "var(--mono)", letterSpacing: "2px", marginBottom: "10px" }}>
                      ● AUGMENT SELECTION DETECTED
                    </div>
                    {augmentRatings.map((aug, i) => {
                      const tierColor = aug.tier === "Prismatic" ? "#ff4757" : aug.tier === "Gold" ? "#ffd32a" : "#c0c0c0";
                      return (
                        <div key={i} className="card" style={{ marginBottom: "8px", borderLeft: `3px solid ${TIER_COLORS[aug.rating] || "#555"}` }}>
                          <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "6px" }}>
                            <span style={{ fontWeight: 600, fontSize: "14px" }}>{aug.name}</span>
                            <TierBadge tier={aug.rating} />
                            <span style={{
                              fontSize: "8px", fontWeight: 700, color: tierColor,
                              background: `${tierColor}12`, padding: "2px 6px",
                              borderRadius: "3px", fontFamily: "var(--mono)",
                              letterSpacing: "1px", border: `1px solid ${tierColor}22`,
                            }}>{aug.tier?.toUpperCase()}</span>
                          </div>
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
