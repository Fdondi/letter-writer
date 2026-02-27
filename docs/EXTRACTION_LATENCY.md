# Extraction latency and making LLM calls faster

## Where time goes

Extraction is **I/O-bound**: most of the time is waiting for the LLM API (network + model prefill + generation). The flamegraph shows stacks like `extract_key_competences` → `client.call` → … → `ssl.read`. So optimising Python code has limited impact; the levers are **fewer calls**, **caching**, and **prompt structure**.

## What we already do

- **Small model**: Extraction uses `ModelSize.TINY` (e.g. gpt-5-nano, claude-haiku-4-5, gemini-2.5-flash-lite per `letter_writer/clients/*.json`).
- **Parallel calls**: `extract_job_metadata_no_requirements` and `extract_key_competences` run in parallel (2 threads). Grading runs after, since it depends on extraction output.
- **In-memory cache**: Repeated extraction for the **same job** (e.g. multiple CVs) reuses the two extraction results; only grading is re-run (see `_EXTRACTION_CACHE` in `generation.py`).
- **Shared prompt prefix**: Both extraction calls use the same system prompt and the same start of the user message (`Job description:\n{job_text}\n\n`). The **task** (metadata vs competences) is only in the suffix. That allows provider-side prompt caching.

## Prompt caching (prefix reuse)

Many providers cache the **prefix** of the prompt and reuse it across requests:

- **OpenAI**: Automatic for prompts ≥1024 tokens (GPT-4o and newer). Cache is by exact prefix; putting the job first and the question/task at the end keeps the prefix identical so the second request can hit the cache. Check `usage.prompt_tokens_details.cached_tokens` in the response to see cache hits.
- **Anthropic**: Explicit `cache_control` on blocks; you can mark the job-description block as cacheable and send multiple questions in separate requests that reuse it.

So: **adding the question at the end** is correct. The prefix (system + job) stays the same; only the suffix (task + example) changes. That gives cache hits when the same job is sent again with a different task, and avoids “new request” behaviour from the cache’s point of view.

## TTFT vs generation time

- **Time to first token (TTFT)**: latency until the first output token (prefill + first decode step).
- **Generation time**: time to produce the rest of the output.

If most of the wait is TTFT, splitting into more parallel calls doesn’t help much (each call pays TTFT). If most is generation, shorter outputs or a smaller model help more.

To measure TTFT in this codebase you’d need to:

1. Use **streaming** in the client (e.g. `stream=True` for OpenAI `chat.completions.create`).
2. Record the time until the first chunk and the time until the last chunk; difference is generation time.

Right now we don’t stream extraction; adding an optional streaming path and timing would require client changes (e.g. a `call_stream` or similar that yields chunks and optionally returns timings).

## Splitting into more questions / more parallel calls

- We already run **two** extraction calls in parallel (metadata + competences). A third call (grading) depends on their output, so it can’t run in parallel with them.
- Splitting further (e.g. 3 calls for 3 competence categories) would mean **3 round-trips**, each with its own TTFT + generation. Total wall time could improve only if those 3 calls are much faster per call and we run them in parallel; usually the extra round-trips and TTFTs make it slower or similar. Keeping one competences call and one metadata call is a good balance.
- “Upload document once and ask many questions in parallel” is exactly what **prompt caching** supports: the job is the cached prefix; each request only adds a different task (question) at the end. We’ve structured extraction so both calls share that prefix; with sequential dispatch the second call can hit the cache; with parallel dispatch the second may hit the cache depending on routing and timing.

## Summary

- **Same text, different question at the end**: Yes, that can hit cache; we structure prompts so the job is the prefix and the task is the suffix.
- **Faster model**: We already use TINY; you can switch to a smaller/faster variant in `clients/*.json` if your provider offers one.
- **Fewer tokens**: Shorter job excerpt or shorter task text reduces cost and can reduce latency.
- **Measure TTFT**: Requires streaming and timing in the client; not implemented yet.
