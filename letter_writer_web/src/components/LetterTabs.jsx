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

  return (
    <div style={{ marginTop: 20 }}>
      {collapsedVendors.length > 0 && (
        <select
          onChange={(e) => {
            if (e.target.value) toggleCollapse(e.target.value);
            e.target.value = "";
          }}
        >
          <option value="">Restore collapsed...</option>
          {collapsedVendors.map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </select>
      )}
      <div style={{ display: "flex", gap: 10, flexWrap: "nowrap", overflowX: "auto" }}>
        {visibleVendors.map((v) => (
          <LetterCard
            key={v}
            title={v}
            text={letters[v]}
            onCollapse={() => toggleCollapse(v)}
          />
        ))}
        <LetterCard
          title="Final Letter (editable)"
          text={finalLetter}
          editable
          onChange={setFinalLetter}
        />
      </div>
    </div>
  );
}

function LetterCard({ title, text, onCollapse, editable = false, onChange }) {
  return (
    <div
      style={{
        minWidth: 300,
        flex: "0 0 300px",
        border: "1px solid #ccc",
        borderRadius: 4,
        padding: 10,
        position: "relative",
        background: "#fafafa",
      }}
    >
      <strong>{title}</strong>
      {onCollapse && (
        <button
          onClick={onCollapse}
          style={{ position: "absolute", top: 5, right: 5 }}
        >
          ⤵︎
        </button>
      )}
      {editable ? (
        <textarea
          value={text}
          onChange={(e) => onChange(e.target.value)}
          style={{ width: "100%", height: 400, marginTop: 5 }}
        />
      ) : (
        <pre
          style={{
            whiteSpace: "pre-wrap",
            overflowY: "auto",
            height: 400,
            marginTop: 5,
          }}
        >
          {text}
        </pre>
      )}
    </div>
  );
} 