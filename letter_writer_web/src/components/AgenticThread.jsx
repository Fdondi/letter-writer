/**
 * Renders one topic's feedback thread: comments with subcomments, addendums, and vote counts.
 * When canEdit, shows Edit and Remove so user can adjust feedback before Refine.
 */
import React, { useState } from "react";

const topicLabels = {
  instruction: "Instruction",
  accuracy: "Accuracy",
  precision: "Precision",
  company_fit: "Company fit",
  user_fit: "User fit",
  human: "Human",
};

function topicStatusLabel(meta) {
  if (!meta) return null;
  if (meta.done) return "Done";
  if (meta.suspended) return "Suspended";
  return "Active";
}

function topicStatusColor(meta) {
  if (!meta) return "var(--secondary-text-color)";
  if (meta.done) return "#16a34a";
  if (meta.suspended) return "#d97706";
  return "#0d9488";
}

export default function AgenticThread({
  topic,
  thread = [],
  topicMeta,
  description,
  canEdit = false,
  canSuspend = false,
  canResume = false,
  onSuspend,
  onResume,
  onRemoveComment,
  onEditComment,
}) {
  const label = topicLabels[topic] || topic;
  const meta = topicMeta || {};
  const statusLabel = topicStatusLabel(meta);
  const messages = meta.messages ?? (thread?.length ?? 0);
  const turns = meta.round ?? 0;

  return (
    <div
      style={{
        padding: 12,
        backgroundColor: "var(--panel-bg)",
        border: "1px solid var(--border-color)",
        borderRadius: 8,
        minHeight: 120,
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          gap: 8,
          marginBottom: 6,
          flexWrap: "wrap",
        }}
      >
        <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-color)" }}>{label}</div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          {statusLabel != null && (
            <span
              style={{
                fontSize: 11,
                fontWeight: 600,
                color: topicStatusColor(meta),
                textTransform: "uppercase",
              }}
            >
              {statusLabel}
            </span>
          )}
          <span style={{ fontSize: 11, color: "var(--secondary-text-color)" }}>
            {messages} msg{messages !== 1 ? "s" : ""} · {turns} turn{turns !== 1 ? "s" : ""}
          </span>
          {canSuspend && onSuspend && (
            <button
              type="button"
              onClick={onSuspend}
              style={{
                fontSize: 11,
                padding: "2px 8px",
                cursor: "pointer",
                border: "1px solid var(--border-color)",
                borderRadius: 4,
                background: "var(--bg-color)",
                color: "var(--text-color)",
              }}
            >
              Suspend
            </button>
          )}
          {canResume && onResume && (
            <button
              type="button"
              onClick={onResume}
              style={{
                fontSize: 11,
                padding: "2px 8px",
                cursor: "pointer",
                border: "none",
                borderRadius: 4,
                background: "#0d9488",
                color: "white",
              }}
            >
              Resume
            </button>
          )}
        </div>
      </div>
      {description && (
        <div
          style={{
            fontSize: 11,
            color: "var(--secondary-text-color)",
            marginBottom: 8,
          }}
        >
          {description}
        </div>
      )}
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {!thread || thread.length === 0 ? (
          <div
            style={{
              fontSize: 12,
              color: "var(--secondary-text-color)",
              fontStyle: "italic",
            }}
          >
            No comments yet.
          </div>
        ) : (
          thread.map((comment, idx) => (
            <CommentBlock
              key={comment.id || comment.text?.slice(0, 20) || idx}
              comment={comment}
              commentIndex={idx}
              topic={topic}
              canEdit={canEdit}
              onRemove={() => onRemoveComment?.(topic, idx)}
              onEdit={(newText) => onEditComment?.(topic, idx, newText)}
            />
          ))
        )}
      </div>
    </div>
  );
}

function CommentBlock({ comment, commentIndex, topic, canEdit, onRemove, onEdit }) {
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState(comment.text || "");
  const up = (comment.votes && comment.votes.up) || [];
  const down = (comment.votes && comment.votes.down) || [];
  const net = up.length - down.length;

  const handleSaveEdit = () => {
    if (editText.trim() !== (comment.text || "").trim()) onEdit?.(editText.trim() || comment.text);
    setEditing(false);
  };

  return (
    <div
      style={{
        padding: 8,
        backgroundColor: "var(--bg-color)",
        border: "1px solid var(--border-color)",
        borderRadius: 6,
      }}
    >
      <div
        style={{
          fontSize: 11,
          color: "var(--secondary-text-color)",
          marginBottom: 4,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <span>{comment.vendor}</span>
        {canEdit && (
          <span style={{ display: "flex", gap: 6 }}>
            <button
              type="button"
              onClick={() => (editing ? handleSaveEdit() : setEditing(true))}
              style={{
                fontSize: 11,
                padding: "2px 8px",
                cursor: "pointer",
                border: "1px solid var(--border-color)",
                borderRadius: 4,
                background: "var(--panel-bg)",
                color: "var(--text-color)",
              }}
            >
              {editing ? "Save" : "Edit"}
            </button>
            <button
              type="button"
              onClick={() => onRemove?.()}
              style={{
                fontSize: 11,
                padding: "2px 8px",
                cursor: "pointer",
                border: "1px solid var(--border-color)",
                borderRadius: 4,
                background: "#fef2f2",
                color: "#b91c1c",
              }}
            >
              Remove
            </button>
          </span>
        )}
      </div>
      {editing ? (
        <textarea
          value={editText}
          onChange={(e) => setEditText(e.target.value)}
          onBlur={handleSaveEdit}
          style={{
            width: "100%",
            minHeight: 80,
            fontSize: 13,
            padding: 6,
            border: "1px solid var(--border-color)",
            borderRadius: 4,
            resize: "vertical",
            fontFamily: "inherit",
          }}
        />
      ) : (
        <div
          style={{
            fontSize: 13,
            color: "var(--text-color)",
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
          }}
        >
          {comment.text}
        </div>
      )}
      {(comment.addendums || []).length > 0 && (
        <div style={{ marginTop: 6, paddingLeft: 8, borderLeft: "2px solid var(--border-color)" }}>
          {(comment.addendums || []).map((a, i) => {
            const addendumUp = (a.up && Array.isArray(a.up)) ? a.up.length : 0;
            return (
              <div
                key={a.id || i}
                style={{
                  fontSize: 12,
                  color: "var(--secondary-text-color)",
                  marginBottom: 6,
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "flex-start",
                  gap: 8,
                }}
              >
                <span>
                  <span style={{ fontWeight: 600 }}>Addendum ({a.vendor}):</span> {a.text}
                </span>
                <span
                  style={{
                    fontSize: 11,
                    color: addendumUp > 0 ? "#16a34a" : "var(--secondary-text-color)",
                    flexShrink: 0,
                    fontWeight: 600,
                  }}
                  title="Addendum upvotes (only positively upvoted addendums are used in the revision)"
                >
                  ↑ {addendumUp}
                </span>
              </div>
            );
          })}
        </div>
      )}
      {(comment.subcomments || []).length > 0 && (
        <div style={{ marginTop: 6, paddingLeft: 8, borderLeft: "2px solid var(--border-color)" }}>
          {(comment.subcomments || []).map((s) => (
            <div key={s.id || s.text?.slice(0, 12)} style={{ fontSize: 12, marginBottom: 4 }}>
              <span style={{ color: "var(--secondary-text-color)" }}>{s.vendor}:</span> {s.text}
            </div>
          ))}
        </div>
      )}
      <div
        style={{
          marginTop: 6,
          fontSize: 11,
          display: "flex",
          gap: 8,
          alignItems: "center",
        }}
      >
        <span style={{ color: net > 0 ? "#16a34a" : "var(--secondary-text-color)" }}>
          ↑ {up.length}
        </span>
        <span style={{ color: down.length > 0 ? "#dc2626" : "var(--secondary-text-color)" }}>
          ↓ {down.length}
        </span>
      </div>
    </div>
  );
}
