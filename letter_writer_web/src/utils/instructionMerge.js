import { diffArrays, diffLines } from "diff";

/** @typedef {'equal' | 'custom_only' | 'default_only' | 'changed'} MergeChunkKind */

/**
 * @typedef {Object} MergeChunk
 * @property {number} id
 * @property {MergeChunkKind} kind
 * @property {string} customText
 * @property {string} defaultText
 * @property {string | null} resolvedText
 * @property {boolean} isNewUpstream
 * @property {boolean} isConflict
 */

export function splitInstructionLines(text) {
  const normalized = String(text ?? "").replace(/\r\n/g, "\n");
  if (!normalized) return [];
  const lines = normalized.split("\n");
  if (lines.length && lines[lines.length - 1] === "") lines.pop();
  return lines;
}

export function joinInstructionLines(lines) {
  return (lines || []).join("\n");
}

function normalize(text) {
  return String(text ?? "").replace(/\r\n/g, "\n");
}

function trimChunk(text) {
  return String(text ?? "").replace(/\s+$/, "");
}

/** Segments introduced or altered in default since baseline. */
function upstreamDefaultSegments(baseline, defaultText) {
  const segments = new Set();
  if (!baseline.trim()) return segments;
  const parts = diffLines(normalize(baseline), normalize(defaultText));
  for (const part of parts) {
    if (part.added) segments.add(trimChunk(part.value));
  }
  return segments;
}

function segmentTouchesUpstream(segment, upstreamSegments) {
  const trimmed = trimChunk(segment);
  if (!trimmed) return false;
  if (upstreamSegments.has(trimmed)) return true;
  for (const seg of upstreamSegments) {
    if (seg.includes(trimmed) || trimmed.includes(seg)) return true;
  }
  return false;
}

/**
 * Diff hunks between custom and default (line-aligned), annotated for upstream merge.
 * @returns {MergeChunk[]}
 */
export function buildMergeChunks({ baseline, custom, defaultText }) {
  const customLines = splitInstructionLines(custom);
  const defaultLines = splitInstructionLines(defaultText);
  const baselineLines = splitInstructionLines(baseline);
  const upstreamSegments = upstreamDefaultSegments(baseline, defaultText);

  const parts = diffArrays(customLines, defaultLines);
  /** @type {MergeChunk[]} */
  const chunks = [];
  let id = 0;

  const pushEqual = (line) => {
    chunks.push({
      id: id++,
      kind: "equal",
      customText: `${line}\n`,
      defaultText: `${line}\n`,
      resolvedText: null,
      isNewUpstream: false,
      isConflict: false,
    });
  };

  const pushCustomOnly = (lines) => {
    const text = lines.map((l) => `${l}\n`).join("");
    chunks.push({
      id: id++,
      kind: "custom_only",
      customText: text,
      defaultText: "",
      resolvedText: null,
      isNewUpstream: false,
      isConflict: false,
    });
  };

  const pushDefaultOnly = (lines) => {
    const text = lines.map((l) => `${l}\n`).join("");
    const isNewUpstream =
      !baseline.trim()
      || lines.some((line) => upstreamSegments.has(line) || lineIsNewUpstream(line, baselineLines, defaultLines));
    chunks.push({
      id: id++,
      kind: "default_only",
      customText: "",
      defaultText: text,
      resolvedText: null,
      isNewUpstream,
      isConflict: false,
    });
  };

  const pushChangedPair = (customLine, defaultLine) => {
    const customText = `${customLine}\n`;
    const defaultTextLine = `${defaultLine}\n`;
    const baseLine = findBaselineLine(customLine, defaultLine, baselineLines);
    const conflict = isLineConflict(baseLine, customLine, defaultLine);
    chunks.push({
      id: id++,
      kind: "changed",
      customText,
      defaultText: defaultTextLine,
      resolvedText: null,
      isNewUpstream: isLineUpstream(baseLine, customLine, defaultLine, baselineLines),
      isConflict: conflict,
    });
  };

  for (let i = 0; i < parts.length; i += 1) {
    const part = parts[i];
    const lines = part.value;

    if (!part.removed && !part.added) {
      lines.forEach(pushEqual);
      continue;
    }

    if (part.removed && parts[i + 1]?.added) {
      const removed = parts[i].value;
      const added = parts[i + 1].value;
      i += 1;
      const paired = Math.min(removed.length, added.length);
      for (let p = 0; p < paired; p += 1) {
        if (removed[p] === added[p]) pushEqual(removed[p]);
        else pushChangedPair(removed[p], added[p]);
      }
      if (removed.length > paired) pushCustomOnly(removed.slice(paired));
      if (added.length > paired) pushDefaultOnly(added.slice(paired));
      continue;
    }

    if (part.removed) {
      pushCustomOnly(lines);
      continue;
    }

    if (part.added) {
      pushDefaultOnly(lines);
    }
  }

  return chunks;
}

function lineIsNewUpstream(line, baselineLines, defaultLines) {
  return !baselineLines.includes(line) && defaultLines.includes(line);
}

function findBaselineLine(customLine, defaultLine, baselineLines) {
  const ci = baselineLines.indexOf(customLine);
  if (ci >= 0) return customLine;
  const di = baselineLines.indexOf(defaultLine);
  if (di >= 0) return defaultLine;
  return "";
}

function isLineConflict(baseLine, customLine, defaultLine) {
  if (customLine === defaultLine) return false;
  if (!baseLine) return true;
  if (customLine === baseLine) return false;
  if (defaultLine === baseLine) return false;
  return true;
}

function isLineUpstream(baseLine, customLine, defaultLine, baselineLines) {
  if (!baselineLines.length) return customLine !== defaultLine;
  if (baseLine && defaultLine !== baseLine) return true;
  return !baselineLines.includes(defaultLine) && customLine !== defaultLine;
}

/** Text for one chunk (resolved choice, or fall back to custom side). */
export function chunkEffectiveText(chunk) {
  if (chunk.resolvedText !== null) return chunk.resolvedText;
  if (chunk.kind === "default_only") return chunk.customText;
  if (chunk.kind === "changed") return chunk.customText;
  return chunk.customText;
}

/** Reassemble document from chunks. */
export function mergeChunksToText(chunks) {
  const text = chunks.map(chunkEffectiveText).join("");
  return text.replace(/\n$/, "");
}

/** Pick default or custom side for one chunk. */
export function applyChunkChoice(chunks, chunkId, choice) {
  return chunks.map((chunk) => {
    if (chunk.id !== chunkId) return chunk;
    const resolvedText = choice === "default" ? chunk.defaultText : chunk.customText;
    return { ...chunk, resolvedText, isConflict: false };
  });
}

function autoResolveChanged(baseline, chunk) {
  const customLine = trimChunk(chunk.customText);
  const defaultLine = trimChunk(chunk.defaultText);
  const baselineLines = splitInstructionLines(baseline);
  const baseLine = findBaselineLine(customLine, defaultLine, baselineLines);
  if (!baseline.trim()) return null;
  if (baseLine && customLine === baseLine) return chunk.defaultText;
  if (baseLine && defaultLine === baseLine) return chunk.customText;
  if (baselineLines.includes(customLine)) return chunk.defaultText;
  if (baselineLines.includes(defaultLine)) return chunk.customText;
  return null;
}

/**
 * Apply all non-conflicting upstream changes.
 * @returns {{ chunks: MergeChunk[], unresolved: MergeChunk[] }}
 */
export function applyAllUpstreamToChunks(chunks, baseline) {
  const next = chunks.map((chunk) => {
    if (chunk.resolvedText !== null) return chunk;

    if (chunk.kind === "default_only") {
      return { ...chunk, resolvedText: chunk.defaultText };
    }

    if (chunk.kind === "changed") {
      if (chunk.isConflict) {
        const auto = autoResolveChanged(baseline, chunk);
        if (auto !== null) {
          return { ...chunk, resolvedText: auto, isConflict: false };
        }
        return chunk;
      }
      const customLine = trimChunk(chunk.customText);
      const defaultLine = trimChunk(chunk.defaultText);
      const baselineLines = splitInstructionLines(baseline);
      if (baselineLines.includes(customLine)) {
        return { ...chunk, resolvedText: chunk.defaultText };
      }
      if (baselineLines.includes(defaultLine)) {
        return { ...chunk, resolvedText: chunk.customText };
      }
      return { ...chunk, resolvedText: chunk.defaultText };
    }

    return chunk;
  });

  const unresolved = next.filter(
    (c) => c.kind === "changed" && c.isConflict && c.resolvedText === null,
  );
  return { chunks: next, unresolved };
}

/** @deprecated use buildMergeChunks — kept for tests migrating off row view */
export function buildInstructionDiffView({ baseline, custom, defaultText }) {
  return buildMergeChunks({ baseline, custom, defaultText }).flatMap((chunk) => {
    if (chunk.kind === "equal") {
      return trimChunk(chunk.customText).split("\n").map((text) => ({
        kind: "equal",
        text,
        customLineNo: null,
        defaultLineNo: null,
      }));
    }
    if (chunk.kind === "custom_only") {
      return trimChunk(chunk.customText).split("\n").map((text) => ({
        kind: "removed",
        text,
      }));
    }
    if (chunk.kind === "default_only") {
      return trimChunk(chunk.defaultText).split("\n").map((text) => ({
        kind: chunk.isNewUpstream ? "new_upstream" : "added",
        text,
      }));
    }
    const customLines = trimChunk(chunk.customText).split("\n");
    const defaultLines = trimChunk(chunk.defaultText).split("\n");
    const rows = [];
    const n = Math.max(customLines.length, defaultLines.length);
    for (let i = 0; i < n; i += 1) {
      const cl = customLines[i];
      const dl = defaultLines[i];
      if (cl === dl) {
        rows.push({ kind: "equal", text: cl });
      } else if (cl !== undefined && dl === undefined) {
        rows.push({ kind: "removed", text: cl });
      } else if (cl === undefined && dl !== undefined) {
        rows.push({
          kind: chunk.isNewUpstream ? "new_upstream" : "added",
          text: dl,
        });
      } else {
        rows.push({ kind: "removed", text: cl });
        rows.push({
          kind: chunk.isNewUpstream ? "new_upstream" : "added",
          text: dl,
        });
      }
    }
    return rows;
  });
}

/** @deprecated */
export function applyUpstreamChanges(baseline, custom, defaultText) {
  const chunks = buildMergeChunks({ baseline, custom, defaultText });
  const { chunks: merged, unresolved } = applyAllUpstreamToChunks(chunks, baseline);
  return {
    text: mergeChunksToText(merged),
    conflicts: unresolved.map((c, index) => ({
      index,
      base: "",
      ours: trimChunk(c.customText),
      theirs: trimChunk(c.defaultText),
      chunkId: c.id,
    })),
  };
}

/** @deprecated */
export function resolveConflict(text, conflict, choice) {
  void text;
  void conflict;
  void choice;
  return text;
}

export function hasUpstreamUpdate(meta) {
  return Boolean(meta?.is_custom && meta?.upstream_updated);
}

export function chunksNeedingAction(chunks) {
  return chunks.filter(
    (c) =>
      c.resolvedText === null
      && (c.kind === "default_only" || c.kind === "changed")
      && (c.isNewUpstream || c.isConflict || c.kind === "default_only"),
  );
}
