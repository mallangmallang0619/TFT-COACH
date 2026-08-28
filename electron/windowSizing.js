const FULL_OVERLAY_WIDTH = 420;
const COMPACT_OVERLAY_WIDTH = 320;
const COMPACT_OVERLAY_HEIGHT = 58;
const COMPACT_INSET = 12;

function positiveNumber(value, fallback) {
  return Number.isFinite(value) && value > 0 ? value : fallback;
}

function getOverlayBounds(workArea, compact) {
  const area = {
    x: Number.isFinite(workArea?.x) ? workArea.x : 0,
    y: Number.isFinite(workArea?.y) ? workArea.y : 0,
    width: positiveNumber(workArea?.width, FULL_OVERLAY_WIDTH),
    height: positiveNumber(workArea?.height, COMPACT_OVERLAY_HEIGHT),
  };

  const requestedWidth = compact ? COMPACT_OVERLAY_WIDTH : FULL_OVERLAY_WIDTH;
  const requestedHeight = compact ? COMPACT_OVERLAY_HEIGHT : area.height;
  const width = Math.min(requestedWidth, area.width);
  const height = Math.min(requestedHeight, area.height);
  const horizontalInset = compact && area.width >= width + COMPACT_INSET * 2
    ? COMPACT_INSET
    : 0;
  const verticalInset = compact && area.height >= height + COMPACT_INSET * 2
    ? COMPACT_INSET
    : 0;

  return {
    x: area.x + area.width - width - horizontalInset,
    y: area.y + verticalInset,
    width,
    height,
  };
}

module.exports = {
  COMPACT_OVERLAY_HEIGHT,
  COMPACT_OVERLAY_WIDTH,
  FULL_OVERLAY_WIDTH,
  getOverlayBounds,
};
