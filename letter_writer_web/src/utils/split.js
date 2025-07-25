import { v4 as uuidv4 } from "uuid";

export function splitIntoParagraphs(text, vendor) {
  if (!text) return [];
  // Split on blank lines (two or more line breaks with optional spaces)
  const rawParas = text.trim().split(/\n\s*\n/);
  return rawParas.map((t) => ({
    id: uuidv4(),
    vendor,
    text: t.trim(),
  }));
} 