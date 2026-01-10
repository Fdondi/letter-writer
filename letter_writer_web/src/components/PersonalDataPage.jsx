import React, { useEffect, useState } from "react";
import { fetchWithHeartbeat } from "../utils/apiHelpers";

export default function PersonalDataPage() {
  const [cv, setCv] = useState("");
  const [revisions, setRevisions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState(null);
  const [isEditing, setIsEditing] = useState(false);
  const [editedCv, setEditedCv] = useState("");

  const fetchCv = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await fetch("/api/personal-data/cv/");
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setCv(data.cv || "");
      setRevisions(data.revisions || []);
    } catch (e) {
      setError(`Failed to load CV: ${e.message || e}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchCv();
  }, []);

  const handleSave = async () => {
    if (!editedCv.trim()) {
      setError("CV content cannot be empty");
      return;
    }

    try {
      setSaving(true);
      setError(null);
      const result = await fetchWithHeartbeat("/api/personal-data/cv/", {
        method: "POST",
        body: JSON.stringify({
          content: editedCv,
          source: "manual_edit",
        }),
      });
      const data = result.data;
      setCv(data.cv || "");
      setRevisions(data.revisions || []);
      setIsEditing(false);
      setEditedCv("");
    } catch (e) {
      setError(`Failed to save CV: ${e.message || e}`);
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = () => {
    setIsEditing(false);
    setEditedCv("");
    setError(null);
  };

  const handleFileUpload = async (event) => {
    const file = event.target.files[0];
    if (!file) return;

    // Validate file type
    const filename = file.name.toLowerCase();
    if (!filename.endsWith(".txt") && !filename.endsWith(".md") && !filename.endsWith(".pdf")) {
      setError("Unsupported file type. Please upload .txt, .md, or .pdf files.");
      return;
    }

    try {
      setUploading(true);
      setError(null);
      const formData = new FormData();
      formData.append("file", file);

      const result = await fetchWithHeartbeat("/api/personal-data/cv/", {
        method: "POST",
        body: formData,
      });
      const data = result.data;
      setCv(data.cv || "");
      setRevisions(data.revisions || []);
      // Clear file input
      event.target.value = "";
    } catch (e) {
      setError(`Failed to upload file: ${e.message || e}`);
    } finally {
      setUploading(false);
    }
  };

  const formatDate = (dateString) => {
    if (!dateString) return "Unknown date";
    try {
      const date = new Date(dateString);
      return date.toLocaleString();
    } catch {
      return dateString;
    }
  };

  if (loading) {
    return (
      <div style={{ padding: 20, textAlign: "center" }}>
        <p>Loading CV...</p>
      </div>
    );
  }

  return (
    <div style={{ padding: 20 }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 20,
        }}
      >
        <h2 style={{ margin: 0, color: "var(--text-color)" }}>Your CV</h2>
        <div style={{ display: "flex", gap: 8 }}>
          {!isEditing && (
            <>
              <label
                style={{
                  padding: "8px 12px",
                  border: "1px solid var(--border-color)",
                  borderRadius: "4px",
                  backgroundColor: "var(--button-bg)",
                  color: "var(--button-text)",
                  cursor: "pointer",
                  fontSize: "14px",
                  display: "inline-block",
                }}
              >
                {uploading ? "Uploading..." : "📄 Upload File"}
                <input
                  type="file"
                  accept=".txt,.md,.pdf"
                  onChange={handleFileUpload}
                  disabled={uploading}
                  style={{ display: "none" }}
                />
              </label>
              <button
                onClick={() => {
                  setEditedCv(cv);
                  setIsEditing(true);
                }}
                style={{
                  padding: "8px 12px",
                  border: "1px solid var(--border-color)",
                  borderRadius: "4px",
                  backgroundColor: "var(--button-bg)",
                  color: "var(--button-text)",
                  cursor: "pointer",
                  fontSize: "14px",
                }}
              >
                ✏️ Edit
              </button>
            </>
          )}
          {isEditing && (
            <>
              <button
                onClick={handleCancel}
                disabled={saving}
                style={{
                  padding: "8px 12px",
                  border: "1px solid var(--border-color)",
                  borderRadius: "4px",
                  backgroundColor: "var(--button-bg)",
                  color: "var(--button-text)",
                  cursor: "pointer",
                  fontSize: "14px",
                  opacity: saving ? 0.5 : 1,
                }}
              >
                Cancel
              </button>
              <button
                onClick={handleSave}
                disabled={saving}
                style={{
                  padding: "8px 12px",
                  border: "1px solid var(--border-color)",
                  borderRadius: "4px",
                  backgroundColor: "#3b82f6",
                  color: "white",
                  cursor: saving ? "not-allowed" : "pointer",
                  fontSize: "14px",
                  opacity: saving ? 0.5 : 1,
                }}
              >
                {saving ? "Saving..." : "Save"}
              </button>
            </>
          )}
        </div>
      </div>

      {error && (
        <div
          style={{
            padding: 12,
            marginBottom: 20,
            backgroundColor: "#fee",
            color: "#c33",
            borderRadius: "4px",
            border: "1px solid #fcc",
          }}
        >
          {error}
        </div>
      )}

      {!isEditing ? (
        <div
          style={{
            padding: 16,
            backgroundColor: "var(--bg-color)",
            border: "1px solid var(--border-color)",
            borderRadius: "4px",
            minHeight: 400,
            whiteSpace: "pre-wrap",
            fontFamily: "monospace",
            fontSize: "14px",
            lineHeight: "1.6",
            color: "var(--text-color)",
          }}
        >
          {cv || (
            <div style={{ color: "var(--text-color)", opacity: 0.6, fontStyle: "italic" }}>
              No CV uploaded yet. Upload a file or click Edit to add your CV.
            </div>
          )}
        </div>
      ) : (
        <textarea
          value={editedCv}
          onChange={(e) => setEditedCv(e.target.value)}
          style={{
            width: "100%",
            minHeight: 400,
            padding: 16,
            fontFamily: "monospace",
            fontSize: "14px",
            lineHeight: "1.6",
            border: "1px solid var(--border-color)",
            borderRadius: "4px",
            backgroundColor: "var(--bg-color)",
            color: "var(--text-color)",
            resize: "vertical",
          }}
          placeholder="Enter your CV content here..."
        />
      )}

      {revisions.length > 0 && (
        <div style={{ marginTop: 30 }}>
          <h3 style={{ color: "var(--text-color)", marginBottom: 12 }}>Revision History</h3>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {[...revisions].reverse().map((rev, idx) => (
              <div
                key={idx}
                style={{
                  padding: 12,
                  backgroundColor: "var(--bg-color)",
                  border: "1px solid var(--border-color)",
                  borderRadius: "4px",
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                }}
              >
                <div>
                  <div style={{ color: "var(--text-color)", fontWeight: "bold" }}>
                    Revision #{rev.revision_number || revisions.length - idx}
                  </div>
                  <div style={{ color: "var(--text-color)", opacity: 0.7, fontSize: "12px", marginTop: 4 }}>
                    {formatDate(rev.created_at)} • {rev.source || "unknown"}
                  </div>
                </div>
                <button
                  onClick={() => {
                    setEditedCv(rev.content);
                    setIsEditing(true);
                  }}
                  style={{
                    padding: "6px 10px",
                    border: "1px solid var(--border-color)",
                    borderRadius: "4px",
                    backgroundColor: "var(--button-bg)",
                    color: "var(--button-text)",
                    cursor: "pointer",
                    fontSize: "12px",
                  }}
                >
                  Restore
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
