/**
 * Phase modules index - exports phase-specific functions by phase name
 */
import * as backgroundPhase from "./background";
import * as refinePhase from "./refine";

export const phases = {
  background: backgroundPhase,
  refine: refinePhase,
};
