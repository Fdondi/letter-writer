// node --test extensions/job-capture/  (no dependencies)
// The keys and capture rules must match letter_writer/opportunity_store.py and the phone app:
// both sides are verified against the shared fixture letter_writer/tests/fixtures/opportunity_keys.json.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const P = require("./pipeline.js");

const FIXTURE = JSON.parse(
  readFileSync(path.join(here, "..", "..", "letter_writer", "tests", "fixtures", "opportunity_keys.json"), "utf8"),
);

const JOB_URL = "https://www.jobs.ch/de/stellenangebote/detail/6ef0e053-1d7a-45bc-b9a7-a32dd1dfb5f7/?source=jobmail&utm_medium=email";
const JOB_KEY = "jobs.ch:6ef0e053-1d7a-45bc-b9a7-a32dd1dfb5f7";

test("canonical keys, clean urls and sources match the shared fixture", () => {
  assert.ok(FIXTURE.canonical_keys.length >= 15, "fixture should cover the key rules");
  for (const entry of FIXTURE.canonical_keys) {
    assert.equal(P.canonicalKey(entry.url), entry.canonical_key, `key for ${entry.url}`);
    assert.equal(P.cleanUrl(entry.url), entry.clean_url, `clean url for ${entry.url}`);
    assert.equal(P.sourceOf(entry.canonical_key), entry.source, `source for ${entry.canonical_key}`);
  }
});

test("text keys match the shared fixture", async () => {
  for (const entry of FIXTURE.text_keys) {
    assert.equal(await P.textKey(entry.text), entry.text_key, `text key for ${JSON.stringify(entry.text)}`);
  }
});

test("document ids match the shared fixture", async () => {
  for (const entry of FIXTURE.document_ids) {
    assert.equal(await P.documentId(FIXTURE.user_id, entry.canonical_key), entry.document_id);
  }
});

test("capture payload truncates text and drops oversized html", () => {
  const at = new Date("2026-10-26T12:00:00.000Z");
  assert.deepEqual(P.capturePayload("  hello  ", "extension", "<p>x</p>", at), {
    text: "hello",
    html: "<p>x</p>",
    captured_at: at,
    via: "extension",
  });
  const big = P.capturePayload("x".repeat(100001), "extension", "y".repeat(300001), at);
  assert.equal(big.text.length, P.MAX_CAPTURE_TEXT_CHARS);
  assert.equal(big.html, null);
  const edge = P.capturePayload("text", "extension", "y".repeat(300000), at);
  assert.equal(edge.html.length, 300000);
});

test("planCapture: a new job with text is captured, without text approved", async () => {
  const now = new Date();
  const withText = await P.planCapture({
    userId: "u1",
    key: JOB_KEY,
    oppId: "abc",
    url: JOB_URL,
    title: " Job ",
    text: "Posting",
    html: "<p>Posting</p>",
    via: "extension",
    existing: null,
    now,
  });
  assert.equal(withText.action, "create");
  assert.equal(withText.status, "captured");
  assert.equal(withText.fields.status, "captured");
  assert.equal(withText.fields.url, "https://www.jobs.ch/de/stellenangebote/detail/6ef0e053-1d7a-45bc-b9a7-a32dd1dfb5f7");
  assert.equal(withText.fields.canonical_key, JOB_KEY);
  assert.equal(withText.fields.source, "jobs.ch");
  assert.equal(withText.fields.user_id, "u1");
  assert.equal(withText.fields.title, "Job");
  assert.equal(withText.fields.capture.via, "extension");
  assert.equal(withText.fields.capture.text, "Posting");
  assert.equal(withText.message, "Saved. The desktop drafts it on its next run.");

  const linkOnly = await P.planCapture({
    userId: "u1",
    key: "url:https://example.com/job",
    oppId: "abc",
    url: "https://example.com/job",
    title: "",
    text: "",
    html: "",
    via: "extension",
    existing: null,
    now,
  });
  assert.equal(linkOnly.action, "create");
  assert.equal(linkOnly.status, "approved");
  assert.equal(linkOnly.fields.capture, null);
  assert.equal(linkOnly.message, "Link saved. Paste the posting text when you have it.");
});

test("planCapture: existing jobs follow the phone's rules", async () => {
  const now = new Date();
  const base = { userId: "u1", key: "k", oppId: "abc", url: "", title: "", text: "Posting", html: "", via: "extension", now };

  const drafting = await P.planCapture({ ...base, existing: { status: "drafting" } });
  assert.equal(drafting.action, "skip");
  assert.equal(drafting.message, "The desktop is drafting this job right now.");

  const ready = await P.planCapture({ ...base, existing: { status: "ready" } });
  assert.equal(ready.action, "skip");
  assert.equal(ready.message, "Drafts for this job are already ready.");

  const done = await P.planCapture({ ...base, existing: { status: "done" } });
  assert.equal(done.action, "skip");
  assert.equal(done.message, "This job is already done.");

  const applied = await P.planCapture({ ...base, existing: { status: "applied" } });
  assert.equal(applied.action, "skip");
  assert.equal(applied.message, "This job is already done.");

  // a link for a proposed or skipped job approves it
  for (const status of ["proposed", "skipped"]) {
    const approved = await P.planCapture({ ...base, url: "https://example.com/job/1", text: "", existing: { status } });
    assert.equal(approved.action, "update");
    assert.equal(approved.updateFields.status, "approved");
    assert.deepEqual(Object.keys(approved.updateFields).sort(), ["skip_reason", "status", "updated_at"]);
    assert.equal(approved.message, "Approved. Paste the posting text when you have it.");
  }

  // a link for a job already in the pipeline changes nothing
  const inPipeline = await P.planCapture({ ...base, url: "https://example.com/job/1", text: "", existing: { status: "captured" } });
  assert.equal(inPipeline.action, "skip");
  assert.equal(inPipeline.message, "This job is already in the pipeline.");

  // text on an approved job attaches it and queues it; the url fills only when empty
  const attached = await P.planCapture({
    ...base,
    url: "https://example.com/job?utm_source=x",
    existing: { status: "approved", url: "" },
  });
  assert.equal(attached.action, "update");
  assert.equal(attached.status, "captured");
  assert.equal(attached.updateFields.status, "captured");
  assert.equal(attached.updateFields.url, "https://example.com/job");
  assert.equal(attached.updateFields.capture.text, "Posting");
  assert.equal(attached.message, "Posting text attached. The desktop drafts it on its next run.");

  const replaced = await P.planCapture({ ...base, existing: { status: "captured", url: "https://example.com/job" } });
  assert.equal(replaced.updateFields.url, undefined);
  assert.equal(replaced.message, "Posting text replaced. The desktop drafts it on its next run.");
});

test("planCapture needs a link or text", async () => {
  await assert.rejects(
    P.planCapture({ userId: "u1", key: "k", oppId: "abc", url: "", title: "", text: "  ", html: "", via: "extension", existing: null, now: new Date() }),
    /Paste the job text or a link first/,
  );
});

test("queueCapture writes through the client with the fixture-derived document id", async () => {
  const calls = [];
  const client = {
    getDocument: async (path) => {
      calls.push(["get", path]);
      return null;
    },
    createIfAbsent: async (path, fields) => {
      calls.push(["create", path, fields.status]);
    },
    update: async (path, fields) => {
      calls.push(["update", path, fields.status]);
    },
  };
  const out = await P.queueCapture(client, {
    userId: "u1",
    url: JOB_URL,
    title: "Job",
    text: "Posting",
    html: "<p>x</p>",
    via: "extension",
  });
  assert.equal(out.opportunity_status, "captured");
  assert.equal(out.message, "Saved. The desktop drafts it on its next run.");
  const expectedId = await P.documentId("u1", JOB_KEY);
  assert.deepEqual(calls, [
    ["get", `opportunities/${expectedId}`],
    ["create", `opportunities/${expectedId}`, "captured"],
  ]);
});

test("queueCapture: a lost create race re-reads and follows the new state", async () => {
  let reads = 0;
  const client = {
    getDocument: async () => (++reads === 1 ? null : { status: "drafting" }),
    createIfAbsent: async () => {
      const e = new Error("already exists");
      e.code = "ALREADY_EXISTS";
      throw e;
    },
    update: async () => {
      throw new Error("update should not be reached");
    },
  };
  const out = await P.queueCapture(client, { userId: "u1", url: JOB_URL, title: "", text: "Posting", html: "", via: "extension" });
  assert.equal(reads, 2);
  assert.equal(out.opportunity_status, "drafting");
  assert.equal(out.message, "The desktop is drafting this job right now.");
});

test("queueCapture: a rules rejection while drafting is reported, not retried", async () => {
  let updates = 0;
  const client = {
    getDocument: async () => ({ status: "approved", url: "" }),
    createIfAbsent: async () => {
      throw new Error("create should not be reached");
    },
    update: async () => {
      updates++;
      const e = new Error("Missing or insufficient permissions.");
      e.code = "PERMISSION_DENIED";
      throw e;
    },
  };
  const out = await P.queueCapture(client, { userId: "u1", url: JOB_URL, title: "", text: "Posting", html: "", via: "extension" });
  assert.equal(updates, 1);
  assert.equal(out.opportunity_status, "drafting");
  assert.equal(out.message, "The desktop is drafting this job right now.");
});
