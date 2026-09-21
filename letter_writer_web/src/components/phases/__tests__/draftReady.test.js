import { computeReadyForApproval } from "../draft";
import { FEEDBACK_TYPES } from "../feedbackItemUtils";

describe("draft computeReadyForApproval", () => {
  const base = {
    isLoading: false,
    approved: false,
    thisPhaseDirty: false,
    feedbackOverrides: {},
    cardPhaseEdits: {},
    cardPhaseData: {},
  };

  test("blocks while a whole-letter PLEASE_FIX is unapproved", () => {
    const ready = computeReadyForApproval({
      ...base,
      feedbackKeys: ["accuracy", "precision"],
      feedbackItemApprovals: { fix1: true },
      feedback: {
        precision: [
          {
            id: "fix1",
            observation: "Name the stack.",
            type: FEEDBACK_TYPES.PLEASE_FIX,
            quote: "payment systems",
          },
        ],
        accuracy: [
          {
            id: "whole1",
            observation: "The letter as a whole stays short enough.",
            type: FEEDBACK_TYPES.PLEASE_FIX,
            quote: "",
          },
        ],
      },
    });
    expect(ready).toBe(false);
  });

  test("allows approval after whole-letter PLEASE_FIX is approved", () => {
    const ready = computeReadyForApproval({
      ...base,
      feedbackKeys: ["accuracy"],
      feedbackItemApprovals: { whole1: true },
      feedback: {
        accuracy: [
          {
            id: "whole1",
            observation: "The letter as a whole stays short enough.",
            type: FEEDBACK_TYPES.PLEASE_FIX,
            quote: "",
          },
        ],
      },
    });
    expect(ready).toBe(true);
  });
});
