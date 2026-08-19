import React from "react";

export const planMarkdownComponents = {
  h1: ({ children }) => (
    <h1 style={{ fontSize: 15, fontWeight: 700, margin: "0 0 6px", color: "#111827" }}>{children}</h1>
  ),
  h2: ({ children }) => (
    <h2 style={{ fontSize: 14, fontWeight: 600, margin: "14px 0 4px", color: "#111827" }}>{children}</h2>
  ),
  h3: ({ children }) => (
    <h3 style={{ fontSize: 13, fontWeight: 600, margin: "10px 0 4px", color: "#374151" }}>{children}</h3>
  ),
  p: ({ children }) => <p style={{ margin: "4px 0" }}>{children}</p>,
  ul: ({ children }) => <ul style={{ margin: "4px 0 4px 18px", padding: 0 }}>{children}</ul>,
  ol: ({ children }) => <ol style={{ margin: "4px 0 4px 18px", padding: 0 }}>{children}</ol>,
  li: ({ children }) => <li style={{ margin: "2px 0" }}>{children}</li>,
  strong: ({ children }) => <strong style={{ fontWeight: 600 }}>{children}</strong>,
};
