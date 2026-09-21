/**
 * Place an expanded note under the quote, centered on the letter card and inset so it
 * does not hang off the sides even when the marker is at an edge.
 * When ``viewport.height`` is set, cap height and lift the box so the bottom stays on screen.
 * @param {{ bottom: number }} anchorRect
 * @param {{ left: number, width: number }} cardRect
 * @param {number} [pad]
 * @param {{ height?: number }} [viewport]
 * @returns {{ top: number, left: number, width: number, maxHeight: number|null }}
 */
export function placeFloatingNote(anchorRect, cardRect, pad = 8, viewport = {}) {
  const cardLeft = Number(cardRect?.left) || 0;
  const cardWidth = Math.max(0, Number(cardRect?.width) || 0);
  const width = Math.max(0, cardWidth - pad * 2);
  const left = cardLeft + (cardWidth - width) / 2;
  const preferredTop = (Number(anchorRect?.bottom) || 0) + 4;
  const viewH = Number(viewport?.height) || 0;
  if (!(viewH > 0)) {
    return { top: preferredTop, left, width, maxHeight: null };
  }
  const minTop = pad;
  const maxBottom = Math.max(minTop, viewH - pad);
  const available = maxBottom - minTop;
  const minH = Math.min(160, available);
  let top = preferredTop;
  let maxHeight;
  const spaceBelow = maxBottom - preferredTop;
  if (spaceBelow >= minH) {
    maxHeight = spaceBelow;
  } else {
    maxHeight = available;
    top = minTop;
  }
  if (top < minTop) top = minTop;
  if (top + maxHeight > maxBottom) {
    maxHeight = Math.max(0, maxBottom - top);
  }
  return { top, left, width, maxHeight };
}
