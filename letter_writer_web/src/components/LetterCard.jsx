import React from "react";

export default function LetterCard({ title, text, loading = false, error = null, onRetry, onCollapse, editable = false, onChange, width }) {
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
            👁️‍🗨️
          </button>
        )}
      </div>
      <div style={{ flex: 1, minHeight: 0, overflow: "hidden" }}>
        {loading && !text && !error ? (
          <div style={{display:"flex",alignItems:"center",justifyContent:"center",height:"100%"}}>
            <div className="spinner" />
          </div>
        ) : error && !text ? (
          <div style={{padding:8,color:"red",fontSize:12}}>
            {error}
            {onRetry && (
              <button onClick={onRetry} style={{marginTop:5}}>Retry</button>
            )}
          </div>
        ) : editable ? (
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