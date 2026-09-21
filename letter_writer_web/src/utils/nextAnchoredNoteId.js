/**
 * Next still-open anchored note after `dealtId`, in letter order (wraps).
 * @param {{ id: string, start?: number, faint?: boolean, unanchored?: boolean }[]} notes
 * @param {string | null} dealtId
 * @returns {string | null}
 */
export function nextAnchoredNoteId(notes, dealtId) {
  const anchored = (notes || []).filter((n) => !n.unanchored && n.start != null);
  const ordered = [...anchored].sort((a, b) => {
    const ds = (a.start ?? 0) - (b.start ?? 0);
    if (ds !== 0) return ds;
    return String(a.id).localeCompare(String(b.id));
  });
  if (!ordered.length) return null;
  const idx = ordered.findIndex((n) => n.id === dealtId);
  const start = idx >= 0 ? idx + 1 : 0;
  for (let i = 0; i < ordered.length; i++) {
    const n = ordered[(start + i) % ordered.length];
    if (!n.faint && n.id !== dealtId) return n.id;
  }
  return null;
}
