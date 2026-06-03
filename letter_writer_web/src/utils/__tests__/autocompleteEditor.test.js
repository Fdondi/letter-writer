import {
  acceptSuggestion,
  assignShortcutLetters,
  resolveShortcutMap,
  updateShortcutLetter,
  buildAutocompleteDraftPrefix,
  buildGroupedModels,
  defaultCycleModels,
  formatModelKey,
  letterForCycleModel,
  normalizeShortcutMap,
  normalizeStoredModels,
  parseCtrlLetterKey,
  parseModelKey,
  readSessionCycleModels,
  sectionsToBodyText,
  sectionsToProposalText,
  buildAutocompletePlanAiLetter,
  writeSessionCycleModels,
  cycleModelsEqual,
  shouldAcceptOnSpace,
  shouldHandleCtrlLetterShortcut,
  suggestionAlreadyAtCursor,
  resolveCompletionModel,
  nextCycleIndex,
  createAutocompleteSuggestionHistory,
  splitSuggestionAcceptance,
  getPredefinedSectionIndices,
  isPredefinedAutocompleteSection,
  DEFAULT_AUTOCOMPLETE_SECTIONS,
  sliceNextAutocompleteChunk,
  shouldExtendAutocompleteCache,
  isSectionProposalStale,
  canUseProposalAutocompleteBuffer,
  shouldUseCompletionModelForSection,
  buildSectionProposalAutocompleteBuffer,
  PROPOSAL_AUTOCOMPLETE_CACHE_SOURCE,
  isProposalAutocompleteCache,
} from "../autocompleteEditor";

describe("sliceNextAutocompleteChunk", () => {
  test("returns first chunk and advances offset", () => {
    const raw = "one two three. four five";
    const { chunk, newOffset, hasMore } = sliceNextAutocompleteChunk(raw, 0, {
      maxWords: 3,
      stopOnPeriod: true,
    });
    expect(chunk).toBe("one two three.");
    expect(newOffset).toBeGreaterThan(0);
    expect(hasMore).toBe(true);
  });

  test("extend threshold at 80%", () => {
    expect(shouldExtendAutocompleteCache(8, 10)).toBe(true);
    expect(shouldExtendAutocompleteCache(7, 10)).toBe(false);
  });
});

describe("proposal autocomplete buffer", () => {
  test("returns full proposal when body empty at cursor", () => {
    expect(
      buildSectionProposalAutocompleteBuffer(
        { proposal: "Dear team, I apply.", proposalSourceBody: "", body: "" },
        0
      )
    ).toBe("Dear team, I apply.");
  });

  test("returns suffix after aligned prefix", () => {
    expect(
      buildSectionProposalAutocompleteBuffer(
        {
          proposal: "Dear team, I apply.",
          proposalSourceBody: "Dear ",
          body: "Dear ",
        },
        5
      )
    ).toBe("team, I apply.");
  });

  test("returns empty when stale", () => {
    expect(
      buildSectionProposalAutocompleteBuffer(
        {
          proposal: "Full text",
          proposalSourceBody: "Old",
          body: "Edited",
        },
        0
      )
    ).toBe("");
    expect(
      canUseProposalAutocompleteBuffer({
        proposal: "x",
        proposalSourceBody: "a",
        body: "b",
      })
    ).toBe(false);
    expect(
      shouldUseCompletionModelForSection({
        proposal: "x",
        proposalSourceBody: "a",
        body: "b",
      })
    ).toBe(true);
  });

  test("completion model when no proposal", () => {
    expect(shouldUseCompletionModelForSection({ proposal: "" })).toBe(true);
    expect(
      shouldUseCompletionModelForSection({
        proposal: "Guide",
        proposalSourceBody: "Hi",
        body: "Hi",
      })
    ).toBe(false);
  });

  test("proposal cache source marker", () => {
    expect(isProposalAutocompleteCache({ modelKey: PROPOSAL_AUTOCOMPLETE_CACHE_SOURCE })).toBe(
      true
    );
    expect(isProposalAutocompleteCache({ modelKey: "openai/gpt-4" })).toBe(false);
  });
});

describe("isSectionProposalStale", () => {
  test("detects body drift from proposal source", () => {
    expect(
      isSectionProposalStale({
        proposal: "Guide text",
        proposalSourceBody: "Hello",
        body: "Hello world",
      })
    ).toBe(true);
    expect(
      isSectionProposalStale({
        proposal: "Guide",
        proposalSourceBody: "Hi",
        body: "Hi",
      })
    ).toBe(false);
  });
});

describe("acceptSuggestion", () => {
  test("inserts suggestion and trailing space", () => {
    const { text, cursor } = acceptSuggestion("Hello ", 6, "world");
    expect(text).toBe("Hello world ");
    expect(cursor).toBe(12);
  });

  test("does not double space if suggestion ends with space", () => {
    const { text } = acceptSuggestion("Hi ", 3, "there ");
    expect(text).toBe("Hi there ");
  });

  test("returns inserted text for history", () => {
    const { inserted } = acceptSuggestion("A ", 2, "B");
    expect(inserted).toBe("B ");
  });
});

describe("splitSuggestionAcceptance", () => {
  test("full accept has empty rejected", () => {
    expect(splitSuggestionAcceptance("hello world", "hello world")).toEqual({
      accepted: "hello world",
      rejected: [],
    });
  });

  test("full reject records suggestion in rejected", () => {
    expect(splitSuggestionAcceptance("hello world", "")).toEqual({
      accepted: "",
      rejected: ["hello world"],
    });
  });

  test("partial accept splits remainder into rejected", () => {
    expect(splitSuggestionAcceptance("hello world", "hello ")).toEqual({
      accepted: "hello ",
      rejected: ["world"],
    });
  });
});

describe("createAutocompleteSuggestionHistory", () => {
  test("records incremental chunks with letter text at request time", () => {
    const hist = createAutocompleteSuggestionHistory();
    hist.setFixedContext("CV and job context");
    hist.startPending({ text: "Dear team,", suggestion: "I am interested.", model: "openai/gpt-4" });
    hist.acceptPending("I am interested. ");
    hist.startPending({
      text: "Dear team, I am interested. ",
      suggestion: "Your mission aligns.",
      model: "openai/gpt-4",
    });
    hist.acceptPending("Your mission aligns. ");
    expect(hist.finalizeForSave()).toEqual({
      fixed_context: "CV and job context",
      chunks: [
        {
          text: "Dear team,",
          accepted: "I am interested. ",
          rejected: [],
          model: "openai/gpt-4",
          cost: null,
        },
        {
          text: "Dear team, I am interested. ",
          accepted: "Your mission aligns. ",
          rejected: [],
          model: "openai/gpt-4",
          cost: null,
        },
      ],
    });
  });

  test("rejected suggestion when superseded without accept", () => {
    const hist = createAutocompleteSuggestionHistory();
    hist.startPending({ text: "Hi", suggestion: "first", model: "m1" });
    hist.startPending({ text: "Hi", suggestion: "second", model: "m2" });
    hist.acceptPending("second ");
    const saved = hist.finalizeForSave();
    expect(saved.chunks).toHaveLength(2);
    expect(saved.chunks[0]).toMatchObject({
      text: "Hi",
      accepted: "",
      rejected: ["first"],
    });
  });
});

describe("suggestionAlreadyAtCursor", () => {
  test("detects text already at cursor", () => {
    expect(suggestionAlreadyAtCursor("Hello world ", 12, "world")).toBe(false);
    expect(suggestionAlreadyAtCursor("Hello world ", 6, "world")).toBe(true);
    expect(suggestionAlreadyAtCursor("Hello world ", 6, "world extra")).toBe(false);
  });
});

describe("resolveCompletionModel", () => {
  test("prefers completionModel over modelUsed and cycle fallback", () => {
    expect(
      resolveCompletionModel("gemini/gemini-2.5-flash-lite", "grok/x", ["openai/y"])
    ).toBe("gemini/gemini-2.5-flash-lite");
  });
});

describe("shouldAcceptOnSpace", () => {
  test("accepts when suggestion present and shift not held", () => {
    expect(shouldAcceptOnSpace("foo", false)).toBe(true);
    expect(shouldAcceptOnSpace("foo", true)).toBe(false);
    expect(shouldAcceptOnSpace("", false)).toBe(false);
  });
});

describe("parseCtrlLetterKey", () => {
  test("returns letter for ctrl+key", () => {
    expect(parseCtrlLetterKey({ ctrlKey: true, key: "g", altKey: false, metaKey: false })).toBe("G");
  });

  test("returns null without ctrl", () => {
    expect(parseCtrlLetterKey({ ctrlKey: false, key: "g", altKey: false, metaKey: false })).toBe(null);
  });

  test("returns null when shift+letter (old shortcut)", () => {
    expect(
      parseCtrlLetterKey({ ctrlKey: false, shiftKey: true, key: "g", altKey: false, metaKey: false })
    ).toBe(null);
  });
});

describe("shouldHandleCtrlLetterShortcut", () => {
  test("works without an active suggestion", () => {
    const ctrlG = { ctrlKey: true, key: "g", altKey: false, metaKey: false };
    expect(shouldHandleCtrlLetterShortcut(ctrlG)).toBe(true);
    expect(shouldHandleCtrlLetterShortcut({ ...ctrlG, ctrlKey: false })).toBe(false);
  });
});

describe("model key helpers", () => {
  test("parseModelKey splits vendor and model", () => {
    expect(parseModelKey("openai/gpt-realtime-mini")).toEqual({
      vendor: "openai",
      modelId: "gpt-realtime-mini",
      reasoningEffort: "",
      composite: "openai/gpt-realtime-mini",
    });
  });

  test("parseModelKey splits reasoning effort suffix", () => {
    expect(parseModelKey("openai/gpt-5.5@high")).toEqual({
      vendor: "openai",
      modelId: "gpt-5.5",
      reasoningEffort: "high",
      composite: "openai/gpt-5.5@high",
    });
  });

  test("formatModelKey omits none effort suffix", () => {
    expect(formatModelKey("openai", "gpt-5.5", "none")).toBe("openai/gpt-5.5");
    expect(formatModelKey("openai", "gpt-5.5", "high")).toBe("openai/gpt-5.5@high");
  });

  test("normalizeStoredModels expands vendor-only entries", () => {
    const roleDefaults = { openai: "openai/gpt-realtime-mini", gemini: "gemini/gemini-2.5-flash-lite" };
    expect(normalizeStoredModels(["openai", "gemini/gemini-2.5-flash-lite"], roleDefaults)).toEqual([
      "openai/gpt-realtime-mini",
      "gemini/gemini-2.5-flash-lite",
    ]);
  });

  test("normalizeShortcutMap resolves vendor-only values", () => {
    const roleDefaults = { gemini: "gemini/gemini-2.5-flash-lite" };
    expect(normalizeShortcutMap({ G: "gemini" }, roleDefaults)).toEqual({
      G: "gemini/gemini-2.5-flash-lite",
    });
  });

  test("buildGroupedModels collects vendor keys", () => {
    const { grouped, vendors } = buildGroupedModels({
      OpenAI: [{ id: "gpt-realtime-mini", name: "Realtime Mini", vendor_key: "openai" }],
    });
    expect(vendors).toEqual(["openai"]);
    expect(grouped.openai[0].composite).toBe("openai/gpt-realtime-mini");
  });

  test("formatModelKey builds composite id", () => {
    expect(formatModelKey("openai", "gpt-realtime-mini")).toBe("openai/gpt-realtime-mini");
  });

  test("defaultCycleModels returns role defaults", () => {
    expect(defaultCycleModels({ a: "a/m1", b: "b/m2" })).toEqual(["a/m1", "b/m2"]);
  });
});

describe("assignShortcutLetters", () => {
  test("uses vendor initial letter", () => {
    expect(
      assignShortcutLetters(["openai/gpt-realtime-mini", "gemini/gemini-2.5-flash-lite"])
    ).toEqual({
      O: "openai/gpt-realtime-mini",
      G: "gemini/gemini-2.5-flash-lite",
    });
  });

  test("increments when initial is taken", () => {
    expect(
      assignShortcutLetters(["gemini/gemini-2.5-flash-lite", "grok/grok-4-1-fast-non-reasoning"])
    ).toEqual({
      G: "gemini/gemini-2.5-flash-lite",
      H: "grok/grok-4-1-fast-non-reasoning",
    });
  });

  test("letterForCycleModel returns assigned letter from map", () => {
    const map = assignShortcutLetters([
      "openai/gpt-realtime-mini",
      "gemini/gemini-2.5-flash-lite",
    ]);
    expect(letterForCycleModel("gemini/gemini-2.5-flash-lite", map)).toBe("G");
  });
});

describe("resolveShortcutMap", () => {
  const roleDefaults = {
    openai: "openai/gpt-realtime-mini",
    gemini: "gemini/gemini-2.5-flash-lite",
  };
  const cycle = ["openai/gpt-realtime-mini", "gemini/gemini-2.5-flash-lite"];

  test("uses vendor initial when no stored map", () => {
    expect(resolveShortcutMap(cycle, {}, roleDefaults)).toEqual({
      O: "openai/gpt-realtime-mini",
      G: "gemini/gemini-2.5-flash-lite",
    });
  });

  test("honors stored letter overrides", () => {
    expect(resolveShortcutMap(cycle, { M: "gemini/gemini-2.5-flash-lite" }, roleDefaults)).toEqual({
      O: "openai/gpt-realtime-mini",
      M: "gemini/gemini-2.5-flash-lite",
    });
  });
});

describe("updateShortcutLetter", () => {
  test("swaps letters when target is taken", () => {
    const map = { O: "openai/m1", G: "gemini/m2" };
    expect(updateShortcutLetter(map, "gemini/m2", "O")).toEqual({
      G: "openai/m1",
      O: "gemini/m2",
    });
  });
});

describe("scoped autocomplete draft storage", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  test("readStoredAutocompleteSections ignores draft for a different job", () => {
    const {
      buildAutocompleteDraftScope,
      readStoredAutocompleteSections,
      writeStoredAutocompleteSections,
    } = require("../autocompleteEditor");
    const scopeA = buildAutocompleteDraftScope({
      companyName: "Acme",
      jobTitle: "Engineer",
      jobText: "Job A",
    });
    const scopeB = buildAutocompleteDraftScope({
      companyName: "Other Co",
      jobTitle: "Engineer",
      jobText: "Job B",
    });
    writeStoredAutocompleteSections(
      [{ id: "x", title: "T", description: "", body: "Old letter", plan: "" }],
      scopeA
    );
    const forB = readStoredAutocompleteSections(scopeB);
    expect(sectionsToBodyText(forB)).toBe("");
  });

  test("readStoredAutocompleteSections restores draft for matching job", () => {
    const {
      buildAutocompleteDraftScope,
      readStoredAutocompleteSections,
      writeStoredAutocompleteSections,
    } = require("../autocompleteEditor");
    const scope = buildAutocompleteDraftScope({
      companyName: "Acme",
      jobTitle: "Engineer",
      jobText: "Job A",
    });
    writeStoredAutocompleteSections(
      [{ id: "x", title: "T", description: "", body: "Saved draft", plan: "" }],
      scope
    );
    const restored = readStoredAutocompleteSections(scope);
    expect(sectionsToBodyText(restored)).toBe("Saved draft");
  });
});

describe("session cycle storage", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  test("writeSessionCycleModels round-trips", () => {
    writeSessionCycleModels(["openai/gpt-realtime-mini"]);
    expect(readSessionCycleModels()).toEqual(["openai/gpt-realtime-mini"]);
  });

  test("cycleModelsEqual compares ordered lists", () => {
    expect(cycleModelsEqual(["a/m1"], ["a/m1"])).toBe(true);
    expect(cycleModelsEqual(["a/m1"], ["b/m2"])).toBe(false);
  });

  test("clearAutocompleteFlowCache removes session and local draft keys", () => {
    const {
      clearAutocompleteFlowCache,
      writeSessionCycleModels,
      writeSessionPlanModel,
      writeStoredAutocompleteSections,
      readSessionCycleModels,
      readSessionPlanModel,
      AUTOCOMPLETE_SECTIONS_KEY,
    } = require("../autocompleteEditor");
    writeSessionCycleModels(["openai/gpt-realtime-mini"]);
    writeSessionPlanModel("openai/gpt-realtime-mini");
    writeStoredAutocompleteSections(
      [{ id: "x", title: "T", description: "", body: "Hi", plan: "" }],
      "test-scope"
    );
    clearAutocompleteFlowCache();
    expect(readSessionCycleModels()).toBeNull();
    expect(readSessionPlanModel()).toBeNull();
    expect(localStorage.getItem(AUTOCOMPLETE_SECTIONS_KEY)).toBeNull();
  });
});

describe("nextCycleIndex", () => {
  test("wraps around", () => {
    expect(nextCycleIndex(2, 3)).toBe(0);
    expect(nextCycleIndex(0, 3)).toBe(1);
  });
});

describe("predefined autocomplete sections", () => {
  test("recognizes default section ids", () => {
    expect(isPredefinedAutocompleteSection(DEFAULT_AUTOCOMPLETE_SECTIONS[0])).toBe(true);
    expect(
      isPredefinedAutocompleteSection({ id: "custom", title: "X", description: "", body: "" })
    ).toBe(false);
  });

  test("getPredefinedSectionIndices returns only built-in sections", () => {
    const mixed = [
      ...DEFAULT_AUTOCOMPLETE_SECTIONS,
      { id: "extra", title: "Extra", description: "", body: "" },
    ];
    expect(getPredefinedSectionIndices(mixed)).toEqual([0, 1, 2, 3]);
    expect(getPredefinedSectionIndices([{ id: "extra", title: "X", description: "", body: "" }])).toEqual(
      []
    );
  });
});

describe("sectioned autocomplete draft", () => {
  const sections = [
    { title: "You are great", description: "Why them", body: "Dear team," },
    { title: "I am great", description: "Why me", body: "I built systems" },
    { title: "Together", description: "Fit", body: "Future" },
  ];

  test("buildAutocompleteDraftPrefix includes partial active section", () => {
    const prefix = buildAutocompleteDraftPrefix(sections, 1, 3);
    expect(prefix).toContain("Please continue:");
    expect(prefix).toContain("# You are great");
    expect(prefix).toContain("Dear team,");
    expect(prefix).toContain("I b");
    expect(prefix).not.toContain("built");
    expect(prefix).not.toContain("Together");
  });

  test("sectionsToProposalText joins proposals only", () => {
    const sections = [
      { proposal: "Dear team," },
      { proposal: "" },
      { proposal: "I am a strong fit." },
    ];
    expect(sectionsToProposalText(sections)).toBe("Dear team,\n\nI am a strong fit.");
  });

  test("buildAutocompletePlanAiLetter uses plan model composite", () => {
    const entry = buildAutocompletePlanAiLetter(
      "openai/gpt-4.1-mini",
      "Full draft letter.",
      0.02
    );
    expect(entry).toMatchObject({
      vendor: "openai",
      model: "openai/gpt-4.1-mini",
      text: "Full draft letter.",
      cost: 0.02,
    });
  });

  test("sectionsToBodyText joins bodies only", () => {
    expect(sectionsToBodyText(sections)).toBe(
      "Dear team,\n\nI built systems\n\nFuture"
    );
  });
});
