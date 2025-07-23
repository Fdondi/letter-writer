import React, { useState } from "react";

export default function LetterTabs({ letters }) {
  const [collapsed, setCollapsed] = useState([]); // vendor names collapsed
  const [finalLetter, setFinalLetter] = useState("");

  const toggleCollapse = (vendor) => {
    setCollapsed((prev) =>
      prev.includes(vendor) ? prev.filter((v) => v !== vendor) : [...prev, vendor]
    );
  };

  const visibleVendors = Object.keys(letters).filter((v) => !collapsed.includes(v));
  const collapsedVendors = Object.keys(letters).filter((v) => collapsed.includes(v));
  const totalVisible = visibleVendors.length + 1; // +1 for final letter

  return (
    <div style={{ 
      height: "calc(100vh - 200px)", 
      marginTop: 20,
      display: "flex",
      flexDirection: "column"
    }}>
      {collapsedVendors.length > 0 && (
        <select
          onChange={(e) => {
            if (e.target.value) toggleCollapse(e.target.value);
            e.target.value = "";
          }}
          style={{ marginBottom: 10 }}
        >
          <option value="">Restore collapsed...</option>
          {collapsedVendors.map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </select>
      )}
      <div style={{ 
        display: "flex", 
        gap: 10, 
        flex: 1,
        minHeight: 0 // Allow flex items to shrink
      }}>
        {visibleVendors.map((v) => (
          <LetterCard
            key={v}
            title={v}
            text={letters[v]}
            onCollapse={() => toggleCollapse(v)}
            width={`${100 / totalVisible}%`}
          />
        ))}
        <LetterCard
          title="Final Letter (editable)"
          text={finalLetter}
          editable
          onChange={setFinalLetter}
          width={`${100 / totalVisible}%`}
        />
      </div>
    </div>
  );
}

function LetterCard({ title, text, onCollapse, editable = false, onChange, width }) {
  return (
    <div
      style={{
        width,
        border: "1px solid #ccc",
        borderRadius: 4,
        padding: 10,
        position: "relative",
        background: "#fafafa",
        display: "flex",
        flexDirection: "column",
        minHeight: 0 // Allow content to shrink
      }}
    >
      <div style={{ 
        display: "flex", 
        justifyContent: "space-between", 
        alignItems: "center",
        marginBottom: 5
      }}>
        <strong>{title}</strong>
        {onCollapse && (
          <button
            onClick={onCollapse}
            style={{ 
              background: "none",
              border: "none",
              cursor: "pointer",
              fontSize: "16px",
              padding: "2px 6px"
            }}
            title="Hide letter"
          >
            ⊗
          </button>
        )}
      </div>
      <div style={{ flex: 1, minHeight: 0, overflow: "hidden" }}>
        {editable ? (
          <textarea
            value={text}
            onChange={(e) => onChange(e.target.value)}
            style={{ 
              width: "100%", 
              height: "100%", 
              resize: "none",
              border: "1px solid #ddd",
              borderRadius: 2,
              padding: 8,
              fontFamily: "monospace",
              fontSize: "12px"
            }}
          />
        ) : (
          <pre
            style={{
              whiteSpace: "pre-wrap",
              overflowY: "auto",
              height: "100%",
              margin: 0,
              fontFamily: "monospace",
              fontSize: "12px",
              padding: 8,
              background: "white",
              border: "1px solid #ddd",
              borderRadius: 2
            }}
          >
            {text}
          </pre>
        )}
      </div>
    </div>
  );
} 