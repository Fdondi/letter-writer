import React, { useEffect, useState, useCallback } from "react";
import { getCsrfToken } from "../utils/apiHelpers";

function formatDate(dateString) {
  if (!dateString) return "-";
  const date = new Date(dateString);
  if (isNaN(date.getTime())) return "-";
  const day = String(date.getDate()).padStart(2, "0");
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const year = String(date.getFullYear()).slice(-2);
  return `${day}/${month}/${year}`;
}

export default function DocumentsPage() {
  const [documents, setDocuments] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [selected, setSelected] = useState(null);
  const [editedLetter, setEditedLetter] = useState("");
  const [isEditing, setIsEditing] = useState(false);
  const [loadingList, setLoadingList] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [companySearch, setCompanySearch] = useState("");
  const [roleSearch, setRoleSearch] = useState("");

  const fetchList = useCallback(async () => {
    try {
      setLoadingList(true);
      setError(null);
      const params = new URLSearchParams();
      if (companySearch.trim()) {
        params.append("company_name", companySearch.trim());
      }
      if (roleSearch.trim()) {
        params.append("role", roleSearch.trim());
      }
      const queryString = params.toString();
      const url = `/api/documents${queryString ? `?${queryString}` : ""}`;
      const res = await fetch(url);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      // Sort by created_at descending (most recent first)
      // Parse dates to ensure proper numeric comparison, not string comparison
      const sortedDocs = (data.documents || []).sort((a, b) => {
        const dateA = a.created_at ? new Date(a.created_at).getTime() : 0;
        const dateB = b.created_at ? new Date(b.created_at).getTime() : 0;
        return dateB - dateA; // Descending order (most recent first)
      });
      setDocuments(sortedDocs);
    } catch (e) {
      setError(`Failed to load documents: ${e.message || e}`);
    } finally {
      setLoadingList(false);
    }
  }, [companySearch, roleSearch]);

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
  }, [fetchList]);

  useEffect(() => {
    if (selectedId) {
      fetchDetail(selectedId);
    } else {
      setSelected(null);
    }
  }, [selectedId]);

  useEffect(() => {
    if (selected) {
      setEditedLetter(selected.letter_text || "");
      setIsEditing(false);
    } else {
      setEditedLetter("");
      setIsEditing(false);
    }
  }, [selected]);

  const saveDocument = async () => {
    if (!selectedId) return;
    try {
      setSaving(true);
      setError(null);
      const csrfToken = await getCsrfToken();
      const res = await fetch(`/api/documents/${selectedId}/`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken,
        },
        body: JSON.stringify({ ...selected, letter_text: editedLetter }),
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setSelected(data.document);
      setIsEditing(false);
      await fetchList();
    } catch (e) {
      setError(`Failed to save document: ${e.message || e}`);
    } finally {
      setSaving(false);
    }
  };

  const deleteSelected = async () => {
    if (!selectedId) return;
    const confirmed = window.confirm("Delete this document? This cannot be undone.");
    if (!confirmed) return;
    try {
      setDeleting(true);
      setError(null);
      const csrfToken = await getCsrfToken();
      const res = await fetch(`/api/documents/${selectedId}/`, {
        method: "DELETE",
        headers: {
          "X-CSRFToken": csrfToken,
        },
      });
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
          {doc.company_name_original || doc.company_name || "-"}
        </td>
        <td style={{ padding: "6px 8px", borderBottom: "1px solid var(--border-color)" }}>
          {doc.role || "-"}
        </td>
        <td style={{ padding: "6px 8px", borderBottom: "1px solid var(--border-color)" }}>
          {doc.status || "-"}
        </td>
        <td style={{ padding: "6px 8px", borderBottom: "1px solid var(--border-color)" }}>
          {formatDate(doc.created_at)}
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

        <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
          <input
            type="text"
            placeholder="Search by company..."
            value={companySearch}
            onChange={(e) => setCompanySearch(e.target.value)}
            style={{
              flex: 1,
              padding: "6px 8px",
              border: "1px solid var(--border-color)",
              borderRadius: 4,
              background: "var(--input-bg)",
              color: "var(--text-color)",
              fontSize: 14,
            }}
          />
          <input
            type="text"
            placeholder="Search by role..."
            value={roleSearch}
            onChange={(e) => setRoleSearch(e.target.value)}
            style={{
              flex: 1,
              padding: "6px 8px",
              border: "1px solid var(--border-color)",
              borderRadius: 4,
              background: "var(--input-bg)",
              color: "var(--text-color)",
              fontSize: 14,
            }}
          />
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
                <th style={{ textAlign: "left", padding: "6px 8px" }}>Created</th>
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
              <strong>Company:</strong> {selected.company_name_original || selected.company_name || "-"}
            </div>
            <div>
              <strong>Role:</strong> {selected.role || "-"}
            </div>
            <div>
              <strong>Status:</strong> {selected.status || "-"}
            </div>
            <div>
              <strong>Updated:</strong> {formatDate(selected.updated_at)}
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
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                <strong>Final letter:</strong>
                <div>
                  {isEditing ? (
                    <>
                      <button
                        onClick={() => {
                          setIsEditing(false);
                          setEditedLetter(selected.letter_text || "");
                        }}
                        disabled={saving}
                        style={{
                          padding: "2px 8px",
                          fontSize: "12px",
                          background: "var(--button-bg)",
                          color: "var(--button-text)",
                          border: "1px solid var(--border-color)",
                          borderRadius: 4,
                          cursor: "pointer",
                          marginRight: 8,
                        }}
                      >
                        Cancel
                      </button>
                      <button
                        onClick={saveDocument}
                        disabled={saving}
                        style={{
                          padding: "2px 8px",
                          fontSize: "12px",
                          background: saving ? "var(--border-color)" : "var(--button-bg)",
                          color: saving ? "var(--secondary-text-color)" : "var(--button-text)",
                          border: "1px solid var(--border-color)",
                          borderRadius: 4,
                          cursor: saving ? "not-allowed" : "pointer",
                        }}
                      >
                        {saving ? "Saving..." : "Save"}
                      </button>
                    </>
                  ) : (
                    <button
                      onClick={() => setIsEditing(true)}
                      style={{
                        padding: "2px 8px",
                        fontSize: "12px",
                        background: "var(--button-bg)",
                        color: "var(--button-text)",
                        border: "1px solid var(--border-color)",
                        borderRadius: 4,
                        cursor: "pointer",
                      }}
                    >
                      Edit
                    </button>
                  )}
                </div>
              </div>
              {isEditing ? (
                <textarea
                  value={editedLetter}
                  onChange={(e) => setEditedLetter(e.target.value)}
                  style={{
                    width: "100%",
                    minHeight: "200px",
                    whiteSpace: "pre-wrap",
                    background: "var(--input-bg)",
                    border: "1px solid var(--border-color)",
                    borderRadius: 4,
                    padding: 8,
                    marginTop: 4,
                    resize: "vertical",
                    color: "var(--text-color)",
                    fontFamily: "monospace",
                    boxSizing: "border-box",
                  }}
                />
              ) : (
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
              )}
            </div>
            <div>
              <strong>AI letters:</strong>
              {(selected.ai_letters || []).length === 0 ? (
                <div style={{ color: "var(--secondary-text-color)" }}>None</div>
              ) : (
                (selected.ai_letters || []).map((l, idx) => (
                  <div key={idx} style={{ marginBottom: 16 }}>
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
                        marginBottom: 8,
                      }}
                    >
                      {l.text || ""}
                    </pre>
                    {l.user_corrections && l.user_corrections.length > 0 && (
                      <div style={{ marginTop: 8 }}>
                        <div style={{ fontSize: "12px", fontWeight: 600, marginBottom: 4, color: "var(--secondary-text-color)" }}>
                          User corrections:
                        </div>
                        {l.user_corrections.map((corr, corrIdx) => {
                          if (corr.type === "full") {
                            return (
                              <div key={corrIdx} style={{ marginBottom: 8, fontSize: "12px" }}>
                                <div style={{ color: "#ef4444", marginBottom: 2 }}>
                                  <strong>Original:</strong> {corr.original || ""}
                                </div>
                                <div style={{ color: "#10b981" }}>
                                  <strong>Edited:</strong> {corr.edited || ""}
                                </div>
                              </div>
                            );
                          } else {
                            return (
                              <div key={corrIdx} style={{ marginBottom: 4, fontSize: "12px", fontFamily: "monospace" }}>
                                <span style={{ color: "#ef4444" }}>-{corr.original || ""}</span>
                                <span style={{ color: "#10b981" }}>+{corr.edited || ""}</span>
                              </div>
                            );
                          }
                        })}
                      </div>
                    )}
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


