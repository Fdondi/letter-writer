import { normalizeCategoryItems, FEEDBACK_TYPES } from "./src/components/phases/feedbackItemUtils.js";

const raw = [
  { id: "1", observation: "test", type: FEEDBACK_TYPES.PLEASE_FIX },
  { id: "2", observation: "", type: FEEDBACK_TYPES.PLEASE_FIX }
];

console.log(JSON.stringify(normalizeCategoryItems(raw), null, 2));
