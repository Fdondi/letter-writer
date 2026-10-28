// The browser extension's direct-Firestore queue path (extensions/job-capture/pipeline.js +
// firestore.js), run against the emulator with the real security rules. The extension talks
// plain REST with a Google-linked Firebase ID token; here the token is a mock JWT in the exact
// format the Firestore emulator accepts (see createMockUserToken in @firebase/util), with the
// same claims the rules read: firebase.identities['google.com'][0] == user_id.
//
// The tests drive the real "letter" database (firebase/firebase.json) over REST. Seeding uses
// the emulator's "owner" token; the Firestore SDK's settings({databaseId}) is ignored in
// firebase v11, so SDK writes would land in (default) instead — see rules.test.mjs, which is
// self-consistent on (default) but never touches "letter".
//   scripts/firebase/test_rules.sh
import { after, before, beforeEach, describe, test } from "node:test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import { initializeTestEnvironment } from "@firebase/rules-unit-testing";

const require = createRequire(import.meta.url);
const LW_FIRESTORE = require("../../extensions/job-capture/firestore.js");
const LW_PIPELINE = require("../../extensions/job-capture/pipeline.js");

const RULES = readFileSync(fileURLToPath(new URL("../firestore.rules", import.meta.url)), "utf8");
const PROJECT_ID = "demo-letter-writer-rules";
const DATABASE = "letter";
const EMULATOR_BASE = `http://127.0.0.1:8085/v1/projects/${PROJECT_ID}/databases/${DATABASE}/documents`;
const OWNER = { Authorization: "Bearer owner" }; // the emulator's admin token bypasses the rules
const ME = "111111111111111111111";
const OTHER = "222222222222222222222";

// A jobs.ch posting and a LinkedIn posting: host-specific keys (see the shared fixture).
const JOBS_URL = "https://www.jobs.ch/de/stellenangebote/detail/6ef0e053-1d7a-45bc-b9a7-a32dd1dfb5f7/?source=jobmail&utm_medium=email";
const JOBS_KEY = "jobs.ch:6ef0e053-1d7a-45bc-b9a7-a32dd1dfb5f7";
const LINKEDIN_URL = "https://www.linkedin.com/jobs/view/424242?refId=abc";
const LINKEDIN_KEY = "linkedin:424242";

const jobsId = await LW_PIPELINE.documentId(ME, JOBS_KEY);
const linkedinId = await LW_PIPELINE.documentId(ME, LINKEDIN_KEY);
const draftingId = await LW_PIPELINE.documentId(ME, JOBS_KEY.replace("6ef0e053", "aaaaaaaa"));

let env;

// Mirrors createMockUserToken (@firebase/util): an unsecured JWT the emulator decodes without
// verifying a signature. `claims.firebase` is what the rules read as request.auth.token.firebase.
function mockIdToken(googleSub) {
  const header = { alg: "none", type: "JWT" };
  const payload = {
    iss: `https://securetoken.google.com/${PROJECT_ID}`,
    aud: PROJECT_ID,
    iat: 0,
    exp: 3600,
    auth_time: 0,
    sub: `firebase-uid-${googleSub}`, // the Firebase uid differs from the Google sub on purpose
    user_id: `firebase-uid-${googleSub}`,
    firebase: { sign_in_provider: "google.com", identities: { "google.com": [googleSub] } },
  };
  const encode = (value) => Buffer.from(JSON.stringify(value), "utf8").toString("base64url");
  return [encode(header), encode(payload), ""].join(".");
}

function clientFor(googleSub) {
  return LW_FIRESTORE.createClient({ baseUrl: EMULATOR_BASE, getIdToken: async () => (googleSub ? mockIdToken(googleSub) : null) });
}

async function clearLetter() {
  const res = await fetch(`http://127.0.0.1:8085/emulator/v1/projects/${PROJECT_ID}/databases/${DATABASE}/documents`, {
    method: "DELETE",
    headers: OWNER,
  });
  if (!res.ok) throw new Error(await res.text());
}

async function seedDoc(path, fields) {
  const res = await fetch(`${EMULATOR_BASE}:commit`, {
    method: "POST",
    headers: { ...OWNER, "Content-Type": "application/json" },
    body: JSON.stringify({
      writes: [
        {
          update: {
            name: `projects/${PROJECT_ID}/databases/${DATABASE}/documents/${path}`,
            fields: LW_FIRESTORE.encodeFields(fields),
          },
          currentDocument: { exists: false },
        },
      ],
    }),
  });
  if (!res.ok) throw new Error(await res.text());
}

function denied(err) {
  return err && err.code === "PERMISSION_DENIED";
}

before(async () => {
  env = await initializeTestEnvironment({
    projectId: PROJECT_ID,
    firestore: { rules: RULES, host: "127.0.0.1", port: 8085 },
  });
});

after(async () => {
  await env.cleanup();
});

beforeEach(async () => {
  await clearLetter();
  await seedDoc(`personal_data/${ME}`, { cv_revisions: [] });
  await seedDoc(`personal_data/${OTHER}`, { cv_revisions: [] });
  await seedDoc(`opportunities/${linkedinId}`, {
    user_id: ME,
    canonical_key: LINKEDIN_KEY,
    status: "approved",
    url: LW_PIPELINE.cleanUrl(LINKEDIN_URL),
    title: "Approved job",
  });
  await seedDoc("opportunities/captured-mine", { user_id: ME, canonical_key: "linkedin:7", status: "captured" });
  await seedDoc("opportunities/ready-mine", { user_id: ME, canonical_key: "linkedin:8", status: "ready" });
  await seedDoc(`opportunities/${draftingId}`, {
    user_id: ME,
    canonical_key: "jobs.ch:aaaaaaaa-1d7a-45bc-b9a7-a32dd1dfb5f7",
    status: "drafting",
  });
  await seedDoc("opportunities/approved-theirs", { user_id: OTHER, canonical_key: "linkedin:999", status: "approved" });
});

describe("extension queueCapture writes straight to Firestore under the real rules", () => {
  test("queues a captured job with the fixture-derived document id", async () => {
    const client = clientFor(ME);
    const result = await LW_PIPELINE.queueCapture(client, {
      userId: ME,
      url: JOBS_URL,
      title: "Senior Dev",
      text: "We are hiring.",
      html: "",
      via: "extension",
    });
    if (result.opportunity_id !== jobsId) throw new Error(`id ${result.opportunity_id} != ${jobsId}`);
    if (result.opportunity_status !== "captured") throw new Error(`status ${result.opportunity_status}`);
    const stored = await client.getDocument(`opportunities/${jobsId}`);
    if (stored.user_id !== ME) throw new Error("user_id");
    if (stored.canonical_key !== JOBS_KEY) throw new Error(`key ${stored.canonical_key}`);
    if (stored.source !== "jobs.ch") throw new Error(`source ${stored.source}`);
    if (stored.status !== "captured") throw new Error(`status ${stored.status}`);
    if (stored.url !== "https://www.jobs.ch/de/stellenangebote/detail/6ef0e053-1d7a-45bc-b9a7-a32dd1dfb5f7") throw new Error(`url ${stored.url}`);
    if (stored.title !== "Senior Dev") throw new Error("title");
    if (!stored.capture || stored.capture.text !== "We are hiring." || stored.capture.via !== "extension") throw new Error("capture");
  });

  test("queues a link-only job as approved", async () => {
    const client = clientFor(ME);
    const result = await LW_PIPELINE.queueCapture(client, { userId: ME, url: JOBS_URL, title: "T", text: "", html: "", via: "extension" });
    if (result.opportunity_status !== "approved") throw new Error(`status ${result.opportunity_status}`);
    const stored = await client.getDocument(`opportunities/${jobsId}`);
    if (stored.status !== "approved") throw new Error(`stored status ${stored.status}`);
    if (stored.capture !== null) throw new Error("capture should be null");
  });

  test("queues a text-only posting under a text key", async () => {
    const client = clientFor(ME);
    const result = await LW_PIPELINE.queueCapture(client, { userId: ME, url: "", title: "", text: "No link posting", html: "", via: "extension" });
    const key = await LW_PIPELINE.textKey("No link posting");
    if (!key.startsWith("text:")) throw new Error(`key ${key}`);
    if (result.opportunity_id !== (await LW_PIPELINE.documentId(ME, key))) throw new Error("id");
    if (result.opportunity_status !== "captured") throw new Error(`status ${result.opportunity_status}`);
    const stored = await client.getDocument(`opportunities/${result.opportunity_id}`);
    if (stored.url !== "") throw new Error(`url ${stored.url}`);
    if (stored.source !== "manual") throw new Error(`source ${stored.source}`);
  });

  test("attaches text to an approved job", async () => {
    const client = clientFor(ME);
    const result = await LW_PIPELINE.queueCapture(client, {
      userId: ME,
      url: LINKEDIN_URL,
      title: "",
      text: "Posting text",
      html: "",
      via: "extension",
    });
    if (result.opportunity_id !== linkedinId) throw new Error("id");
    if (result.opportunity_status !== "captured") throw new Error(`status ${result.opportunity_status}`);
    const stored = await client.getDocument(`opportunities/${linkedinId}`);
    if (stored.status !== "captured") throw new Error(`stored status ${stored.status}`);
    if (!stored.capture || stored.capture.text !== "Posting text") throw new Error("capture");
    if (stored.title !== "Approved job") throw new Error("title must be untouched");
  });

  test("reports a job the desktop is drafting instead of rewriting it", async () => {
    const client = clientFor(ME);
    const result = await LW_PIPELINE.queueCapture(client, {
      userId: ME,
      url: "https://www.jobs.ch/de/stellenangebote/detail/aaaaaaaa-1d7a-45bc-b9a7-a32dd1dfb5f7/",
      title: "",
      text: "Posting text",
      html: "",
      via: "extension",
    });
    if (result.opportunity_status !== "drafting") throw new Error(`status ${result.opportunity_status}`);
    if (result.message !== "The desktop is drafting this job right now.") throw new Error(`message ${result.message}`);
    const stored = await client.getDocument(`opportunities/${draftingId}`);
    if (stored.status !== "drafting") throw new Error(`stored status ${stored.status}`);
    if (stored.capture) throw new Error("capture must stay empty");
  });

  test("an unsigned client cannot write", async () => {
    const client = clientFor(null);
    await LW_PIPELINE.queueCapture(client, { userId: ME, url: JOBS_URL, title: "", text: "x", html: "", via: "extension" }).then(
      () => {
        throw new Error("should have failed");
      },
      (err) => {
        if (err.code !== "UNAUTHENTICATED") throw err;
      },
    );
  });
});

describe("the rules guard the extension's direct writes", () => {
  test("reject a create for another user", async () => {
    const client = clientFor(ME);
    await LW_PIPELINE.queueCapture(client, { userId: OTHER, url: JOBS_URL, title: "", text: "x", html: "", via: "extension" }).then(
      () => {
        throw new Error("should have failed");
      },
      (err) => {
        if (!denied(err)) throw err;
      },
    );
  });

  test("reject a create with a batch-only status", async () => {
    const client = clientFor(ME);
    await client.createIfAbsent(`opportunities/${jobsId}`, { user_id: ME, canonical_key: JOBS_KEY, status: "drafting" }).then(
      () => {
        throw new Error("should have failed");
      },
      (err) => {
        if (!denied(err)) throw err;
      },
    );
  });

  test("reject an update while the batch is drafting (the race guard)", async () => {
    const client = clientFor(ME);
    await client
      .update(`opportunities/${draftingId}`, { status: "captured", capture: { text: "x" }, skip_reason: null, updated_at: new Date() })
      .then(
        () => {
          throw new Error("should have failed");
        },
        (err) => {
          if (!denied(err)) throw err;
        },
      );
  });

  test("reject reading another user's job; a miss is visible as null", async () => {
    const client = clientFor(ME);
    await client.getDocument("opportunities/approved-theirs").then(
      () => {
        throw new Error("should have failed");
      },
      (err) => {
        if (!denied(err)) throw err;
      },
    );
    if ((await client.getDocument("opportunities/does-not-exist")) !== null) throw new Error("expected null");
  });

  test("reject a list query without the user_id filter", async () => {
    const client = clientFor(ME);
    await client.query("opportunities", [["status", "approved"]], ["url"]).then(
      () => {
        throw new Error("should have failed");
      },
      (err) => {
        if (!denied(err)) throw err;
      },
    );
  });
});

describe("the extension's pending-jobs queries", () => {
  test("queryApproved returns only the caller's approved jobs", async () => {
    const client = clientFor(ME);
    const rows = await client.queryApproved(ME);
    if (rows.length !== 1) throw new Error(`rows ${rows.length}`);
    if (rows[0].id !== linkedinId) throw new Error(`id ${rows[0].id}`);
    if (rows[0].canonical_key !== LINKEDIN_KEY) throw new Error(`key ${rows[0].canonical_key}`);
    if (rows[0].status !== "approved") throw new Error(`status ${rows[0].status}`);
    if (rows[0].user_id !== undefined) throw new Error("select should not return user_id");
  });

  test("queryByCanonicalKey finds the approved job for auto-capture", async () => {
    const client = clientFor(ME);
    const rows = await client.queryByCanonicalKey(ME, LINKEDIN_KEY);
    if (rows.length !== 1) throw new Error(`rows ${rows.length}`);
    if (rows[0].id !== linkedinId) throw new Error(`id ${rows[0].id}`);
    if (rows[0].url !== LW_PIPELINE.cleanUrl(LINKEDIN_URL)) throw new Error(`url ${rows[0].url}`);
  });

  test("a user_id-only list query returns every status (the badge counts query)", async () => {
    const client = clientFor(ME);
    const rows = await client.query("opportunities", [["user_id", ME]], ["status"]);
    const statuses = rows.map((r) => r.status).sort();
    const expected = ["approved", "captured", "drafting", "ready"];
    if (JSON.stringify(statuses) !== JSON.stringify(expected)) throw new Error(`statuses ${statuses}`);
    if (rows.some((r) => r.id === "approved-theirs")) throw new Error("another user's job leaked into the counts");
  });
});
