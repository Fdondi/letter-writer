# Agentic Feedback Flow

This document describes the agentic discussion pipeline: phases, parallelism, structured LLM outputs, persistence, and what the UI shows while feedback runs.

## Scope

- Feedback is started via `/api/phases/agentic/feedback/start/` and runs in a background worker (`_run_ordered_feedback_loop` in `letter_writer_server/api/phases.py`).
- Core logic and schemas live in `letter_writer/agentic_service.py`.
- LLM clients accept optional `response_format` (JSON schema) on `BaseClient.call` so each phase exposes **only** the allowed output shape—not merely prompt text.

## Terminology

- **Topic**: one dimension in `AGENTIC_TOPIC_KEYS` (instruction, company_fit, precision, user_fit, human, accuracy).
- **Vendor**: a model provider from `feedback_vendors` / `feedback_vendor_order`.
- **Thread**: per-topic list of top-level comments (subcomments, addendums, votes).
- **Round**: per-topic cursor `round` in `topic_cursors`. A topic is active while `round <= max_rounds`.

## High-level execution order

Each worker loop iteration (one “global round”) runs:

1. Heartbeat / suspend / stale-poll abort checks.
2. **Phase A — topic phases (strictly ordered sub-phases, parallel within each sub-phase):**
   - **A1**: optional new top-level comment per (topic × vendor).
   - **A2a**: optional subcomments per (topic × vendor), seeing the thread after A1.
   - **A2b**: optional subcomments again, seeing the thread after A2a.
   - **A3**: optional addendums (edit suggestions) per (topic × vendor), seeing the full thread after A2b.
3. **Phase B — global cross-topic vote:** after all of Phase A finishes for this round, every vendor runs **one** structured vote call over **all** active topics’ comments and addendums. Votes are applied; items with strictly negative score (`down > up`) are dropped (comments marked removed; addendums removed from lists).
4. Per-topic round counters advance and vendor orders reshuffle; repeat until every topic has `round > max_rounds`, then `feedback_done`.

There is **no** sequential “one vendor after another” chain inside a topic for these phases, and **no** linear per-topic Phase B sweep. Cross-topic interaction is **Phase B** only.

## Parallelism

- **Phase A (each of A1 / A2a / A2b / A3):** all `(active_topic × feedback_vendor)` API calls for that sub-phase run concurrently (`ThreadPoolExecutor` + `as_completed`).
- **Phase B:** all `feedback_vendor` global vote calls run concurrently.

## Structured output (tools / schemas)

Each phase uses a **fixed JSON schema** passed to the client as `response_format` (OpenAI/DeepSeek: `response_format`; Anthropic: single tool + `tool_choice`; Gemini: `response_schema` when schema is set). The model is constrained to that schema for the call—not only by natural-language instructions.

Rough shape by phase (see `letter_writer/agentic_service.py` for exact `SCHEMA_*`):

| Phase | Allowed output |
|--------|----------------|
| A1 | `{ "new_comment": string \| null }` |
| A2a / A2b | `{ "subcomments": [ { "comment_id", "text" } ] }` |
| A3 | `{ "addendums": [ { "comment_id", "text" } ] }` |
| B | `{ "votes": [ { "topic", "target_type", "comment_id", "action", optional "addendum_id", "reason" } ] }` |

Entry point: `call_agentic_phase_action(...)`. Application to threads uses `apply_phase_a1_comment`, `apply_phase_subcomments`, `apply_phase_addendums`, and `apply_global_votes_and_prune`.

## Legacy cross-topic carry-over

Earlier designs injected “carry-over” clones from prior topics into later topic threads and merged edits back. That path is **disabled**; global Phase B replaces it. Helper functions such as `get_prior_topic_top_comments` / `seed_thread_with_prior_topic_comments` / `merge_carryover_updates_and_strip` are kept for compatibility but no longer drive the main loop.

## UI: `waiting_for` (topic progress)

While `feedback_ongoing` is true, `topic_meta[topic].waiting_for` (also echoed under each topic in poll `threads`) describes what that topic is waiting on.

- **Phase A:** each topic shows **that topic’s** vendors only:
  - `API returned: … | still running: …` updates **after each** vendor call completes for that topic in the current sub-phase (A1, A2a, A2b, or A3).
- **Phase B:** every active topic shows the **same** global line (one shared vote wave):
  - `API returned: … | still running: …` updates after each vendor’s global vote call returns.

Strings are built in `letter_writer_server/api/phases.py` via `_topic_wait_strings_phase_a` and `_topic_wait_strings_phase_b`.

State is stored in `topic_feedback_wait` on the agentic state object; `_build_topic_meta` in `letter_writer/agentic_service.py` exposes it as `waiting_for` when feedback is ongoing.

## Poll snapshot (live sessions)

For `/agentic/feedback/poll/`, when a live in-memory entry exists, the snapshot passed to `poll_response` must include:

- `worker_running`
- `topic_feedback_wait`

Otherwise the UI would see `waiting_for: null` even while the worker is updating progress.

## In-memory live state vs persisted session

While feedback runs, a per-session entry in `_agentic_live_store` lets the worker and poll share state. The worker persists after phase merges. Polls on **another** process fall back to persisted storage (may lag on `waiting_for` until next persist).

On feedback start, if a live entry exists from a prior run, the handler must replace its `state` from the current session so `feedback_ongoing` and threads are not stale (see comments in `phases.py` around `agentic/feedback/start/`).

## Post-feedback draft voting (separate)

After `status === feedback_done`, the product may run **draft** voting (`draft_votes`): each voter ranks favorite draft vendors. That is separate from Phase B comment/addendum voting above.
