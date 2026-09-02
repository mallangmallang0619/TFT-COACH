export function getBoardStrengthPresentation(score, breakdown) {
  const available = breakdown?.source === "detected_board" && Number.isFinite(score);
  const roundedScore = available ? Math.round(score) : null;
  const partialBoard = breakdown?.source === "partial_board";
  const detected = breakdown?.detected_board_slots || 0;
  const expected = breakdown?.expected_board_slots || 0;
  return {
    available,
    score: roundedScore,
    tabLabel: available ? `📈 Strength ${roundedScore ?? 0}` : "📈 Board Strength",
    status: available
      ? (breakdown?.label || "Unknown").toUpperCase()
      : partialBoard && expected > 0
        ? `SCANNING ${detected}/${expected}`
        : "MODEL NEEDED",
  };
}
