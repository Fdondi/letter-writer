export const VENDOR_COLUMN_WIDTH = 340;
/** Fixed viewport height per column — independent of sibling columns. */
export const VENDOR_COLUMN_HEIGHT = "calc(100dvh - 80px)";

export const cardStyle = {
  border: "1px solid #e5e7eb",
  borderRadius: 8,
  padding: 12,
  background: "#fafafa",
  display: "flex",
  flexDirection: "column",
  justifyContent: "flex-start",
  alignItems: "stretch",
  gap: 0,
  flex: `0 0 ${VENDOR_COLUMN_WIDTH}px`,
  width: VENDOR_COLUMN_WIDTH,
  minWidth: VENDOR_COLUMN_WIDTH,
  maxWidth: VENDOR_COLUMN_WIDTH,
  height: VENDOR_COLUMN_HEIGHT,
  minHeight: VENDOR_COLUMN_HEIGHT,
  maxHeight: VENDOR_COLUMN_HEIGHT,
  position: "relative",
  boxSizing: "border-box",
  overflow: "hidden",
};

export const cardHeaderStyle = {
  flex: "0 0 auto",
  display: "flex",
  flexDirection: "column",
  gap: 6,
  paddingBottom: 8,
  marginBottom: 8,
  borderBottom: "1px solid #e5e7eb",
  background: "#fafafa",
  position: "sticky",
  top: 0,
  zIndex: 2,
};

export const contentContainerStyle = {
  flex: 1,
  minHeight: 0,
  display: "flex",
  flexDirection: "column",
  gap: 8,
  overflowY: "auto",
  paddingRight: 2,
  paddingBottom: 8,
  boxSizing: "border-box",
};

export const iconButtonStyle = {
  flexShrink: 0,
  width: 26,
  height: 26,
  padding: 0,
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  border: "1px solid var(--border-color, #d1d5db)",
  borderRadius: 4,
  background: "var(--panel-bg, #fff)",
  color: "var(--text-color, #111827)",
  cursor: "pointer",
};
