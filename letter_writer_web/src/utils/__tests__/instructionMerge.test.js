import {
  applyAllUpstreamToChunks,
  applyChunkChoice,
  applyUpstreamChanges,
  buildMergeChunks,
  mergeChunksToText,
  splitInstructionLines,
} from "../instructionMerge";

describe("instructionMerge", () => {
  test("buildMergeChunks marks new upstream default-only hunks", () => {
    const baseline = "line one\nline two\nline three";
    const custom = "line one\nmy two\nline three";
    const defaultText = "line one\nline two updated\nline three\nline four";

    const chunks = buildMergeChunks({ baseline, custom, defaultText });
    const upstream = chunks.filter((c) => c.isNewUpstream);
    expect(upstream.length).toBeGreaterThan(0);
  });

  test("applyAllUpstreamToChunks merges non-conflicting edits", () => {
    const baseline = "a\nb\nc";
    const custom = "a custom\nb\nc";
    const defaultText = "a\nb upstream\nc";

    const chunks = buildMergeChunks({ baseline, custom, defaultText });
    const { chunks: merged, unresolved } = applyAllUpstreamToChunks(chunks, baseline);
    expect(unresolved).toHaveLength(0);
    expect(splitInstructionLines(mergeChunksToText(merged))).toEqual(["a custom", "b upstream", "c"]);
  });

  test("applyAllUpstreamToChunks leaves conflicts unresolved", () => {
    const baseline = "a\nb\nc";
    const custom = "a\nmine\nc";
    const defaultText = "a\ntheirs\nc";

    const chunks = buildMergeChunks({ baseline, custom, defaultText });
    const { unresolved } = applyAllUpstreamToChunks(chunks, baseline);
    expect(unresolved.length).toBeGreaterThan(0);
  });

  test("applyChunkChoice takes default for one hunk", () => {
    const baseline = "a\nb\nc";
    const custom = "a\nmine\nc";
    const defaultText = "a\ntheirs\nc";

    const chunks = buildMergeChunks({ baseline, custom, defaultText });
    const changed = chunks.find((c) => c.kind === "changed");
    expect(changed).toBeDefined();
    const next = applyChunkChoice(chunks, changed.id, "default");
    expect(mergeChunksToText(next)).toBe("a\ntheirs\nc");
  });

  test("apply upstream works without stored baseline (legacy custom)", () => {
    const custom = "old custom line\nkeep this";
    const defaultText = "new default intro\nkeep this\nextra line";

    const chunks = buildMergeChunks({ baseline: "", custom, defaultText });
    const { chunks: merged } = applyAllUpstreamToChunks(chunks, "");
    const text = mergeChunksToText(merged);
    expect(text).toContain("extra line");
    expect(text).toContain("keep this");
  });

  test("apply all applies default-only lines without baseline", () => {
    const custom = "my plan\nshort";
    const defaultText = "telegraphic plan\n~10 lines\nmore";

    const chunks = buildMergeChunks({ baseline: "", custom, defaultText });
    const { chunks: merged } = applyAllUpstreamToChunks(chunks, "");
    const result = mergeChunksToText(merged);
    expect(result).toContain("more");
  });
});
