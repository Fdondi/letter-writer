// Firestore rules for the Android app, run against the emulator:
//   scripts/firebase/test_rules.sh
import { after, before, beforeEach, describe, test } from "node:test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { assertFails, assertSucceeds, initializeTestEnvironment } from "@firebase/rules-unit-testing";
import {
  collection,
  deleteDoc,
  doc,
  getDoc,
  getDocs,
  query,
  runTransaction,
  setDoc,
  updateDoc,
  where,
} from "firebase/firestore";

const RULES = readFileSync(fileURLToPath(new URL("../firestore.rules", import.meta.url)), "utf8");
const DATABASE = "letter";
const ME = "111111111111111111111";
const OTHER = "222222222222222222222";
const STRANGER = "333333333333333333333"; // Google account with no desktop profile

let env;

function googleUser(sub) {
  // The Firebase uid differs from the Google sub on purpose: the rules must key on the sub.
  return env
    .authenticatedContext(`firebase-uid-${sub}`, {
      firebase: { sign_in_provider: "google.com", identities: { "google.com": [sub] } },
    })
    .firestore({ databaseId: DATABASE });
}

function passwordUser(uid) {
  return env
    .authenticatedContext(uid, { firebase: { sign_in_provider: "password", identities: { email: ["x@example.com"] } } })
    .firestore({ databaseId: DATABASE });
}

async function seed(fn) {
  await env.withSecurityRulesDisabled(async (ctx) => fn(ctx.firestore({ databaseId: DATABASE })));
}

before(async () => {
  env = await initializeTestEnvironment({
    projectId: "demo-letter-writer-rules",
    firestore: { rules: RULES, host: "127.0.0.1", port: 8085 },
  });
});

after(async () => {
  await env.cleanup();
});

beforeEach(async () => {
  await env.clearFirestore();
  await seed(async (db) => {
    await setDoc(doc(db, "personal_data", ME), { cv_revisions: [] });
    await setDoc(doc(db, "personal_data", OTHER), { cv_revisions: [] });
    await setDoc(doc(db, "personal_data", OTHER, "secrets", "api_keys"), { openai: "sk-other" });
    await setDoc(doc(db, "documents", "mine"), { user_id: ME, created_at: 1 });
    await setDoc(doc(db, "documents", "theirs"), { user_id: OTHER, created_at: 1 });
    await setDoc(doc(db, "feedbacks", "f1"), { user_id: ME });
    await setDoc(doc(db, "companies", "generali"), { company_name: "Generali" });
    await setDoc(doc(db, "sessions", "s1"), { user_id: ME });
    await setDoc(doc(db, "opportunities", "proposed"), { user_id: ME, canonical_key: "linkedin:1", status: "proposed", title: "T" });
    await setDoc(doc(db, "opportunities", "ready"), { user_id: ME, canonical_key: "linkedin:2", status: "ready", vendors_done: ["openai"] });
    await setDoc(doc(db, "opportunities", "ready", "state", "session"), { vendors: { openai: { draft_letter: "D" } } });
    await setDoc(doc(db, "opportunities", "drafting"), { user_id: ME, canonical_key: "linkedin:3", status: "drafting", lease: { owner: "batch" } });
    await setDoc(doc(db, "opportunities", "theirs"), { user_id: OTHER, canonical_key: "linkedin:4", status: "proposed" });
    await setDoc(doc(db, "opportunities", "theirs", "state", "session"), { vendors: {} });
    await setDoc(doc(db, "alert_messages", "a1"), { user_id: ME, message_id: "m1" });
  });
});

describe("personal_data", () => {
  test("owner reads and updates their profile", async () => {
    const db = googleUser(ME);
    await assertSucceeds(getDoc(doc(db, "personal_data", ME)));
    await assertSucceeds(updateDoc(doc(db, "personal_data", ME), { default_vendors: ["openai"] }));
  });

  test("phone can neither create nor delete a profile", async () => {
    await assertFails(setDoc(doc(googleUser(STRANGER), "personal_data", STRANGER), { cv_revisions: [] }));
    await assertFails(deleteDoc(doc(googleUser(ME), "personal_data", ME)));
  });

  test("another account cannot read or write my profile", async () => {
    const db = googleUser(OTHER);
    await assertFails(getDoc(doc(db, "personal_data", ME)));
    await assertFails(updateDoc(doc(db, "personal_data", ME), { x: 1 }));
  });

  test("a non-Google sign-in whose uid equals the sub is refused", async () => {
    await assertFails(getDoc(doc(passwordUser(ME), "personal_data", ME)));
  });

  test("api keys: owner reads and writes, others cannot", async () => {
    await assertSucceeds(setDoc(doc(googleUser(ME), "personal_data", ME, "secrets", "api_keys"), { openai: "sk-me" }));
    await assertSucceeds(getDoc(doc(googleUser(ME), "personal_data", ME, "secrets", "api_keys")));
    await assertFails(getDoc(doc(googleUser(ME), "personal_data", OTHER, "secrets", "api_keys")));
  });

  test("an account without a desktop profile cannot write subcollections", async () => {
    await assertFails(setDoc(doc(googleUser(STRANGER), "personal_data", STRANGER, "secrets", "api_keys"), { openai: "x" }));
  });
});

describe("documents (previous examples)", () => {
  test("owner lists their documents filtered by user_id", async () => {
    await assertSucceeds(getDocs(query(collection(googleUser(ME), "documents"), where("user_id", "==", ME))));
  });

  test("an unfiltered list is refused", async () => {
    await assertFails(getDocs(collection(googleUser(ME), "documents")));
  });

  test("owner reads, updates and deletes their own document only", async () => {
    const db = googleUser(ME);
    await assertSucceeds(getDoc(doc(db, "documents", "mine")));
    await assertSucceeds(setDoc(doc(db, "documents", "mine"), { user_id: ME, letter_text: "v2" }, { merge: true }));
    await assertFails(getDoc(doc(db, "documents", "theirs")));
    await assertFails(setDoc(doc(db, "documents", "theirs"), { user_id: ME }, { merge: true }));
    await assertFails(deleteDoc(doc(db, "documents", "theirs")));
    await assertSucceeds(deleteDoc(doc(db, "documents", "mine")));
  });

  test("cannot hand a document to another user", async () => {
    await assertFails(updateDoc(doc(googleUser(ME), "documents", "mine"), { user_id: OTHER }));
  });

  test("create requires my own user_id and a desktop profile", async () => {
    await assertSucceeds(setDoc(doc(googleUser(ME), "documents", "new1"), { user_id: ME }));
    await assertFails(setDoc(doc(googleUser(ME), "documents", "new2"), { user_id: OTHER }));
    await assertFails(setDoc(doc(googleUser(STRANGER), "documents", "new3"), { user_id: STRANGER }));
  });
});

describe("phase_draft_feedback", () => {
  test("merge-set creates then updates my snapshot", async () => {
    const ref = doc(googleUser(ME), "phase_draft_feedback", `phase_draft_${ME}_s_openai`);
    await assertSucceeds(setDoc(ref, { user_id: ME, vendor: "openai" }, { merge: true }));
    await assertSucceeds(setDoc(ref, { user_id: ME, vendor: "openai", feedback: {} }, { merge: true }));
    await assertFails(getDoc(doc(googleUser(OTHER), "phase_draft_feedback", `phase_draft_${ME}_s_openai`)));
  });
});

describe("feedbacks", () => {
  test("append-only records for the owner", async () => {
    await assertSucceeds(setDoc(doc(googleUser(ME), "feedbacks", "f2"), { user_id: ME }));
    await assertFails(setDoc(doc(googleUser(ME), "feedbacks", "f3"), { user_id: OTHER }));
    await assertFails(updateDoc(doc(googleUser(ME), "feedbacks", "f1"), { rating: 5 }));
    await assertFails(deleteDoc(doc(googleUser(ME), "feedbacks", "f1")));
  });
});

describe("companies (shared research cache)", () => {
  test("known users read and write; strangers and deletes are refused", async () => {
    await assertSucceeds(getDoc(doc(googleUser(ME), "companies", "generali")));
    await assertSucceeds(getDocs(collection(googleUser(ME), "companies")));
    await assertSucceeds(setDoc(doc(googleUser(ME), "companies", "generali"), { reports: {} }, { merge: true }));
    await assertFails(getDoc(doc(googleUser(STRANGER), "companies", "generali")));
    await assertFails(deleteDoc(doc(googleUser(ME), "companies", "generali")));
  });
});

describe("opportunities (job pipeline)", () => {
  test("owner lists their jobs filtered by user_id; unfiltered lists are refused", async () => {
    const db = googleUser(ME);
    await assertSucceeds(getDocs(query(collection(db, "opportunities"), where("user_id", "==", ME))));
    await assertFails(getDocs(collection(db, "opportunities")));
    await assertFails(getDoc(doc(db, "opportunities", "theirs")));
  });

  test("the phone creates captured or approved jobs for itself only", async () => {
    const db = googleUser(ME);
    await assertSucceeds(setDoc(doc(db, "opportunities", "new1"), { user_id: ME, canonical_key: "url:x", status: "captured", capture: { text: "t" } }));
    await assertSucceeds(setDoc(doc(db, "opportunities", "new2"), { user_id: ME, canonical_key: "url:y", status: "approved" }));
    await assertFails(setDoc(doc(db, "opportunities", "new3"), { user_id: ME, canonical_key: "url:z", status: "ready" }));
    await assertFails(setDoc(doc(db, "opportunities", "new4"), { user_id: OTHER, canonical_key: "url:z", status: "captured" }));
    await assertFails(setDoc(doc(googleUser(STRANGER), "opportunities", "new5"), { user_id: STRANGER, canonical_key: "url:z", status: "captured" }));
  });

  test("the app's send: a transaction reads the (missing) job, then creates it", async () => {
    const db = googleUser(ME);
    const ref = doc(db, "opportunities", "sent-from-phone");
    await assertSucceeds(getDoc(ref));
    await assertSucceeds(
      runTransaction(db, async (tx) => {
        const snap = await tx.get(ref);
        if (snap.exists()) throw new Error("expected a new job");
        tx.set(ref, { user_id: ME, canonical_key: "text:abc", status: "captured", capture: { text: "posting", via: "share_text" } });
      }),
    );
    // Sending again reads the job just made and attaches the new text to it.
    await assertSucceeds(
      runTransaction(db, async (tx) => {
        const snap = await tx.get(ref);
        tx.set(ref, { status: "captured", capture: { text: "posting v2" }, updated_at: 2 }, { merge: true });
      }),
    );
    // A miss reveals nothing, but someone else's existing job stays unreadable, in a transaction too.
    const other = googleUser(OTHER);
    await assertFails(runTransaction(other, async (tx) => { await tx.get(doc(other, "opportunities", "sent-from-phone")); }));
  });

  test("triage, capture and done are allowed; desktop states and bookkeeping are not", async () => {
    const db = googleUser(ME);
    await assertSucceeds(updateDoc(doc(db, "opportunities", "proposed"), { status: "approved", updated_at: 1 }));
    await assertSucceeds(updateDoc(doc(db, "opportunities", "proposed"), { status: "captured", capture: { text: "posting" } }));
    await assertSucceeds(updateDoc(doc(db, "opportunities", "ready"), { status: "done", document_id: "doc1" }));
    // Sending the posting again with other desktop settings.
    await assertSucceeds(updateDoc(doc(db, "opportunities", "proposed"), { status: "captured", capture: { text: "p" }, rewrite_rounds: 2, final_feedback: false }));
    await assertFails(updateDoc(doc(db, "opportunities", "proposed"), { status: "ready" }));
    await assertFails(updateDoc(doc(db, "opportunities", "proposed"), { status: "drafting" }));
    await assertFails(updateDoc(doc(db, "opportunities", "proposed"), { user_id: OTHER }));
    await assertFails(updateDoc(doc(db, "opportunities", "proposed"), { vendors_done: ["openai"] }));
    await assertFails(updateDoc(doc(db, "opportunities", "proposed"), { canonical_key: "linkedin:9" }));
  });

  test("a job the desktop is drafting cannot be touched", async () => {
    await assertFails(updateDoc(doc(googleUser(ME), "opportunities", "drafting"), { status: "skipped" }));
  });

  test("nobody else updates my jobs and nobody deletes them", async () => {
    await assertFails(updateDoc(doc(googleUser(OTHER), "opportunities", "proposed"), { status: "approved" }));
    await assertFails(deleteDoc(doc(googleUser(ME), "opportunities", "proposed")));
  });

  test("drafts are readable by the owner only and written only by the desktop", async () => {
    await assertSucceeds(getDoc(doc(googleUser(ME), "opportunities", "ready", "state", "session")));
    await assertFails(getDoc(doc(googleUser(ME), "opportunities", "theirs", "state", "session")));
    await assertFails(getDoc(doc(googleUser(OTHER), "opportunities", "ready", "state", "session")));
    await assertFails(setDoc(doc(googleUser(ME), "opportunities", "ready", "state", "session"), { vendors: {} }));
  });

  test("the alert mail log is server-only", async () => {
    await assertFails(getDoc(doc(googleUser(ME), "alert_messages", "a1")));
  });
});

describe("everything else", () => {
  test("server-only collections are closed", async () => {
    await assertFails(getDoc(doc(googleUser(ME), "sessions", "s1")));
    await assertFails(setDoc(doc(googleUser(ME), "sessions", "s2"), { user_id: ME }));
  });

  test("signed-out access is refused", async () => {
    const db = env.unauthenticatedContext().firestore({ databaseId: DATABASE });
    await assertFails(getDoc(doc(db, "companies", "generali")));
    await assertFails(getDoc(doc(db, "personal_data", ME)));
  });
});
