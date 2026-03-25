# Agentic Feedback Flow: Visibility and Actions

This document describes the current behavior of the agentic discussion pipeline, including what each agent can see and what each agent is allowed to do at every stage.

## Scope

- Covers the feedback path executed by `/agentic/feedback/start` background worker logic.
- Reflects current implementation in `letter_writer_server/api/phases.py` and `letter_writer/agentic_service.py`.

## Terminology

- **Topic**: one dimension in `AGENTIC_TOPIC_KEYS` (for example instruction, accuracy, etc.).
- **Vendor/agent**: one model provider selected in `feedback_vendors`.
- **Thread**: list of top-level comments for a topic, including subcomments, addendums, and votes.
- **Carry-over comment**: a cloned top comment from an earlier topic, injected into a later topic so later-topic agents can react.
- **Round**: per-topic cursor round. A topic is active while `topic_round <= max_rounds`.

## High-level execution order

Each worker tick runs these stages:

1. Heartbeat/suspend/abort checks.
2. Build active topic work for the current global tick.
3. **Phase A (parallel topics):** run all active topics in parallel.
4. Persist Phase A outputs (threads + per-topic round increment/shuffle).
5. **Phase B (linear cross-topic sweep):** for each later topic, run one additional pass where it sees carry-over comments from all earlier topics at once.
6. Persist Phase B updates.
7. Repeat until no active topics remain, then mark `feedback_done`.

## Stage-by-stage visibility and permissions

### Stage 0: Entry checks

Before any agent call:

- Worker reads `feedback_ongoing`, `feedback_suspended`, heartbeat timestamps.
- If suspended: stop worker and persist.
- If stale poll heartbeat: hard-abort feedback and reset state back to draft phase.

No model calls happen here.

### Stage 1: Build topic work items

For each active topic:

- Build topic context from draft(s), CV, company report, job text, docs, style, and metadata.
- Load current topic thread.
- Ensure vendor order exists (fallback from persisted `feedback_vendor_order` if needed).

No agent acts here; this stage only prepares input.

### Stage 2 (Phase A): Parallel topic execution

All active topics run concurrently. Within each topic, vendors run sequentially in that topic order.

What an agent in topic `T` sees in Phase A:

- Topic `T` context (draft(s) + source data).
- Current thread for topic `T` only.
- No cross-topic carry-over is injected in this phase.

What the agent can do:

- If thread empty (first agent path):
  - create one top-level comment, or skip (`NO COMMENT` / `SKIP`).
- If thread non-empty (JSON path):
  - optional new top-level comment (`new_comment`).
  - subcomment on open comments.
  - vote top-level comments (`upvote` / `downvote` / `abstain`).
  - upvote/downvote existing addendums by `addendum_id`.
  - add a new addendum (which starts with author upvote).

Important vote effects:

- Any top-level **downvote** marks that comment removed for downstream use.
- When an addendum becomes net-positive, parent comment votes are invalidated/reset.

After each topic completes:

- Topic thread returned from Phase A is persisted.
- Topic cursor round increments by 1.
- Topic vendor order reshuffled for next round.

### Stage 3 (Phase B): Linear cross-topic sweep

Topics are processed in fixed order. For each target topic `j > 0`:

- Collect carry-over comments from **all earlier topics** `0..j-1` using top surviving comments per earlier topic.
- Inject those carry-over comments into topic `j` thread once.
- Run topic `j` vendors sequentially one more time for this sweep.
- Merge carry-over edits back into source topics, then strip carry-over clones from topic `j` visible thread.

What an agent in target topic `j` sees in Phase B:

- Same topic `j` context as Phase A.
- Topic `j` local thread.
- Prior-topic carry-over section containing selected comments from all earlier topics.

What the agent can do in Phase B:

- The exact same actions as Stage 2 JSON path:
  - vote/subcomment/addendum/new comment according to prompt rules.
- Actions on carry-over clones are written back to original source-topic comments during merge.

Visibility consequence:

- Later topics get a "last word" pass over earlier topics' selected comments.
- Earlier topics do not get an additional pass after later topics act in this same tick.

### Stage 4: Completion condition

When no topics remain active (`topic_round > max_rounds` for all topics):

- Worker sets `feedback_ongoing = False`.
- Worker sets status to `feedback_done`.

## What is selected for cross-topic carry-over

When building prior-topic carry-over for target topic `T`:

- Only topics earlier than `T` are considered.
- Removed comments are excluded.
- Candidates are ranked by score (up/down votes + small bonuses for discussion/addendum signals).
- Up to `max_per_topic` (currently 3) comments per earlier topic are cloned.

So agents do **not** see all earlier-topic comments, only top surviving ones.

## Who can act on what (quick matrix)

- **Topic-local comments in Phase A:** agents of that same topic can act.
- **Earlier-topic carry-over in Phase A:** not shown.
- **Earlier-topic carry-over in Phase B:** agents of later topics can act; actions are merged back to originals.
- **Removed comments:** visible for audit but not acted on downstream.

## Voting stage (post-feedback)

After feedback is done, voting is separate:

- Each voting vendor reads all drafts + all discussion threads.
- Voting calls are parallelized.
- Each voter returns top-3 preferred draft vendors.

This is independent from per-topic feedback action rules above.

## Notes on current behavior

- Current flow is **parallel topics + linear sweep** per worker tick.
- This differs from strictly topic-serial execution and from full quadratic per-edge sweep.
- Cross-topic visibility is present, but only through selected top carry-over comments from earlier topics.

## In-memory “live” state vs persisted session

While feedback is running, the API keeps a per-session copy in `_agentic_live_store` (same server process) so the background worker and `/agentic/feedback/poll/` can share threads without racing. Polls that hit **another** worker process have no live entry and read **persisted** session storage instead.

On `/agentic/feedback/start/`, if a live entry already exists from an earlier run on the same process (for example after a new draft followed by starting feedback again), the handler must **replace** that entry’s `state` from the current session. Updating only `last_poll_at` would leave `feedback_ongoing=false` from the old run, so the worker exits immediately (`AGENTIC ordered worker exit: ongoing=false`), nothing is generated, and the UI shows empty threads while persisted data can briefly look inconsistent.
