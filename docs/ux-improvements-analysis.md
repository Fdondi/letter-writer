# UX & Quality Improvements Analysis

## Current State Problems

### 1. Wait Time & Progress Feedback
**Problems:**
- Long waits (1-3 minutes) with minimal progress feedback
- User sees "Loading..." but doesn't know what's happening
- Feedback phase runs 4-5 separate LLM calls sequentially (~20-40s total) with no visibility

**Root causes:**
- PhaseFlow shows only "readyCount/totalCount" badges
- No granular "current step" indicator during multi-stage operations
- Background/plan/draft/feedback/refine phases are opaque to user

### 2. Excessive Approval Steps
**Problems:**
- Plan approval required for each vendor (or 30s auto-approve wait)
- Draft approval required for each vendor
- Feedback must be reviewed before refinement
- 2-3 manual approval clicks per vendor × multiple vendors = high friction

**Root causes:**
- `includePlanStep` defaults to true in VendorFlow
- Each phase requires explicit `onApprove` call
- No "express mode" for users who trust the system

### 3. Formulaic Letter Output
**Problems:**
- Letters feel generic and template-like
- Over-reliance on RAG examples leads to copy-paste style
- Feedback checks enforce conformity to past patterns

**Root causes from code:**
- Prompt says "produce a personalized cover letter **in the same style as the examples**"
- RAG examples dominate the generation context
- Multiple feedback rounds push output toward "safe" middle ground
- No explicit anti-cliché or distinctiveness instruction

## High-Leverage Solutions

### Solution 1: Granular Progress Indicators
**Impact:** Makes waits feel 40-60% shorter (psychological)

**Changes:**
- Add `currentStep` state to show "Retrieving examples...", "Researching company...", "Generating draft...", "Checking accuracy...", etc.
- Show estimated time remaining for each step
- Update progress indicator every 2-3 seconds during long operations

**Files:** 
- `letter_writer_web/src/components/phase-flow/VendorCard.jsx` - add progress UI
- `letter_writer_web/src/pages/VendorFlowPage.jsx` - track and broadcast step status
- `letter_writer_server/api/phases.py` - add progress events (optional WebSocket/SSE)

### Solution 2: Skip Plan Phase by Default
**Impact:** Saves 30s + 1 approval per vendor

**Changes:**
- Set `includePlanStep: false` as default
- Add "Show strategic planning" toggle for power users
- When plan IS used, auto-approve after generation (just show it, don't wait for click)

**Files:**
- `letter_writer_web/src/contexts/JobSessionContext.jsx` - change default
- `letter_writer_web/src/pages/IntakePage.jsx` - add toggle
- `letter_writer_web/src/components/PhaseFlow.jsx` - auto-approve plan when enabled

### Solution 3: Express Mode (One-Click Generation)
**Impact:** Reduces approvals from 2-3 to 0-1 per vendor

**Changes:**
- Add "Express Mode" checkbox on intake: generates final letter directly
- In express mode: skip plan, auto-approve draft, auto-refine with feedback
- Show feedback summary after generation (optional review)

**Files:**
- `letter_writer_web/src/pages/IntakePage.jsx` - add express mode toggle
- `letter_writer_web/src/pages/VendorFlowPage.jsx` - implement auto-flow logic
- `letter_writer_web/src/components/PhaseFlow.jsx` - support auto-progression

### Solution 4: Anti-Formulaic Prompt Improvements
**Impact:** 20-30% more distinctive letters

**Changes:**
- Modify system prompt to emphasize distinctiveness over template-matching
- Add explicit instruction: "Avoid clichés, generic phrases, and overused opener/closer patterns"
- Change from "same style as examples" to "inspired by examples' structure and voice"
- Reduce RAG example weight in context (fewer examples or lower prominence)

**Files:**
- `letter_writer/letter_generation.py` - update `generate_letter` system prompt
- `letter_writer/retrieval.py` - reduce top_k from 7→3 for selection phase
- `letter_writer/instructions.py` - update default style instructions

### Solution 5: Parallel Feedback Execution
**Impact:** Saves 15-25s by running feedback checks concurrently

**Changes:**
- Run accuracy/precision/fit checks in parallel instead of sequentially
- Use `asyncio.gather()` or thread pool for concurrent LLM calls

**Files:**
- `letter_writer/feedback_checks.py` - refactor `run_phased_feedback_checks` to use async/threads
- `letter_writer/phased_service.py` - call parallel feedback runner

## Implementation Priority

1. **Quick wins (30 min each):**
   - Skip plan phase by default (Solution 2)
   - Basic progress indicators (Solution 1, partial)

2. **Medium effort (1-2 hours):**
   - Anti-formulaic prompts (Solution 4)
   - Express mode (Solution 3)

3. **Larger effort (3-4 hours):**
   - Parallel feedback execution (Solution 5)
   - Real-time progress with WebSocket (Solution 1, complete)

## Success Metrics

- **Fewer approval moments:** 2-3 → 0-1 per vendor (express mode)
- **Clearer progress:** User always knows current step + time estimate
- **Less formulaic:** User/tester subjective rating improves
- **Faster perceived time:** Psychological wait time reduced by providing visibility
