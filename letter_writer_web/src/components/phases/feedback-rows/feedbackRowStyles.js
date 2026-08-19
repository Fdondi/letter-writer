export const ICON_BTN_STYLE = {
  fontSize: 14,
  lineHeight: 1,
  padding: "2px 6px",
  border: "1px solid #d1d5db",
  background: "#fff",
  borderRadius: 4,
  cursor: "pointer",
  color: "#374151",
};

export function iconBtnStyle(disabled) {
  return {
    ...ICON_BTN_STYLE,
    cursor: disabled ? "not-allowed" : "pointer",
  };
}
