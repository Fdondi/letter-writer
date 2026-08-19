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
