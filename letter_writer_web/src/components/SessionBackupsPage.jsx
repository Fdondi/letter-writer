import React, { useState, useEffect } from "react";
import { fetchWithHeartbeat } from "../utils/apiHelpers";

export default function SessionBackupsPage({ onSessionRestored = null }) {
  const [backups, setBackups] = useState([]);
  const [backupsLoading, setBackupsLoading] = useState(false);
  const [backupsError, setBackupsError] = useState(null);
  const [restoringFilename, setRestoringFilename] = useState(null);

  const loadBackups = async () => {
    try {
      setBackupsLoading(true);
      setBackupsError(null);
      const res = await fetch("/api/phases/backups/", { credentials: "include" });
      if (!res.ok) {
        const detail = await res.text();
        throw new Error(detail || `Failed to list backups (${res.status})`);
      }
      const data = await res.json();
      setBackups(Array.isArray(data.backups) ? data.backups : []);
    } catch (e) {
      setBackupsError(e?.message || "Failed to list session backups");
      setBackups([]);
    } finally {
      setBackupsLoading(false);
    }
  };

  useEffect(() => {
    loadBackups();
  }, []);

  const handleRestoreBackup = async (backup) => {
    const filename = typeof backup === "string" ? backup : backup?.filename;
    if (!filename) return;
    if (backup && typeof backup === "object" && backup.empty) {
      setBackupsError(
        "That backup is empty (no job text or letters). Choose one that shows a company/title and a non-empty stage."
      );
      return;
    }
    const labelParts = [];
    if (backup && typeof backup === "object") {
      if (backup.company_name) labelParts.push(backup.company_name);
      if (backup.job_title) labelParts.push(backup.job_title);
      if (backup.stage) labelParts.push(`stage: ${backup.stage}`);
      if (backup.size != null) labelParts.push(`${Math.round(backup.size / 1024)} KB`);
    }
    const label = labelParts.length ? labelParts.join(" · ") : filename;
    const confirmed = window.confirm(
      `Restore session from backup?\n\n${label}\n${filename}\n\nThis replaces the current working session on the server with the backup contents.`
    );
    if (!confirmed) return;
    try {
      setRestoringFilename(filename);
      setBackupsError(null);
      const result = await fetchWithHeartbeat("/api/phases/restore-from-backup/", {
        method: "POST",
        body: JSON.stringify({ filename }),
      });
      const payload = result?.data || result;
      if (typeof onSessionRestored === "function") {
        onSessionRestored(payload.session_state || {}, payload.session_id || null);
      }
    } catch (e) {
      setBackupsError(e?.message || "Failed to restore session backup");
    } finally {
      setRestoringFilename(null);
    }
  };

  const formatBackupTime = (backup) => {
    const raw = backup?.saved_at || (backup?.mtime ? new Date(backup.mtime * 1000).toISOString() : null);
    if (!raw) return "—";
    try {
      return new Date(raw).toLocaleString();
    } catch {
      return String(raw);
    }
  };

  return (
    <div>
      <div
        style={{
          marginBottom: 30,
          padding: 20,
          border: "1px solid var(--border-color)",
          borderRadius: "8px",
          backgroundColor: "var(--card-bg)",
        }}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: 15,
            gap: 12,
          }}
        >
          <h3 style={{ margin: 0, color: "var(--text-color)" }}>Session backups</h3>
          <button
            type="button"
            onClick={loadBackups}
            disabled={backupsLoading}
            style={{
              padding: "6px 12px",
              backgroundColor: "#3b82f6",
              color: "white",
              border: "none",
              borderRadius: "4px",
              cursor: backupsLoading ? "not-allowed" : "pointer",
              opacity: backupsLoading ? 0.7 : 1,
              fontSize: "14px",
            }}
          >
            {backupsLoading ? "Refreshing…" : "Refresh"}
          </button>
        </div>
        <p
          style={{
            marginTop: 0,
            marginBottom: 15,
            fontSize: "14px",
            color: "var(--secondary-text-color)",
          }}
        >
          Automatic silent copies of your working session are written to the host
          folder <code>session_backups/</code>. Restore replaces the current
          server session with a chosen backup so you can continue where you left
          off. Prefer rows with a company/title and stage (input / phases /
          assembly); empty login/CV-only snapshots cannot restore work.
        </p>
        {backupsError && (
          <div
            style={{
              marginBottom: 12,
              padding: "8px 12px",
              backgroundColor: "#fef2f2",
              color: "#b91c1c",
              borderRadius: "4px",
              fontSize: "14px",
            }}
          >
            {backupsError}
          </div>
        )}
        {backupsLoading && backups.length === 0 ? (
          <p style={{ color: "var(--secondary-text-color)", fontSize: "14px" }}>
            Loading backups…
          </p>
        ) : backups.length === 0 ? (
          <p style={{ color: "var(--secondary-text-color)", fontSize: "14px" }}>
            No session backups found yet.
          </p>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {backups.map((backup) => (
              <div
                key={backup.filename}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  gap: 12,
                  padding: "10px 12px",
                  border: "1px solid var(--border-color)",
                  borderRadius: "6px",
                  backgroundColor: "var(--input-bg)",
                  opacity: backup.empty ? 0.55 : 1,
                }}
              >
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div
                    style={{
                      fontSize: "13px",
                      fontWeight: 600,
                      color: "var(--text-color)",
                      wordBreak: "break-word",
                    }}
                  >
                    {backup.company_name || "Unknown company"}
                    {backup.job_title ? ` — ${backup.job_title}` : ""}
                    {backup.is_latest ? " (latest)" : ""}
                    {backup.empty ? " (empty)" : ""}
                  </div>
                  <div
                    style={{
                      fontSize: "12px",
                      color: "var(--secondary-text-color)",
                      marginTop: 2,
                    }}
                  >
                    {formatBackupTime(backup)}
                    {backup.stage ? ` · ${backup.stage}` : ""}
                    {backup.vendor_count ? ` · ${backup.vendor_count} vendors` : ""}
                    {backup.size != null ? ` · ${Math.round(backup.size / 1024)} KB` : ""}
                  </div>
                  <div
                    style={{
                      fontSize: "11px",
                      color: "var(--secondary-text-color)",
                      marginTop: 2,
                      wordBreak: "break-all",
                    }}
                  >
                    {backup.filename}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => handleRestoreBackup(backup)}
                  disabled={!!restoringFilename || !!backup.empty}
                  title={backup.empty ? "Empty backup — nothing to restore" : "Restore this backup"}
                  style={{
                    padding: "6px 12px",
                    backgroundColor:
                      restoringFilename === backup.filename || backup.empty
                        ? "#9ca3af"
                        : "#059669",
                    color: "white",
                    border: "none",
                    borderRadius: "4px",
                    cursor:
                      restoringFilename || backup.empty ? "not-allowed" : "pointer",
                    fontSize: "13px",
                    whiteSpace: "nowrap",
                  }}
                >
                  {restoringFilename === backup.filename ? "Restoring…" : "Restore"}
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
