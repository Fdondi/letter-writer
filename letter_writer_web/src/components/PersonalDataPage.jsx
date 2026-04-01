import React, { useEffect, useState, useMemo } from "react";
import ReactMarkdown from "react-markdown";
import { fetchWithHeartbeat } from "../utils/apiHelpers";
import { newId } from "./phases/feedbackItemUtils";

// Extract headers from markdown text
const extractHeaders = (markdown) => {
  if (!markdown) return [];
  const lines = markdown.split("\n");
  const headers = [];
  
  lines.forEach((line, index) => {
    // Match markdown headers: # Header, ## Header, etc.
    const headerMatch = line.match(/^(#{1,6})\s+(.+)$/);
    if (headerMatch) {
      const level = headerMatch[1].length;
      const text = headerMatch[2].trim();
      // Create a slug for the header (simple version)
      const slug = text
        .toLowerCase()
        .replace(/[^\w\s-]/g, "")
        .replace(/\s+/g, "-")
        .replace(/-+/g, "-");
      headers.push({ level, text, slug, lineNumber: index });
    }
  });
  
  return headers;
};

// Helper to extract text from React children
const extractTextFromChildren = (children) => {
  if (typeof children === "string") return children;
  if (Array.isArray(children)) {
    return children.map(extractTextFromChildren).join("");
  }
  if (children?.props?.children) {
    return extractTextFromChildren(children.props.children);
  }
  return "";
};

// Custom component for headers with IDs for scrolling
const HeaderRenderer = ({ level, children, ...props }) => {
  const text = extractTextFromChildren(children);
  const slug = text
    .toLowerCase()
    .replace(/[^\w\s-]/g, "")
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-");
  
  const Tag = `h${level}`;
  return <Tag id={slug} {...props}>{children}</Tag>;
};

export default function PersonalDataPage() {
  const [cv, setCv] = useState("");
  const [revisions, setRevisions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState(null);
  const [isEditing, setIsEditing] = useState(false);
  const [editedCv, setEditedCv] = useState("");
  /** @type {[Array<Record<string, unknown>>, function]} */
  const [extraInfo, setExtraInfo] = useState([]);
  const [savingExtra, setSavingExtra] = useState(false);

  const fetchCv = async () => {
    try {
      setLoading(true);
      setError(null);
      // Updated endpoint path
      const res = await fetch("/api/personal-data/");
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setCv(data.cv || "");
      setRevisions(data.revisions || []);
      setExtraInfo(Array.isArray(data.extra_info) ? data.extra_info : []);
    } catch (e) {
      setError(`Failed to load CV: ${e.message || e}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchCv();
  }, []);

  // Extract headers from CV for table of contents
  const headers = useMemo(() => extractHeaders(cv), [cv]);
  
  // Track which sections are expanded (default: all expanded)
  const [expandedSections, setExpandedSections] = useState(new Set());
  
  // Initialize all sections as expanded when headers change
  useEffect(() => {
    setExpandedSections(new Set(headers.map((_, idx) => idx)));
  }, [headers]);
  
  const toggleSection = (headerIndex) => {
    setExpandedSections((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(headerIndex)) {
        newSet.delete(headerIndex);
      } else {
        newSet.add(headerIndex);
      }
      return newSet;
    });
  };

  // Recursive component for TOC sections
  const TOCSection = ({ startIndex, parentLevel }) => {
    if (startIndex >= headers.length) return null;
    
    const header = headers[startIndex];
    // If this header is at the same level or higher than parent, it's a sibling, not a child
    if (header.level <= parentLevel) return null;
    
    const hasChildren = startIndex < headers.length - 1 && 
      headers[startIndex + 1].level > header.level;
    const isExpanded = expandedSections.has(startIndex);
    
    return (
      <div>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            padding: "4px 0",
            paddingLeft: `${(header.level - 1) * 12}px`,
          }}
        >
          {hasChildren && (
            <button
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                toggleSection(startIndex);
              }}
              style={{
                background: "none",
                border: "none",
                color: "var(--text-color)",
                cursor: "pointer",
                padding: "0 4px",
                fontSize: "12px",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                width: "20px",
                height: "20px",
                flexShrink: 0,
              }}
              onMouseEnter={(e) => {
                e.target.style.backgroundColor = "var(--panel-bg)";
                e.target.style.borderRadius = "3px";
              }}
              onMouseLeave={(e) => {
                e.target.style.backgroundColor = "transparent";
              }}
            >
              {isExpanded ? "▼" : "▶"}
            </button>
          )}
          {!hasChildren && <div style={{ width: "20px", flexShrink: 0 }} />}
          <a
            href={`#${header.slug}`}
            onClick={(e) => {
              e.preventDefault();
              scrollToHeader(header.slug);
            }}
            style={{
              padding: "4px 8px",
              color: "var(--text-color)",
              textDecoration: "none",
              fontSize: header.level === 1 ? "14px" : header.level === 2 ? "13px" : "12px",
              fontWeight: header.level <= 2 ? "600" : "400",
              display: "block",
              flex: 1,
              borderRadius: "4px",
              transition: "background-color 0.2s",
            }}
            onMouseEnter={(e) => {
              e.target.style.backgroundColor = "var(--panel-bg)";
            }}
            onMouseLeave={(e) => {
              e.target.style.backgroundColor = "transparent";
            }}
          >
            {header.text}
          </a>
        </div>
        {/* Render children only if expanded - when collapsed, nothing renders */}
        {hasChildren && isExpanded && (
          <div>
            {(() => {
              const children = [];
              let currentIndex = startIndex + 1;
              // Render all children (headers with level > current header's level)
              // until we hit a sibling (same or higher level)
              while (currentIndex < headers.length) {
                const nextHeader = headers[currentIndex];
                // If we hit a sibling or parent, stop
                if (nextHeader.level <= header.level) break;
                // This is a child - render it recursively
                children.push(
                  <TOCSection
                    key={currentIndex}
                    startIndex={currentIndex}
                    parentLevel={header.level}
                  />
                );
                // Move to next header after this child's subtree
                const childLevel = nextHeader.level;
                currentIndex++;
                // Skip all descendants of this child
                while (currentIndex < headers.length && headers[currentIndex].level > childLevel) {
                  currentIndex++;
                }
              }
              return children;
            })()}
          </div>
        )}
      </div>
    );
  };

  const handleSave = async () => {
    if (!editedCv.trim()) {
      setError("CV content cannot be empty");
      return;
    }

    try {
      setSaving(true);
      setError(null);
      const result = await fetchWithHeartbeat("/api/personal-data/", {
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

      const result = await fetchWithHeartbeat("/api/personal-data/", {
        method: "POST",
        body: formData,
      });
      const data = result.data;
      setCv(data.cv || "");
      setRevisions(data.revisions || []);
      if (Array.isArray(data.extra_info)) setExtraInfo(data.extra_info);
      // Clear file input
      event.target.value = "";
    } catch (e) {
      setError(`Failed to upload file: ${e.message || e}`);
    } finally {
      setUploading(false);
    }
  };

  const handleDownload = () => {
    if (!cv) return;
    
    // Determine if content is markdown (has headers or other markdown syntax)
    const isMarkdown = /^#{1,6}\s|^\*\*|^\*[^*]|^-\s|^\d+\.\s/m.test(cv);
    const extension = isMarkdown ? "md" : "txt";
    const filename = `cv.${extension}`;
    
    const blob = new Blob([cv], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const scrollToHeader = (slug) => {
    const element = document.getElementById(slug);
    if (element) {
      element.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  };

  const updateExtraRow = (index, patch) => {
    setExtraInfo((prev) => {
      const next = [...prev];
      next[index] = { ...next[index], ...patch };
      return next;
    });
  };

  const addManualExtraRow = () => {
    setExtraInfo((prev) => [
      ...prev,
      {
        id: newId(),
        source: "manual",
        category: "",
        observation: "",
        user_context: "",
        user_instructions: "",
        context_lines: [],
        manual_text: "",
      },
    ]);
  };

  const removeExtraRow = (index) => {
    setExtraInfo((prev) => prev.filter((_, i) => i !== index));
  };

  const handleSaveExtraInfo = async () => {
    try {
      setSavingExtra(true);
      setError(null);
      const result = await fetchWithHeartbeat("/api/personal-data/", {
        method: "POST",
        body: JSON.stringify({ extra_info: extraInfo }),
      });
      const data = result.data;
      if (Array.isArray(data.extra_info)) setExtraInfo(data.extra_info);
    } catch (e) {
      setError(`Failed to save notes: ${e.message || e}`);
    } finally {
      setSavingExtra(false);
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
              {cv && (
                <button
                  onClick={handleDownload}
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
                  ⬇️ Download
                </button>
              )}
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
        <div style={{ display: "flex", gap: 20, alignItems: "flex-start" }}>
          {/* Table of Contents Sidebar */}
          {headers.length > 0 && (
            <div
              style={{
                width: 250,
                flexShrink: 0,
                padding: 16,
                backgroundColor: "var(--bg-color)",
                border: "1px solid var(--border-color)",
                borderRadius: "4px",
                position: "sticky",
                top: 20,
                maxHeight: "calc(100vh - 100px)",
                overflowY: "auto",
              }}
            >
              <h3
                style={{
                  margin: "0 0 12px 0",
                  color: "var(--text-color)",
                  fontSize: "16px",
                  fontWeight: "bold",
                }}
              >
                Table of Contents
              </h3>
              <nav style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                {(() => {
                  const sections = [];
                  let i = 0;
                  while (i < headers.length) {
                    // Render this header as a root-level section
                    sections.push(
                      <TOCSection
                        key={i}
                        startIndex={i}
                        parentLevel={0}
                      />
                    );
                    // Move to next root-level sibling (skip all children)
                    const currentLevel = headers[i].level;
                    i++;
                    while (i < headers.length && headers[i].level > currentLevel) {
                      i++;
                    }
                  }
                  return sections;
                })()}
              </nav>
            </div>
          )}

          {/* CV Content */}
          <div
            style={{
              flex: 1,
              padding: 16,
              backgroundColor: "var(--bg-color)",
              border: "1px solid var(--border-color)",
              borderRadius: "4px",
              minHeight: 400,
            }}
          >
            {cv ? (
              <>
                <style>{`
                  .cv-content h1 {
                    font-size: 2em;
                    margin-top: 1em;
                    margin-bottom: 0.5em;
                    font-weight: bold;
                    border-bottom: 2px solid var(--border-color);
                    padding-bottom: 0.3em;
                    scroll-margin-top: 20px;
                  }
                  .cv-content h2 {
                    font-size: 1.5em;
                    margin-top: 0.8em;
                    margin-bottom: 0.4em;
                    font-weight: bold;
                    border-bottom: 1px solid var(--border-color);
                    padding-bottom: 0.2em;
                    scroll-margin-top: 20px;
                  }
                  .cv-content h3 {
                    font-size: 1.25em;
                    margin-top: 0.6em;
                    margin-bottom: 0.3em;
                    font-weight: 600;
                    scroll-margin-top: 20px;
                  }
                  .cv-content h4, .cv-content h5, .cv-content h6 {
                    font-size: 1.1em;
                    margin-top: 0.5em;
                    margin-bottom: 0.3em;
                    font-weight: 600;
                    scroll-margin-top: 20px;
                  }
                  .cv-content p {
                    margin: 0.5em 0;
                  }
                  .cv-content ul, .cv-content ol {
                    margin: 0.5em 0;
                    padding-left: 2em;
                  }
                  .cv-content li {
                    margin: 0.25em 0;
                  }
                  .cv-content code {
                    background-color: var(--pre-bg);
                    padding: 2px 4px;
                    border-radius: 3px;
                    font-family: monospace;
                    font-size: 0.9em;
                  }
                  .cv-content pre {
                    background-color: var(--pre-bg);
                    padding: 12px;
                    border-radius: 4px;
                    overflow-x: auto;
                    margin: 0.5em 0;
                  }
                  .cv-content pre code {
                    background-color: transparent;
                    padding: 0;
                  }
                  .cv-content blockquote {
                    border-left: 4px solid var(--border-color);
                    padding-left: 1em;
                    margin: 0.5em 0;
                    color: var(--secondary-text-color);
                  }
                  .cv-content a {
                    color: #3b82f6;
                    text-decoration: none;
                  }
                  .cv-content a:hover {
                    text-decoration: underline;
                  }
                  .cv-content table {
                    border-collapse: collapse;
                    width: 100%;
                    margin: 0.5em 0;
                  }
                  .cv-content th, .cv-content td {
                    border: 1px solid var(--border-color);
                    padding: 8px;
                    text-align: left;
                  }
                  .cv-content th {
                    background-color: var(--header-bg);
                    font-weight: bold;
                  }
                `}</style>
                <div
                  className="cv-content"
                  style={{
                    color: "var(--text-color)",
                    lineHeight: "1.8",
                  }}
                >
                  <ReactMarkdown
                    components={{
                      h1: (props) => <HeaderRenderer level={1} {...props} />,
                      h2: (props) => <HeaderRenderer level={2} {...props} />,
                      h3: (props) => <HeaderRenderer level={3} {...props} />,
                      h4: (props) => <HeaderRenderer level={4} {...props} />,
                      h5: (props) => <HeaderRenderer level={5} {...props} />,
                      h6: (props) => <HeaderRenderer level={6} {...props} />,
                    }}
                  >
                    {cv}
                  </ReactMarkdown>
                </div>
              </>
            ) : (
              <div style={{ color: "var(--text-color)", opacity: 0.6, fontStyle: "italic" }}>
                No CV uploaded yet. Upload a file or click Edit to add your CV.
              </div>
            )}
          </div>
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

      <div style={{ marginTop: 28 }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: 12,
            flexWrap: "wrap",
            gap: 8,
          }}
        >
          <h3 style={{ margin: 0, color: "var(--text-color)" }}>Additional notes (with your CV)</h3>
          <div style={{ display: "flex", gap: 8 }}>
            <button
              type="button"
              onClick={addManualExtraRow}
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
              Add note
            </button>
            <button
              type="button"
              onClick={handleSaveExtraInfo}
              disabled={savingExtra}
              style={{
                padding: "8px 12px",
                border: "1px solid var(--border-color)",
                borderRadius: "4px",
                backgroundColor: "#3b82f6",
                color: "white",
                cursor: savingExtra ? "not-allowed" : "pointer",
                fontSize: "14px",
                opacity: savingExtra ? 0.6 : 1,
              }}
            >
              {savingExtra ? "Saving…" : "Save notes"}
            </button>
          </div>
        </div>
        <p style={{ color: "var(--secondary-text-color)", fontSize: "14px", marginBottom: 16, maxWidth: 720 }}>
          Text you add in feedback (missing context, instructions) and notes you add here are stored in your profile and
          appended to your CV when the app generates letters or checks accuracy, so models see them as part of your background.
        </p>
        {extraInfo.length === 0 ? (
          <div style={{ color: "var(--text-color)", opacity: 0.65, fontStyle: "italic" }}>
            No saved notes yet. They appear when you fill context in the draft feedback step, or when you add a note above.
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            {extraInfo.map((row, idx) => {
              const src = String(row.source || "manual");
              const lines = Array.isArray(row.context_lines) ? row.context_lines : [];
              return (
                <div
                  key={String(row.id || idx)}
                  style={{
                    padding: 16,
                    backgroundColor: "var(--bg-color)",
                    border: "1px solid var(--border-color)",
                    borderRadius: "4px",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
                    <span style={{ fontSize: "12px", color: "var(--secondary-text-color)" }}>
                      {src === "feedback" ? "From feedback" : "Manual"} · id {String(row.id || "").slice(0, 8)}…
                    </span>
                    <button
                      type="button"
                      onClick={() => removeExtraRow(idx)}
                      style={{
                        padding: "4px 8px",
                        fontSize: "12px",
                        border: "1px solid var(--border-color)",
                        borderRadius: "4px",
                        background: "var(--button-bg)",
                        cursor: "pointer",
                      }}
                    >
                      Remove
                    </button>
                  </div>
                  <label style={{ display: "block", fontSize: "12px", marginBottom: 4, color: "var(--text-color)" }}>
                    Category
                  </label>
                  <input
                    type="text"
                    value={String(row.category ?? "")}
                    onChange={(e) => updateExtraRow(idx, { category: e.target.value })}
                    style={{
                      width: "100%",
                      maxWidth: 480,
                      marginBottom: 8,
                      padding: 8,
                      borderRadius: 4,
                      border: "1px solid var(--border-color)",
                      background: "var(--bg-color)",
                      color: "var(--text-color)",
                    }}
                  />
                  <label style={{ display: "block", fontSize: "12px", marginBottom: 4, color: "var(--text-color)" }}>
                    Related feedback (optional)
                  </label>
                  <textarea
                    value={String(row.observation ?? "")}
                    onChange={(e) => updateExtraRow(idx, { observation: e.target.value })}
                    rows={2}
                    style={{
                      width: "100%",
                      marginBottom: 8,
                      padding: 8,
                      borderRadius: 4,
                      border: "1px solid var(--border-color)",
                      background: "var(--bg-color)",
                      color: "var(--text-color)",
                      resize: "vertical",
                    }}
                  />
                  <label style={{ display: "block", fontSize: "12px", marginBottom: 4, color: "var(--text-color)" }}>
                    Your context
                  </label>
                  <textarea
                    value={String(row.user_context ?? "")}
                    onChange={(e) => updateExtraRow(idx, { user_context: e.target.value })}
                    rows={3}
                    style={{
                      width: "100%",
                      marginBottom: 8,
                      padding: 8,
                      borderRadius: 4,
                      border: "1px solid var(--border-color)",
                      background: "var(--bg-color)",
                      color: "var(--text-color)",
                      resize: "vertical",
                    }}
                  />
                  <label style={{ display: "block", fontSize: "12px", marginBottom: 4, color: "var(--text-color)" }}>
                    Instructions
                  </label>
                  <input
                    type="text"
                    value={String(row.user_instructions ?? "")}
                    onChange={(e) => updateExtraRow(idx, { user_instructions: e.target.value })}
                    style={{
                      width: "100%",
                      maxWidth: 640,
                      marginBottom: 8,
                      padding: 8,
                      borderRadius: 4,
                      border: "1px solid var(--border-color)",
                      background: "var(--bg-color)",
                      color: "var(--text-color)",
                    }}
                  />
                  <label style={{ display: "block", fontSize: "12px", marginBottom: 4, color: "var(--text-color)" }}>
                    Context lines (one per line)
                  </label>
                  <textarea
                    value={lines.join("\n")}
                    onChange={(e) =>
                      updateExtraRow(idx, {
                        context_lines: e.target.value.split("\n"),
                      })
                    }
                    rows={3}
                    style={{
                      width: "100%",
                      marginBottom: 8,
                      padding: 8,
                      borderRadius: 4,
                      border: "1px solid var(--border-color)",
                      background: "var(--bg-color)",
                      color: "var(--text-color)",
                      resize: "vertical",
                      fontFamily: "monospace",
                      fontSize: "13px",
                    }}
                  />
                  <label style={{ display: "block", fontSize: "12px", marginBottom: 4, color: "var(--text-color)" }}>
                    Freeform note
                  </label>
                  <textarea
                    value={String(row.manual_text ?? "")}
                    onChange={(e) => updateExtraRow(idx, { manual_text: e.target.value })}
                    rows={2}
                    style={{
                      width: "100%",
                      padding: 8,
                      borderRadius: 4,
                      border: "1px solid var(--border-color)",
                      background: "var(--bg-color)",
                      color: "var(--text-color)",
                      resize: "vertical",
                    }}
                  />
                </div>
              );
            })}
          </div>
        )}
      </div>

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
