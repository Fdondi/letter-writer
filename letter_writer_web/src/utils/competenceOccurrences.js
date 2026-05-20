/**
 * Count occurrences of each competence string across vendor letter columns
 * (same paragraph source as LetterTabs columns: draft when toggled).
 */
export function countCompetenceOccurrences(
  vendorParagraphs,
  requirements,
  vendorDraftParagraphs,
  swapDraftForFinal
) {
  const counts = {};
  if (!Array.isArray(requirements)) return counts;

  requirements.forEach((req) => {
    const trimmed = (req ?? "").trim();
    if (trimmed) counts[trimmed] = 0;
  });

  const vendors = Object.keys(vendorParagraphs || {});
  const allText = vendors
    .flatMap((v) => {
      const useDraft =
        swapDraftForFinal?.[v] &&
        vendorDraftParagraphs &&
        Array.isArray(vendorDraftParagraphs[v]) &&
        vendorDraftParagraphs[v].length > 0;
      const paragraphs = useDraft
        ? vendorDraftParagraphs[v]
        : vendorParagraphs[v] || [];
      return Array.isArray(paragraphs) ? paragraphs : [];
    })
    .map((p) => p?.text ?? "")
    .join(" ");

  Object.keys(counts).forEach((requirement) => {
    if (!requirement) return;
    try {
      const escaped = requirement.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      const regex = new RegExp(`(?<![a-zA-Z0-9])(${escaped})(?![a-zA-Z0-9])`, "gi");
      counts[requirement] = (allText.match(regex) || []).length;
    } catch {
      counts[requirement] = 0;
    }
  });

  return counts;
}
