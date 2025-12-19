import React from "react";

export default function ModelSelector({ vendors, selected, onToggle, onSelectAll }) {
  const allSelected = selected.size === vendors.length;

  return (
    <div style={{ display: "flex", gap: 10, flexWrap: "wrap", color: 'var(--text-color)' }}>
      <label style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer' }}>
        <input
          type="checkbox"
          checked={allSelected}
          onChange={(e) => onSelectAll(e.target.checked)}
        />
        <strong>Select All</strong>
      </label>
      {vendors.map((v) => (
        <label key={v} style={{ textTransform: "capitalize", display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer' }}>
          <input
            type="checkbox"
            checked={selected.has(v)}
            onChange={(e) => onToggle(v, e.target.checked)}
          />
          {v}
        </label>
      ))}
    </div>
  );
} 