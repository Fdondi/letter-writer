import React, { useEffect, useState } from "react";

export default function DocumentsPage() {
  const [documents, setDocuments] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [selected, setSelected] = useState(null);
  const [loadingList, setLoadingList] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState(null);

  const fetchList = async () => {
    try {
      setLoadingList(true);
      setError(null);
      const res = await fetch("/api/documents/");
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setDocuments(data.documents || []);
    } catch (e) {
      setError(`Failed to load documents: ${e.message || e}`);
    } finally {
      setLoadingList(false);
    }
  };

  const fetchDetail = async (id) => {
    if (!id) return;
    try {
      setLoadingDetail(true);
      setError(null);
      const res = await fetch(`/api/documents/${id}/`);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setSelected(data.document || null);
    } catch (e) {
      setError(`Failed to load document: ${e.message || e}`);
    } finally {
      setLoadingDetail(false);
    }
  };

  useEffect(() => {
    fetchList();
  }, []);

  useEffect(() => {
    if (selectedId) {
      fetchDetail(selectedId);
    } else {
      setSelected(null);
    }
  }, [selectedId]);

  const deleteSelected = async () => {
    if (!selectedId) return;
    const confirmed = window.confirm("Delete this document? This cannot be undone.");
    if (!confirmed) return;
    try {
      setDeleting(true);
      setError(null);
      const res = await fetch(`/api/documents/${selectedId}/`, { method: "DELETE" });
      if (!res.ok) throw new Error(await res.text());
      setSelectedId(null);
      setSelected(null);
      await fetchList();
    } catch (e) {
      setError(`Failed to delete document: ${e.message || e}`);
    } finally {
      setDeleting(false);
    }
  };

  const renderRow = (doc) => {
    return (
      <tr
        key={doc.id}
        onClick={() => setSelectedId(doc.id)}
        style={{
          cursor: "pointer",
          backgroundColor: selectedId === doc.id ? "var(--panel-bg)" : "transparent",
        }}
      >
        <td style={{ padding: "6px 8px", borderBottom: "1px solid var(--border-color)" }}>
          {doc.company_name || "-"}
        </td>
        <td style={{ padding: "6px 8px", borderBottom: "1px solid var(--border-color)" }}>
          {doc.role || "-"}
        </td>
        <td style={{ padding: "6px 8px", borderBottom: "1px solid var(--border-color)" }}>
          {doc.status || "-"}
        </td>
        <td style={{ padding: "6px 8px", borderBottom: "1px solid var(--border-color)" }}>
          {doc.updated_at ? new Date(doc.updated_at).toLocaleString() : "-"}
        </td>
      </tr>
    );
  };

  return (
    <div style={{ display: "flex", gap: 16, minHeight: "70vh" }}>
      <div style={{ flex: 1 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
          <h3 style={{ margin: 0, color: "var(--text-color)" }}>Documents</h3>
          <button
            onClick={fetchList}
            disabled={loadingList}
            style={{
              padding: "6px 12px",
              background: loadingList ? "var(--border-color)" : "var(--button-bg)",
              color: "var(--button-text)",
              border: "1px solid var(--border-color)",
              borderRadius: 4,
              cursor: loadingList ? "not-allowed" : "pointer",
            }}
          >
            {loadingList ? "Refreshing..." : "Refresh"}
          </button>
        </div>

        {error && (
          <div
            style={{
              marginBottom: 10,
              padding: 10,
              background: "var(--error-bg)",
              border: "1px solid var(--error-border)",
              color: "var(--error-text)",
              borderRadius: 4,
            }}
          >
            {error}
          </div>
        )}

        <div style={{ border: "1px solid var(--border-color)", borderRadius: 4, overflow: "hidden" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", color: "var(--text-color)" }}>
            <thead style={{ background: "var(--header-bg)" }}>
              <tr>
                <th style={{ textAlign: "left", padding: "6px 8px" }}>Company</th>
                <th style={{ textAlign: "left", padding: "6px 8px" }}>Role</th>
                <th style={{ textAlign: "left", padding: "6px 8px" }}>Status</th>
                <th style={{ textAlign: "left", padding: "6px 8px" }}>Updated</th>
              </tr>
            </thead>
            <tbody>
              {documents.length === 0 ? (
                <tr>
                  <td colSpan={4} style={{ padding: 12, textAlign: "center", color: "var(--secondary-text-color)" }}>
                    {loadingList ? "Loading..." : "No documents yet"}
                  </td>
                </tr>
              ) : (
                documents.map(renderRow)
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div style={{ flex: 1, border: "1px solid var(--border-color)", borderRadius: 4, padding: 12 }}>
        <h3 style={{ marginTop: 0, color: "var(--text-color)" }}>Details</h3>
        <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
          <button
            onClick={deleteSelected}
            disabled={!selectedId || deleting}
            style={{
              padding: "6px 12px",
              background: deleting ? "var(--border-color)" : "#ef4444",
              color: deleting ? "var(--secondary-text-color)" : "white",
              border: "1px solid var(--border-color)",
              borderRadius: 4,
              cursor: !selectedId || deleting ? "not-allowed" : "pointer",
            }}
          >
            {deleting ? "Deleting..." : "Delete"}
          </button>
        </div>
        {loadingDetail && <p style={{ color: "var(--secondary-text-color)" }}>Loading...</p>}
        {!loadingDetail && !selected && (
          <p style={{ color: "var(--secondary-text-color)" }}>Select a document to view details.</p>
        )}
        {selected && (
          <div style={{ display: "flex", flexDirection: "column", gap: 12, color: "var(--text-color)" }}>
            <div>
              <strong>Company:</strong> {selected.company_name || "-"}
            </div>
            <div>
              <strong>Role:</strong> {selected.role || "-"}
            </div>
            <div>
              <strong>Status:</strong> {selected.status || "-"}
            </div>
            <div>
              <strong>Updated:</strong> {selected.updated_at ? new Date(selected.updated_at).toLocaleString() : "-"}
            </div>
            <div>
              <strong>Job text:</strong>
              <pre
                style={{
                  whiteSpace: "pre-wrap",
                  background: "var(--pre-bg)",
                  border: "1px solid var(--border-color)",
                  borderRadius: 4,
                  padding: 8,
                  maxHeight: 200,
                  overflowY: "auto",
                  marginTop: 4,
                }}
              >
                {selected.job_text || ""}
              </pre>
            </div>
            <div>
              <strong>Final letter:</strong>
              <pre
                style={{
                  whiteSpace: "pre-wrap",
                  background: "var(--pre-bg)",
                  border: "1px solid var(--border-color)",
                  borderRadius: 4,
                  padding: 8,
                  maxHeight: 200,
                  overflowY: "auto",
                  marginTop: 4,
                }}
              >
                {selected.letter_text || ""}
              </pre>
            </div>
            <div>
              <strong>AI letters:</strong>
              {(selected.ai_letters || []).length === 0 ? (
                <div style={{ color: "var(--secondary-text-color)" }}>None</div>
              ) : (
                (selected.ai_letters || []).map((l, idx) => (
                  <div key={idx} style={{ marginBottom: 8 }}>
                    <div style={{ fontWeight: 600 }}>{l.vendor || "unknown"}</div>
                    <pre
                      style={{
                        whiteSpace: "pre-wrap",
                        background: "var(--pre-bg)",
                        border: "1px solid var(--border-color)",
                        borderRadius: 4,
                        padding: 8,
                        maxHeight: 160,
                        overflowY: "auto",
                      }}
                    >
                      {l.text || ""}
                    </pre>
                  </div>
                ))
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}


