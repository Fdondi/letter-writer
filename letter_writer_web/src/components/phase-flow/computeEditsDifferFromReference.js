/**
 * True if local `edits` differ from `reference` (server snapshot or post-approval baseline).
 * Mirrors VendorCard dirty detection: only keys present on `edits` are compared.
 */
export function computeEditsDifferFromReference(cardPhaseEdits, reference) {
  if (!reference || !cardPhaseEdits) return false;
  return Object.keys(cardPhaseEdits).some((key) => {
    const editValue = cardPhaseEdits[key];
    const dataValue = reference[key];

    if (editValue && typeof editValue === "object" && !Array.isArray(editValue)) {
      const dataObj = dataValue && typeof dataValue === "object" && !Array.isArray(dataValue) ? dataValue : {};
      const editKeys = Object.keys(editValue);
      const dataKeys = Object.keys(dataObj);
      if (editKeys.length === 0 && dataKeys.length === 0) return false;
      if (editKeys.length !== dataKeys.length) return true;
      return editKeys.some((k) => {
        const ev = editValue[k];
        const dv = dataObj[k];
        if (ev !== null && typeof ev === "object") {
          return JSON.stringify(ev) !== JSON.stringify(dv);
        }
        return ev !== dv;
      });
    }

    const editStr = (editValue ?? "").toString().trim();
    const dataStr = (dataValue ?? "").toString().trim();
    return editStr !== dataStr;
  });
}
