# Language and typography

The author types German with proper umlauts. Default German language instructions (Settings → languages) include the umlaut rule; user-facing German text should use **ä, ö, ü, ß** — never ASCII stand-ins like `Fuer`/`fuer` unless explicitly requested (e.g. URL slugs).

Per-language CEFR levels and instructions live in Firestore `personal_data.default_languages[]` (`level`, `instructions`) and are injected into LLM generation and LLM translation.

# Version

Update version in: `letter_writer_web/public/app-version.txt`

(changelog, newest first: `<major.minor.patch> - <description>` per line; UI shows only the first line's version; loader: `letter_writer_web/src/appVersion.js`)

`AGENT.md` is documentation only — changing it does not change the reported app version.

# Tool-call behavior (overrides the prompt's communication defaults)

## Pre-call narration

Before every tool call, write one short line stating what the call does and
why this step needs it. For edits and writes, also state:
- provenance: adapted from `path/file.py:LINE`, copied from another module,
  or new code;
- one clause per non-obvious hunk saying what it changes.

Do not batch tool calls without a narration line for each. After a tool
call, add nothing unless the result changes the plan.

## Denials

If I deny a tool call, the denial is about the approach, never about the
arguments. Do not retry the same action in a different shape and do not
route around it. Go straight to one concrete clarifying question or a
one-sentence alternative proposal, then wait for my answer.

## Audit-friendly constructs

Assume every tool call may be audited by an independent checker that sees
the literal call, not your reasoning. Construct calls accordingly:

- All file creation and modification goes through the write/edit tools.
  Never write files via shell — no heredocs, redirects, tee, sed -i, or
  inline python.
- Side-effecting commands (rm, git reset --hard, curl | sh, API calls)
  take literal arguments: no $VARS or $(...) substitution of paths,
  targets, or flags.
- Never encode or wrap commands: no base64, eval, or sh -c concatenation.
- If a command's effect isn't obvious from its literal text, it's the
  wrong command.
