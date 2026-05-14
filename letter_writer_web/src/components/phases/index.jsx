/**
 * Phase modules index - exports phase-specific functions by phase name
 *
 * Vendor flow: plan (strategic outline) → draft (letter + feedback) → assembly via refine.
 */
import * as planPhase from "./plan";
import * as draftPhase from "./draft";

export const phases = {
  plan: planPhase,
  draft: draftPhase,
};
