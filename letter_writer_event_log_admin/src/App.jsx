import React, { useCallback, useEffect, useMemo, useState } from "react";

const STORAGE_KEY = "lw_admin_event_log_api_key";

function truncate(s, max) {
  if (s == null) return "";
  const t = String(s);
  if (t.length <= max) return t;
  return `${t.slice(0, max)}…`;
}

async function readErrorDetail(res) {
  try {
    const data = await res.json();
    if (data && typeof data.detail === "string") return data.detail;
    if (Array.isArray(data.detail)) {
      return data.detail.map((d) => d.msg || JSON.stringify(d)).join("; ");
    }
    return JSON.stringify(data);
  } catch {
    return res.statusText || `HTTP ${res.status}`;
  }
}

export default function App() {
  const [apiKey, setApiKey] = useState(() => sessionStorage.getItem(STORAGE_KEY) || "");
  const [documentId, setDocumentId] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [payload, setPayload] = useState(null);
  const [typeFilter, setTypeFilter] = useState("all");
  const [expanded, setExpanded] = useState(() => new Set());

  useEffect(() => {
    if (apiKey) sessionStorage.setItem(STORAGE_KEY, apiKey);
    else sessionStorage.removeItem(STORAGE_KEY);
  }, [apiKey]);

  const sortedEvents = useMemo(() => {
    const log = payload?.application_event_log || [];
    return [...log].sort((a, b) =>
      String(a.timestamp || "").localeCompare(String(b.timestamp || ""))
    );
  }, [payload]);

  const typesPresent = useMemo(() => {
    const s = new Set();
    for (const ev of sortedEvents) {
      if (ev && typeof ev.type === "string") s.add(ev.type);
    }
    return Array.from(s).sort();
  }, [sortedEvents]);

  const visibleRows = useMemo(() => {
    return sortedEvents
      .map((ev, globalIdx) => ({ ev, globalIdx }))
      .filter(({ ev }) => typeFilter === "all" || ev?.type === typeFilter);
  }, [sortedEvents, typeFilter]);

  const load = useCallback(async () => {
    setError(null);
    const id = documentId.trim();
    if (!id) {
      setError("Enter a Firestore document id.");
      return;
    }
    if (!apiKey.trim()) {
      setError("Enter the admin API key (header X-Admin-Event-Log-Key).");
      return;
    }
    setLoading(true);
    setPayload(null);
    try {
      const res = await fetch(`/api/admin/event-log/document/${encodeURIComponent(id)}`, {
        headers: { "X-Admin-Event-Log-Key": apiKey.trim() },
      });
      if (!res.ok) {
        setError(await readErrorDetail(res));
        return;
      }
      setPayload(await res.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [apiKey, documentId]);

  const toggleExpand = (idx) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  const downloadJson = () => {
    if (!payload) return;
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `application_event_log-${payload.document_id}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  const shell = {
    maxWidth: "min(1100px, 100vw - 2rem)",
    margin: "0 auto",
    padding: "1.25rem 1rem 3rem",
  };

  const card = {
    background: "var(--surface)",
    border: "1px solid var(--border)",
    borderRadius: "10px",
    padding: "1rem 1.1rem",
    marginBottom: "1rem",
  };

  return (
    <div style={shell}>
      <header style={{ marginBottom: "1.25rem" }}>
        <h1 style={{ fontSize: "1.35rem", fontWeight: 600, margin: "0 0 0.35rem" }}>
          Application event log
        </h1>
        <p style={{ margin: 0, color: "var(--muted)", fontSize: "0.95rem" }}>
          Admin viewer for Firestore <code>application_event_log</code> on a document. Requires{" "}
          <code>ADMIN_EVENT_LOG_API_KEY</code> on the backend and the same value below (sent as{" "}
          <code>X-Admin-Event-Log-Key</code>).
        </p>
      </header>

      <section style={card}>
        <div style={{ display: "grid", gap: "0.75rem" }}>
          <label style={{ display: "flex", flexDirection: "column", gap: "0.35rem" }}>
            <span style={{ color: "var(--muted)", fontSize: "0.85rem" }}>Admin API key</span>
            <input
              type="password"
              autoComplete="off"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="From server env ADMIN_EVENT_LOG_API_KEY"
              style={inputStyle}
            />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: "0.35rem" }}>
            <span style={{ color: "var(--muted)", fontSize: "0.85rem" }}>Document id</span>
            <input
              value={documentId}
              onChange={(e) => setDocumentId(e.target.value)}
              placeholder="Firestore document UUID"
              style={inputStyle}
            />
          </label>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", alignItems: "center" }}>
            <button type="button" onClick={load} disabled={loading} style={btnPrimary}>
              {loading ? "Loading…" : "Load log"}
            </button>
            <button
              type="button"
              onClick={() => {
                setApiKey("");
                sessionStorage.removeItem(STORAGE_KEY);
              }}
              style={btnGhost}
            >
              Clear saved key
            </button>
            {payload ? (
              <button type="button" onClick={downloadJson} style={btnGhost}>
                Download JSON
              </button>
            ) : null}
          </div>
        </div>
      </section>

      {error ? (
        <div
          role="alert"
          style={{
            ...card,
            borderColor: "var(--danger)",
            color: "var(--danger)",
            whiteSpace: "pre-wrap",
          }}
        >
          {error}
        </div>
      ) : null}

      {payload ? (
        <>
          <section style={card}>
            <h2 style={{ fontSize: "1rem", margin: "0 0 0.75rem" }}>Document</h2>
            <dl
              style={{
                display: "grid",
                gridTemplateColumns: "8rem 1fr",
                gap: "0.35rem 1rem",
                margin: 0,
                fontSize: "0.92rem",
              }}
            >
              <dt style={{ color: "var(--muted)", margin: 0 }}>id</dt>
              <dd style={{ margin: 0 }}>{payload.document_id}</dd>
              <dt style={{ color: "var(--muted)", margin: 0 }}>user_id</dt>
              <dd style={{ margin: 0 }}>{payload.user_id ?? "—"}</dd>
              <dt style={{ color: "var(--muted)", margin: 0 }}>company / role</dt>
              <dd style={{ margin: 0 }}>
                {(payload.company_name || "—") + " / " + (payload.role || "—")}
              </dd>
              <dt style={{ color: "var(--muted)", margin: 0 }}>created / updated</dt>
              <dd style={{ margin: 0 }}>
                {(payload.created_at || "—") + " → " + (payload.updated_at || "—")}
              </dd>
              <dt style={{ color: "var(--muted)", margin: 0 }}>events (stored)</dt>
              <dd style={{ margin: 0 }}>{payload.event_count}</dd>
            </dl>
          </section>

          <section style={card}>
            <div
              style={{
                display: "flex",
                flexWrap: "wrap",
                gap: "0.5rem",
                alignItems: "center",
                marginBottom: "0.75rem",
              }}
            >
              <span style={{ color: "var(--muted)", fontSize: "0.9rem" }}>Filter by type</span>
              <select
                value={typeFilter}
                onChange={(e) => setTypeFilter(e.target.value)}
                style={selectStyle}
              >
                <option value="all">all ({sortedEvents.length})</option>
                {typesPresent.map((t) => (
                  <option key={t} value={t}>
                    {t} ({sortedEvents.filter((e) => e?.type === t).length})
                  </option>
                ))}
              </select>
              <span style={{ color: "var(--muted)", fontSize: "0.85rem" }}>
                Showing {visibleRows.length} row{visibleRows.length === 1 ? "" : "s"}
              </span>
            </div>

            <ol style={{ margin: 0, padding: 0, listStyle: "none" }}>
              {visibleRows.map(({ ev, globalIdx }) => {
                const isOpen = expanded.has(globalIdx);
                const type = ev?.type || "(missing type)";
                return (
                  <li
                    key={`${globalIdx}-${String(ev?.timestamp ?? "")}-${type}`}
                    style={{
                      border: "1px solid var(--border)",
                      borderRadius: "8px",
                      marginBottom: "0.6rem",
                      overflow: "hidden",
                    }}
                  >
                    <button
                      type="button"
                      onClick={() => toggleExpand(globalIdx)}
                      style={rowHeaderBtn}
                    >
                      <span style={badgeForType(type)}>{type}</span>
                      <span style={{ color: "var(--muted)", fontSize: "0.82rem" }}>
                        {ev?.timestamp || "no timestamp"}
                      </span>
                      <span style={{ marginLeft: "auto", color: "var(--muted)" }}>
                        {isOpen ? "▼" : "▶"}
                      </span>
                    </button>
                    {!isOpen ? (
                      <div style={{ padding: "0 0.75rem 0.65rem", color: "var(--muted)", fontSize: "0.88rem" }}>
                        {summaryLine(ev)}
                      </div>
                    ) : (
                      <div style={{ padding: "0 0.75rem 0.75rem" }}>
                        {type === "llm_io" ? <LlmIoDetail ev={ev} /> : null}
                        {type === "user_input" ? <UserInputDetail ev={ev} /> : null}
                        {type !== "llm_io" && type !== "user_input" ? (
                          <pre style={preBlock}>{JSON.stringify(ev, null, 2)}</pre>
                        ) : null}
                      </div>
                    )}
                  </li>
                );
              })}
            </ol>
          </section>
        </>
      ) : null}
    </div>
  );
}

function summaryLine(ev) {
  if (!ev || typeof ev !== "object") return "";
  if (ev.type === "user_input") {
    return `source: ${ev.source || "?"}`;
  }
  if (ev.type === "llm_io") {
    const err = ev.output?.error;
    const bits = [ev.vendor, ev.model, ev.search ? "search" : null, err ? `error: ${truncate(err, 80)}` : null]
      .filter(Boolean)
      .join(" · ");
    const text = ev.output?.text;
    return bits + (text && !err ? ` · out: ${truncate(text, 120)}` : "");
  }
  return truncate(JSON.stringify(ev), 160);
}

function UserInputDetail({ ev }) {
  return (
    <div>
      <p style={{ margin: "0 0 0.5rem", color: "var(--muted)" }}>
        <strong style={{ color: "var(--text)" }}>source:</strong> {ev.source || "—"}
      </p>
      <pre style={preBlock}>{JSON.stringify(ev.payload ?? null, null, 2)}</pre>
    </div>
  );
}

function LlmIoDetail({ ev }) {
  const sys = ev.input?.system || "";
  const msgs = Array.isArray(ev.input?.user_messages) ? ev.input.user_messages : [];
  const outText = ev.output?.text;
  const outErr = ev.output?.error;
  return (
    <div style={{ display: "grid", gap: "0.75rem" }}>
      <div style={{ color: "var(--muted)", fontSize: "0.88rem" }}>
        <strong style={{ color: "var(--text)" }}>vendor</strong> {ev.vendor || "—"} ·{" "}
        <strong style={{ color: "var(--text)" }}>model</strong> {ev.model || "—"} ·{" "}
        <strong style={{ color: "var(--text)" }}>search</strong> {String(!!ev.search)}
      </div>
      <div>
        <div style={subheading}>System</div>
        <pre style={preBlock}>{truncate(sys, 200000)}</pre>
      </div>
      <div>
        <div style={subheading}>User messages ({msgs.length})</div>
        {msgs.map((m, i) => (
          <pre key={i} style={{ ...preBlock, marginBottom: "0.5rem" }}>
            {typeof m === "string" ? m : JSON.stringify(m, null, 2)}
          </pre>
        ))}
      </div>
      <div>
        <div style={subheading}>Output</div>
        {outErr ? (
          <pre style={{ ...preBlock, borderColor: "var(--danger)" }}>{outErr}</pre>
        ) : (
          <pre style={preBlock}>{outText != null ? String(outText) : ""}</pre>
        )}
      </div>
    </div>
  );
}

const inputStyle = {
  width: "100%",
  padding: "0.55rem 0.65rem",
  borderRadius: "6px",
  border: "1px solid var(--border)",
  background: "#121a24",
  color: "var(--text)",
};

const selectStyle = {
  ...inputStyle,
  width: "auto",
  minWidth: "12rem",
};

const btnPrimary = {
  padding: "0.5rem 1rem",
  borderRadius: "6px",
  border: "none",
  background: "var(--accent)",
  color: "#0b0f14",
  fontWeight: 600,
  cursor: "pointer",
};

const btnGhost = {
  ...btnPrimary,
  background: "transparent",
  color: "var(--accent)",
  border: "1px solid var(--border)",
};

const preBlock = {
  margin: 0,
  padding: "0.65rem",
  background: "#121a24",
  border: "1px solid var(--border)",
  borderRadius: "6px",
  overflow: "auto",
  maxHeight: "min(55vh, 520px)",
  whiteSpace: "pre-wrap",
  wordBreak: "break-word",
};

const rowHeaderBtn = {
  width: "100%",
  textAlign: "left",
  display: "flex",
  alignItems: "center",
  gap: "0.65rem",
  padding: "0.55rem 0.75rem",
  border: "none",
  background: "#141c28",
  color: "var(--text)",
  cursor: "pointer",
  font: "inherit",
};

const subheading = {
  fontSize: "0.8rem",
  color: "var(--warn)",
  marginBottom: "0.35rem",
  fontWeight: 600,
};

function badgeForType(type) {
  const base = {
    display: "inline-block",
    padding: "0.12rem 0.45rem",
    borderRadius: "4px",
    fontSize: "0.78rem",
    fontWeight: 600,
    letterSpacing: "0.02em",
  };
  if (type === "llm_io") return { ...base, background: "#2a3d55", color: "#9fd0ff" };
  if (type === "user_input") return { ...base, background: "#3d3a2a", color: "#e8d49a" };
  return { ...base, background: "#3a2a3d", color: "#e0b8e8" };
}
