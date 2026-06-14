import React, { useMemo } from "react";
import {
  applyAllUpstreamToChunks,
  applyChunkChoice,
  buildMergeChunks,
  mergeChunksToText,
} from "../utils/instructionMerge";

const REVERT_LABEL = "Remove custom instructions and go back to default";

const CHUNK_BG = {
  equal: "transparent",
  custom_only: "rgba(239, 68, 68, 0.08)",
  default_only: "rgba(34, 197, 94, 0.08)",
  changed: "rgba(245, 158, 11, 0.1)",
};

function chunkBorder(chunk) {
  if (chunk.isConflict && chunk.resolvedText === null) return "1px solid #f59e0b";
  if (chunk.isNewUpstream && chunk.resolvedText === null) return "1px solid rgba(99, 102, 241, 0.5)";
  if (chunk.resolvedText !== null) return "1px solid rgba(34, 197, 94, 0.4)";
  return "1px solid var(--border-color)";
}

function ChunkActions({ chunk, onTakeDefault, onKeepCustom, busy }) {
  if (chunk.kind === "equal" || chunk.kind === "custom_only") return null;
  if (chunk.resolvedText !== null) {
    return (
      <span style={{ fontSize: 11, color: "#16a34a", fontWeight: 600 }}>
        Resolved
      </span>
    );
  }

  return (
    <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
      {(chunk.kind === "default_only" || chunk.kind === "changed") && (
        <button
          type="button"
          disabled={busy}
          onClick={onTakeDefault}
          style={{
            padding: "2px 8px",
            fontSize: 11,
            border: "1px solid #6366f1",
            borderRadius: 4,
            background: "rgba(99, 102, 241, 0.15)",
            color: "var(--text-color)",
            cursor: busy ? "not-allowed" : "pointer",
            fontWeight: 600,
          }}
        >
          Take default
        </button>
      )}
      {chunk.kind === "changed" && (
        <button
          type="button"
          disabled={busy}
          onClick={onKeepCustom}
          style={{
            padding: "2px 8px",
            fontSize: 11,
            border: "1px solid var(--border-color)",
            borderRadius: 4,
            background: "var(--button-bg)",
            color: "var(--button-text)",
            cursor: busy ? "not-allowed" : "pointer",
          }}
        >
          Keep mine
        </button>
      )}
    </div>
  );
}

export default function InstructionMergePanel({
  meta,
  draftText,
  onApplyDraft,
  onRevertToDefault,
  busy = false,
}) {
  const [expanded, setExpanded] = React.useState(Boolean(meta?.upstream_updated));

  const baselineText = meta?.baseline ?? "";

  const chunks = useMemo(
    () =>
      buildMergeChunks({
        baseline: baselineText,
        custom: draftText,
        defaultText: meta?.default ?? "",
      }),
    [baselineText, draftText, meta?.default],
  );

  const actionableCount = chunks.filter(
    (c) =>
      c.resolvedText === null
      && (c.kind === "default_only" || c.kind === "changed")
      && c.kind !== "equal",
  ).length;

  if (!meta?.is_custom) return null;

  const applyChunks = (nextChunks) => {
    onApplyDraft(mergeChunksToText(nextChunks));
  };

  const handleApplyUpstream = () => {
    const { chunks: next, unresolved } = applyAllUpstreamToChunks(chunks, baselineText);
    applyChunks(next);
    if (unresolved.length > 0) {
      window.alert(
        `Applied upstream changes. ${unresolved.length} chunk(s) still conflict — pick Take default or Keep mine on each.`,
      );
    }
  };

  const handleTakeDefault = (chunkId) => {
    applyChunks(applyChunkChoice(chunks, chunkId, "default"));
  };

  const handleKeepCustom = (chunkId) => {
    applyChunks(applyChunkChoice(chunks, chunkId, "custom"));
  };

  return (
    <div
      style={{
        marginBottom: 16,
        border: "1px solid var(--border-color)",
        borderRadius: 6,
        background: "var(--panel-bg, var(--header-bg))",
      }}
    >
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        style={{
          width: "100%",
          textAlign: "left",
          padding: "10px 12px",
          border: "none",
          background: "transparent",
          cursor: "pointer",
          color: "var(--text-color)",
          fontWeight: 600,
          fontSize: 13,
        }}
      >
        {expanded ? "▾" : "▸"} Custom instructions — compare with default
        {meta.upstream_updated && (
          <span
            style={{
              marginLeft: 8,
              fontSize: 11,
              fontWeight: 600,
              color: "#6366f1",
              background: "rgba(99, 102, 241, 0.15)",
              padding: "2px 8px",
              borderRadius: 999,
            }}
          >
            Default updated
          </span>
        )}
      </button>

      {expanded && (
        <div style={{ padding: "0 12px 12px" }}>
          {meta.upstream_updated && (
            <div
              style={{
                marginBottom: 10,
                padding: "8px 10px",
                borderRadius: 4,
                background: "rgba(99, 102, 241, 0.1)",
                border: "1px solid rgba(99, 102, 241, 0.35)",
                color: "var(--text-color)",
                fontSize: 13,
              }}
            >
              The repo default changed since you saved your custom version. Use Take default on each chunk, or Apply all upstream changes.
            </div>
          )}

          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
            <button
              type="button"
              disabled={busy || actionableCount === 0}
              onClick={handleApplyUpstream}
              style={{
                padding: "6px 12px",
                border: "1px solid #6366f1",
                borderRadius: 4,
                background: "rgba(99, 102, 241, 0.12)",
                color: "var(--text-color)",
                cursor: busy || actionableCount === 0 ? "not-allowed" : "pointer",
                fontSize: 13,
                fontWeight: 600,
                opacity: busy || actionableCount === 0 ? 0.55 : 1,
              }}
            >
              Apply all upstream changes
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={onRevertToDefault}
              title="Permanently deletes your saved custom instructions"
              style={{
                padding: "6px 12px",
                border: "1px solid #dc2626",
                borderRadius: 4,
                background: "#dc2626",
                color: "#fff",
                cursor: busy ? "not-allowed" : "pointer",
                fontSize: 13,
                fontWeight: 600,
                opacity: busy ? 0.65 : 1,
              }}
            >
              {REVERT_LABEL}
            </button>
          </div>

          <div style={{ fontSize: 12, color: "var(--secondary-text-color)", marginBottom: 8 }}>
            Red tint = only in yours · green = only in default · purple border = new upstream · amber border = conflict
          </div>

          <div
            style={{
              border: "1px solid var(--border-color)",
              borderRadius: 4,
              maxHeight: 320,
              overflow: "auto",
              background: "var(--input-bg)",
            }}
          >
            {chunks.map((chunk) => {
              if (chunk.kind === "equal") {
                return (
                  <pre
                    key={chunk.id}
                    style={{
                      margin: 0,
                      padding: "4px 8px",
                      fontFamily: "monospace",
                      fontSize: 12,
                      whiteSpace: "pre-wrap",
                      borderBottom: "1px solid var(--border-color)",
                    }}
                  >
                    {chunk.customText}
                  </pre>
                );
              }

              const label =
                chunk.kind === "custom_only"
                  ? "Only in yours"
                  : chunk.kind === "default_only"
                    ? chunk.isNewUpstream
                      ? "New in default"
                      : "Only in default"
                    : chunk.isConflict
                      ? "Conflict"
                      : "Changed";

              return (
                <div
                  key={chunk.id}
                  style={{
                    padding: "8px",
                    borderBottom: "1px solid var(--border-color)",
                    background: CHUNK_BG[chunk.kind] || "transparent",
                    border: chunkBorder(chunk),
                    margin: "4px",
                    borderRadius: 4,
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      gap: 8,
                      marginBottom: 6,
                      flexWrap: "wrap",
                    }}
                  >
                    <span
                      style={{
                        fontSize: 11,
                        fontWeight: 700,
                        color: chunk.isNewUpstream ? "#6366f1" : chunk.isConflict ? "#d97706" : "var(--secondary-text-color)",
                      }}
                    >
                      {label}
                    </span>
                    <ChunkActions
                      chunk={chunk}
                      busy={busy}
                      onTakeDefault={() => handleTakeDefault(chunk.id)}
                      onKeepCustom={() => handleKeepCustom(chunk.id)}
                    />
                  </div>
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "1fr 1fr",
                      gap: 8,
                      fontFamily: "monospace",
                      fontSize: 12,
                    }}
                  >
                    <div>
                      <div style={{ fontSize: 10, color: "var(--secondary-text-color)", marginBottom: 2 }}>
                        Yours
                      </div>
                      <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>
                        {chunk.customText || "—"}
                      </pre>
                    </div>
                    <div
                      style={{
                        background: chunk.isNewUpstream ? "rgba(99, 102, 241, 0.12)" : undefined,
                        padding: chunk.isNewUpstream ? 4 : 0,
                        borderRadius: 4,
                      }}
                    >
                      <div style={{ fontSize: 10, color: "var(--secondary-text-color)", marginBottom: 2 }}>
                        Default
                      </div>
                      <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>
                        {chunk.defaultText || "—"}
                      </pre>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          <details style={{ marginTop: 10, fontSize: 13 }}>
            <summary style={{ cursor: "pointer", color: "var(--secondary-text-color)" }}>
              Full default text
            </summary>
            <pre
              style={{
                marginTop: 8,
                padding: 10,
                background: "var(--input-bg)",
                border: "1px solid var(--border-color)",
                borderRadius: 4,
                whiteSpace: "pre-wrap",
                fontSize: 12,
                fontFamily: "monospace",
              }}
            >
              {meta.default}
            </pre>
          </details>
        </div>
      )}
    </div>
  );
}
