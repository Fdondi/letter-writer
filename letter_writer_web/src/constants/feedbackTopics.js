/**
 * Agentic feedback topic registry — keep AGENTIC_TOPICS and FEEDBACK_TOPIC_LABELS
 * in sync with letter_writer/feedback_topics.py FEEDBACK_TOPICS (keys and labels).
 */
export const AGENTIC_TOPICS = [
  "instruction",
  "company_fit",
  "goal_fit",
  "precision",
  "user_fit",
  "human",
  "accuracy",
];

export const FEEDBACK_TOPIC_LABELS = {
  instruction: "Instruction",
  company_fit: "Company fit",
  goal_fit: "Goal fit",
  precision: "Precision",
  user_fit: "User fit",
  human: "Human",
  accuracy: "CV accuracy",
};

/** Note colors by topic (accuracy, precision, …). ALREADY_GOOD uses the same hue, drawn faint. */
export const TOPIC_NOTE_COLORS = {
  instruction: "#6366f1",
  company_fit: "#0d9488",
  goal_fit: "#2563eb",
  precision: "#d97706",
  user_fit: "#7c3aed",
  human: "#db2777",
  accuracy: "#dc2626",
};

export function feedbackTopicLabel(categoryKey) {
  const mapped = FEEDBACK_TOPIC_LABELS[categoryKey];
  if (mapped) return mapped;
  return String(categoryKey || "").replace(/_/g, " ").trim();
}

export function vendorNoteTitle(type, categoryKey) {
  const topic = feedbackTopicLabel(categoryKey);
  if (String(type || "").toUpperCase() === "ALREADY_GOOD") {
    return topic ? `Already good · ${topic}` : "Already good";
  }
  return topic || "Critique";
}

export function vendorNoteColor(categoryKey) {
  return TOPIC_NOTE_COLORS[categoryKey] || "#6b7280";
}
