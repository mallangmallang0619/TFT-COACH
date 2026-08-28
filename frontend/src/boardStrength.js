export function getBoardStrengthPresentation(score, breakdown) {
  const available = breakdown?.source === "detected_board" && Number.isFinite(score);
  const roundedScore = available ? Math.round(score) : null;
  return {
    available,
    score: roundedScore,
    tabLabel: available ? `📈 Strength ${roundedScore ?? 0}` : "📈 Board Strength",
    status: available ? (breakdown?.label || "Unknown").toUpperCase() : "MODEL NEEDED",
  };
}
