import React, { useCallback, useEffect, useMemo, useState } from "react";
import { fetchWithHeartbeat } from "../utils/apiHelpers";

/**
 * Jobs from the opportunity pipeline (OPPORTUNITY_PIPELINE_PLAN.md §4.8): triage alert proposals,
 * attach posting text, and craft the final letter from the drafts the desktop batch wrote.
 */
export const TABS = [
  { key: "proposed", label: "Proposed", statuses: ["proposed"] },
  { key: "waiting", label: "Needs text", statuses: ["approved"] },
  { key: "drafting", label: "Drafting", statuses: ["captured", "drafting", "failed"] },
  { key: "ready", label: "Ready", statuses: ["ready"] },
  { key: "applied", label: "Applied", statuses: ["done", "applied"] },
  { key: "skipped", label: "Skipped", statuses: ["skipped"] },
];

const STAGE_LABELS = {
  applied: "applied",
  received: "received",
  viewed: "viewed",
  forwarded: "sent to the client",
  screening: "screening",
  interview: "interview",
  final: "final round",
  offer: "offer",
};

/** Chips for how far an application got (job fit) and any praise (letter quality). */
export function outcomeChips(outcome) {
  if (!outcome || typeof outcome !== "object") return [];
  const chips = [];
  const stage = STAGE_LABELS[outcome.stage] || outcome.stage;
  if (stage) {
    const rounds = Number(outcome.interviews || 0);
    chips.push({ text: rounds > 1 ? `${stage} ×${rounds}` : stage, tone: "neutral" });
  }
  if (outcome.result === "rejected") chips.push({ text: "rejected", tone: "bad" });
  if (outcome.result === "offer") chips.push({ text: "offer", tone: "good" });
  if (outcome.result === "withdrawn") chips.push({ text: "withdrawn", tone: "neutral" });
  if (outcome.positive_feedback) {
    chips.push({ text: "praised", tone: "good", title: (outcome.feedback_quotes || []).join("\n") });
  }
  return chips;
}

export const SKIP_REASONS = ["Not my field", "Too junior", "Too senior", "Location", "Language", "Not interested"];

const STATUS_LABELS = {
  proposed: "proposed",
  approved: "waiting for posting text",
  captured: "queued for the next desktop run",
  drafting: "drafting on the desktop",
  failed: "failed",
  ready: "ready",
  done: "letter saved",
  applied: "applied",
  skipped: "skipped",
};

const VENDOR_LABELS = { claude_code: "Claude Code" };

export function tabForStatus(status) {
  return (TABS.find((t) => t.statuses.includes(status)) || TABS[0]).key;
}

function vendorLabel(v) {
  return VENDOR_LABELS[v] || v;
}

const buttonStyle = (primary = false, disabled = false) => ({
  padding: "6px 12px",
  border: primary ? "none" : "1px solid var(--border-color)",
  borderRadius: 4,
  backgroundColor: primary ? "#3b82f6" : "var(--button-bg)",
  color: primary ? "white" : "var(--button-text)",
  cursor: disabled ? "not-allowed" : "pointer",
  opacity: disabled ? 0.6 : 1,
  fontSize: 14,
});

function Chip({ children, tone = "neutral" }) {
  const colors = {
    neutral: "var(--border-color)",
    good: "#16a34a",
    warn: "#d97706",
    bad: "#dc2626",
  };
  return (
    <span
      style={{
        display: "inline-block",
        padding: "1px 8px",
        marginRight: 6,
        marginBottom: 4,
        borderRadius: 10,
        border: `1px solid ${colors[tone]}`,
        fontSize: 12,
        whiteSpace: "nowrap",
      }}
    >
      {children}
    </span>
  );
}

function OpportunityCard({ opp, highlighted, busy, onAction }) {
  const [skipOpen, setSkipOpen] = useState(false);
  const [pasteOpen, setPasteOpen] = useState(false);
  const [pasteText, setPasteText] = useState("");
  const status = opp.status;
  const fit = opp.fit_summary || {};
  const failed = opp.vendors_failed || {};
  const meta = [opp.company, opp.location, opp.source].filter(Boolean).join(" · ");
  const title = opp.title || opp.url || "Untitled job";

  return (
    <div
      data-testid={`opportunity-${opp.id}`}
      style={{
        padding: 14,
        marginBottom: 10,
        border: `1px solid ${highlighted ? "#3b82f6" : "var(--border-color)"}`,
        borderRadius: 8,
        backgroundColor: "var(--card-bg)",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <div style={{ minWidth: 0, flex: "1 1 260px" }}>
          <div style={{ fontWeight: 600, overflowWrap: "anywhere" }}>
            {opp.url ? (
              <a href={opp.url} target="_blank" rel="noopener noreferrer" style={{ color: "var(--text-color)" }}>
                {title}
              </a>
            ) : (
              title
            )}
          </div>
          {meta && <div style={{ fontSize: 13, opacity: 0.8 }}>{meta}</div>}
          <div style={{ fontSize: 12, opacity: 0.7, marginTop: 2 }}>{STATUS_LABELS[status] || status}</div>
        </div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "flex-start" }}>
          {(status === "proposed" || status === "skipped") && (
            <button type="button" disabled={busy} style={buttonStyle(true, busy)} onClick={() => onAction("approve", opp)}>
              Approve
            </button>
          )}
          {status === "skipped" && (
            <button type="button" disabled={busy} style={buttonStyle(false, busy)} onClick={() => onAction("unskip", opp)}>
              Back to proposed
            </button>
          )}
          {["proposed", "approved", "captured", "failed", "ready"].includes(status) && (
            <button type="button" disabled={busy} style={buttonStyle(false, busy)} onClick={() => setSkipOpen((v) => !v)}>
              Skip
            </button>
          )}
          {["proposed", "approved", "failed"].includes(status) && (
            <button type="button" disabled={busy} style={buttonStyle(false, busy)} onClick={() => setPasteOpen((v) => !v)}>
              Paste text
            </button>
          )}
          {(status === "failed" || status === "ready") && (
            <button type="button" disabled={busy} style={buttonStyle(false, busy)} onClick={() => onAction("retry", opp)}>
              {status === "failed" ? "Retry" : "Draft again"}
            </button>
          )}
          {status === "ready" && (
            <button type="button" disabled={busy} style={buttonStyle(true, busy)} onClick={() => onAction("open", opp)}>
              Craft letter
            </button>
          )}
        </div>
      </div>

      {(fit.matched?.length > 0 || fit.gaps?.length > 0) && (
        <div style={{ marginTop: 8 }}>
          {(fit.matched || []).map((s) => (
            <Chip key={`m-${s}`} tone="good">
              {s}
            </Chip>
          ))}
          {(fit.gaps || []).map((s) => (
            <Chip key={`g-${s}`} tone="warn">
              gap: {s}
            </Chip>
          ))}
        </div>
      )}
      {(opp.vendors_done?.length > 0 || Object.keys(failed).length > 0 || opp.input_needed_count > 0) && (
        <div style={{ marginTop: 6, fontSize: 13 }}>
          {(opp.vendors_done || []).map((v) => (
            <Chip key={`d-${v}`} tone="good">
              {vendorLabel(v)}
            </Chip>
          ))}
          {Object.entries(failed).map(([v, err]) => (
            <span key={`f-${v}`} title={String(err)}>
              <Chip tone="bad">{vendorLabel(v)} failed</Chip>
            </span>
          ))}
          {opp.input_needed_count > 0 && <Chip tone="warn">{opp.input_needed_count} questions for you</Chip>}
        </div>
      )}
      {status === "skipped" && opp.skip_reason && <div style={{ fontSize: 12, opacity: 0.7, marginTop: 4 }}>Skipped: {opp.skip_reason}</div>}
      {opp.history_note && status === "proposed" && <div style={{ fontSize: 12, opacity: 0.8, marginTop: 4 }}>{opp.history_note}</div>}
      {outcomeChips(opp.outcome).length > 0 && (
        <div style={{ marginTop: 6, fontSize: 13 }}>
          {outcomeChips(opp.outcome).map((c) => (
            <span key={c.text} title={c.title || undefined}>
              <Chip tone={c.tone}>{c.text}</Chip>
            </span>
          ))}
          {opp.document_id && <Chip>letter from this app</Chip>}
        </div>
      )}

      {skipOpen && (
        <div style={{ marginTop: 8, display: "flex", gap: 6, flexWrap: "wrap" }}>
          {SKIP_REASONS.map((reason) => (
            <button
              key={reason}
              type="button"
              disabled={busy}
              style={buttonStyle(false, busy)}
              onClick={() => {
                setSkipOpen(false);
                onAction("skip", opp, { reason });
              }}
            >
              {reason}
            </button>
          ))}
        </div>
      )}
      {pasteOpen && (
        <div style={{ marginTop: 8 }}>
          <textarea
            aria-label="Posting text"
            value={pasteText}
            onChange={(e) => setPasteText(e.target.value)}
            rows={6}
            placeholder="Paste the full job posting"
            style={{ width: "100%", boxSizing: "border-box", fontSize: 14 }}
          />
          <button
            type="button"
            disabled={busy || !pasteText.trim()}
            style={buttonStyle(true, busy || !pasteText.trim())}
            onClick={() => {
              onAction("capture", opp, { text: pasteText });
              setPasteOpen(false);
              setPasteText("");
            }}
          >
            Send to the desktop
          </button>
        </div>
      )}
    </div>
  );
}

export default function OpportunitiesPage({ onOpened = null, highlightId = null }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [tab, setTab] = useState(null);
  const [manualUrl, setManualUrl] = useState("");
  const [manualText, setManualText] = useState("");

  const load = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await fetch("/api/opportunities/", { credentials: "include" });
      if (!res.ok) {
        const detail = await res.text();
        throw new Error(detail || `Failed to list jobs (${res.status})`);
      }
      const data = await res.json();
      setItems(Array.isArray(data.opportunities) ? data.opportunities : []);
    } catch (e) {
      setError(e?.message || "Failed to list jobs");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const counts = useMemo(() => {
    const out = {};
    for (const t of TABS) out[t.key] = items.filter((o) => t.statuses.includes(o.status)).length;
    return out;
  }, [items]);

  // Start on the highlighted job's tab, else on the first tab with work in it.
  const activeTab = useMemo(() => {
    if (tab) return tab;
    const highlighted = highlightId && items.find((o) => o.id === highlightId);
    if (highlighted) return tabForStatus(highlighted.status);
    return (TABS.find((t) => !["applied", "skipped"].includes(t.key) && counts[t.key] > 0) || TABS[0]).key;
  }, [tab, highlightId, items, counts]);

  const visible = items.filter((o) => (TABS.find((t) => t.key === activeTab)?.statuses || []).includes(o.status));

  const onAction = async (action, opp, extra = {}) => {
    setBusyId(opp.id);
    setError(null);
    setNotice(null);
    try {
      if (action === "open") {
        const result = await fetchWithHeartbeat(`/api/opportunities/${opp.id}/open/`, { method: "POST" });
        const payload = result?.data || result;
        if (typeof onOpened === "function") {
          onOpened(payload.session_state || {}, payload.session_id || null, payload.opportunity || opp);
        }
        return;
      }
      const body = action === "skip" ? { reason: extra.reason } : action === "capture" ? { text: extra.text } : {};
      const result = await fetchWithHeartbeat(`/api/opportunities/${opp.id}/${action}/`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      const payload = result?.data || result;
      if (payload?.message) setNotice(payload.message);
      await load();
    } catch (e) {
      setError(e?.message || `Failed to ${action} the job`);
    } finally {
      setBusyId(null);
    }
  };

  const addManual = async () => {
    if (!manualUrl.trim() && !manualText.trim()) return;
    setError(null);
    try {
      const result = await fetchWithHeartbeat("/api/opportunities/manual/", {
        method: "POST",
        body: JSON.stringify({ url: manualUrl.trim(), text: manualText.trim() }),
      });
      const payload = result?.data || result;
      setNotice(payload?.message || "Saved.");
      setManualUrl("");
      setManualText("");
      await load();
    } catch (e) {
      setError(e?.message || "Failed to add the job");
    }
  };

  return (
    <div style={{ maxWidth: 900, width: "100%", margin: "0 auto", overflowY: "auto", minHeight: 0 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, marginBottom: 12, flexWrap: "wrap" }}>
        <h2 style={{ margin: 0 }}>Jobs</h2>
        <button type="button" onClick={load} disabled={loading} style={buttonStyle(true, loading)}>
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      <div role="tablist" style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 12 }}>
        {TABS.map((t) => (
          <button
            key={t.key}
            role="tab"
            type="button"
            aria-selected={activeTab === t.key}
            onClick={() => setTab(t.key)}
            style={{
              ...buttonStyle(activeTab === t.key),
              fontWeight: activeTab === t.key ? 600 : 400,
            }}
          >
            {t.label} ({counts[t.key] || 0})
          </button>
        ))}
      </div>

      {error && (
        <div role="alert" style={{ marginBottom: 10, color: "var(--error-text, #b91c1c)" }}>
          {error}
        </div>
      )}
      {notice && <div style={{ marginBottom: 10, opacity: 0.85 }}>{notice}</div>}

      {visible.length === 0 && !loading && <div style={{ opacity: 0.7, padding: "12px 0" }}>Nothing here.</div>}
      {visible.map((opp) => (
        <OpportunityCard key={opp.id} opp={opp} highlighted={opp.id === highlightId} busy={busyId === opp.id} onAction={onAction} />
      ))}

      <details style={{ marginTop: 20 }}>
        <summary style={{ cursor: "pointer" }}>Add a job by hand</summary>
        <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 8 }}>
          <input
            aria-label="Job link"
            value={manualUrl}
            onChange={(e) => setManualUrl(e.target.value)}
            placeholder="https://…"
            style={{ fontSize: 14, padding: 6 }}
          />
          <textarea
            aria-label="Job posting text"
            value={manualText}
            onChange={(e) => setManualText(e.target.value)}
            rows={5}
            placeholder="Posting text (optional; without it the job waits for its text)"
            style={{ fontSize: 14 }}
          />
          <div>
            <button type="button" style={buttonStyle(true)} onClick={addManual}>
              Add
            </button>
          </div>
        </div>
      </details>
    </div>
  );
}
