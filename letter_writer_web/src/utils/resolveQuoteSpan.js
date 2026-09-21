/**
 * Re-find a stored quote in the current letter (exact, then whitespace/case fold).
 * Does not call embeddings; a miss means the note becomes unanchored.
 */

function normalizeWithMap(text) {
  const out = [];
  const idxMap = [];
  let prevSpace = true;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (/\s/.test(ch)) {
      if (!prevSpace) {
        out.push(" ");
        idxMap.push(i);
        prevSpace = true;
      }
      continue;
    }
    out.push(ch.toLocaleLowerCase());
    idxMap.push(i);
    prevSpace = false;
  }
  if (out.length && out[out.length - 1] === " ") {
    out.pop();
    idxMap.pop();
  }
  return { norm: out.join(""), idxMap };
}

export function findExactSpan(letter, quote) {
  if (!quote) return null;
  const idx = letter.indexOf(quote);
  if (idx < 0) return null;
  return { start: idx, end: idx + quote.length };
}

export function findNormalizedSpan(letter, quote) {
  if (!quote || !letter) return null;
  const letterN = normalizeWithMap(letter);
  const quoteN = normalizeWithMap(quote);
  if (!quoteN.norm || !letterN.norm) return null;
  const idx = letterN.norm.indexOf(quoteN.norm);
  if (idx < 0) return null;
  const endNorm = idx + quoteN.norm.length - 1;
  const start = letterN.idxMap[idx];
  const end = letterN.idxMap[endNorm] + 1;
  return { start, end };
}

/**
 * @param {string} letter
 * @param {string} [quote]
 * @param {string} [matchedText]
 * @returns {{ start: number, end: number } | null}
 */
export function resolveQuoteSpan(letter, quote, matchedText) {
  const hay = letter || "";
  const needles = [matchedText, quote];
  for (const raw of needles) {
    const needle = String(raw ?? "").trim();
    if (!needle) continue;
    const exact = findExactSpan(hay, needle);
    if (exact) return exact;
    const normalized = findNormalizedSpan(hay, needle);
    if (normalized) return normalized;
  }
  return null;
}

/**
 * Split text into segments covered by zero or more ranges.
 * @param {string} text
 * @param {{ id: string, start: number, end: number }[]} ranges
 */
export function splitHighlightedSegments(text, ranges) {
  const source = text || "";
  const points = new Set([0, source.length]);
  for (const r of ranges || []) {
    const start = Math.max(0, Math.min(source.length, r.start));
    const end = Math.max(0, Math.min(source.length, r.end));
    if (end > start) {
      points.add(start);
      points.add(end);
    }
  }
  const sorted = [...points].sort((a, b) => a - b);
  const segments = [];
  for (let i = 0; i < sorted.length - 1; i++) {
    const start = sorted[i];
    const end = sorted[i + 1];
    if (end <= start) continue;
    const covering = (ranges || []).filter((r) => r.start <= start && r.end >= end);
    segments.push({
      start,
      end,
      text: source.slice(start, end),
      noteIds: covering.map((r) => r.id),
    });
  }
  return segments;
}
