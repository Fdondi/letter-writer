import { feedbackTopicLabel, vendorNoteTitle } from "../feedbackTopics";

describe("vendorNoteTitle", () => {
  test("please-fix notes are the topic only", () => {
    expect(vendorNoteTitle("PLEASE_FIX", "company_fit")).toBe("Company fit");
    expect(vendorNoteTitle("PLEASE_FIX", "precision")).toBe("Precision");
  });

  test("already-good notes keep the kind", () => {
    expect(vendorNoteTitle("ALREADY_GOOD", "human")).toBe("Already good · Human");
  });
});

describe("feedbackTopicLabel", () => {
  test("maps known keys", () => {
    expect(feedbackTopicLabel("company_fit")).toBe("Company fit");
    expect(feedbackTopicLabel("accuracy")).toBe("CV accuracy");
  });
});
