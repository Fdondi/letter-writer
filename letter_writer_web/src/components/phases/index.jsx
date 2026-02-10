/**
 * Phase modules index - exports phase-specific functions by phase name
 *
 * Background search is handled during the initial phase (extraction or standalone),
 * so the phased flow starts directly with the draft.
 */
import * as draftPhase from "./draft";

export const phases = {
  draft: draftPhase,
};
