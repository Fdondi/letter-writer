# Email integration (experimental)

Not used by the app. The opportunity pipeline works without it: jobs come from the phone, the
extension or the web app (README → Opportunity pipeline). This folder keeps everything built and
learned so far about reading job alerts and application replies from Gmail, for the version to come.

## What is here

| File | What it does |
|---|---|
| `alert_parsing.py` | Fixed-rule parsers ("templates") per sender: jobs.ch recommendations, LinkedIn alert digests, LinkedIn notices (application sent, viewed, rejected), swissdevjobs |
| `application_tracking.py` | Application history (saved letters + known applications), title and company matching, a reply classifier (tool-less model call), outcomes (furthest stage, result, praise) |
| `mail_store.py` | Store additions: processed-mail log, application events, learned noise senders |
| `mail_batch.py` | CLI: `propose`, `unseen`, `outcomes` (below) |
| `prompts/` | Classifier prompt and JSON schema |
| `fixtures/` | Synthetic mails in each sender's layout (no real content) |
| `routine/SKILL.md` | Claude routine that reads Gmail through the connector and runs the commands |
| `tests/` | `pytest experimental/email/tests` (Firestore emulator, no real services) |
| `samples/` | Real API responses (two LinkedIn digests, three searches). **Gitignored**, this machine only |
| `review/` | Mail no template matched, saved by `propose` for manual review. **Gitignored** |

```bash
.venv/bin/python -m experimental.email.mail_batch propose --mail-file mail.jsonl            # unmatched mail -> review/
.venv/bin/python -m experimental.email.mail_batch propose --mail-file mail.jsonl --classify # unmatched mail -> classifier
.venv/bin/python -m experimental.email.mail_batch propose --mail-file mail.jsonl --dry-run  # parse only, touch nothing
.venv/bin/python -m experimental.email.mail_batch unseen <id>:<sender> …
.venv/bin/python -m experimental.email.mail_batch outcomes
```

## Direction (2026-10-24)

- **Python reads Gmail directly** (read-only OAuth), not a Claude agent through the connector: no
  agent tokens, and the HTML is available.
- **A library of templates chosen by metadata** (sender, subject pattern) does the parsing.
- **Intelligence only where templates fall short**: a mail with job-offer keywords that matches no
  template, or a mail whose sender/subject says a template should match but it does not. **For now
  such mail is kept for manual review** (`review/`), to build an intuition for the shape of the
  problem before automating it.
- **Rejections and other replies**: later via the local-AI email triage system built earlier (not on
  GitHub; see the chat of that project). To integrate from home; it would replace the classifier
  call in `application_tracking.classify_mail`.

## Findings (Gmail, 2026-10-24)

### Volumes (last 14 days)

- Job alerts: ~61 mails (~4.5/day). `jobalerts-noreply@linkedin.com` ~2/day, `jobs-noreply@linkedin.com`
  ~1/day, `info@jobs.ch` ~1/day, `app@swissdevjobs.ch` rare.
- Keyword search for replies (query in `routine/SKILL.md`): 26 mails, ~15 about applications,
  ~11 noise (newsletters, course ads, notices that contain "application"/"Absage"/"Bewerbung").

### Templates seen, by sender

| Sender | Subject | Body (PLAIN_TEXT) | Status |
|---|---|---|---|
| `info@jobs.ch` | "Job-Empfehlungen für dich" | `Title - <detail URL>` then `Company, City`; `&amp;` left escaped | template |
| `jobalerts-noreply@linkedin.com` | varies ("X at Y", "Hiring now: …", "… and N other jobs") | blocks: title, company, location, badges, `View job: <url>`, separated by dashes; several alerts per mail | template (by body, not subject) |
| `jobs-noreply@linkedin.com` | "…, your application was sent to <Company>" | first block is the job; "similar jobs" below | template (applied) |
| `jobs-noreply@linkedin.com` | "Your application was viewed by <Company>" | job block | template (viewed) |
| `jobs-noreply@linkedin.com` | "Your application to <Title> at <Company>" | only "Your update from <Company>" + footer; the kind is in the tracking parameter `email_jobs_application_rejected_01` | template (rejection) |
| `jobs-noreply@linkedin.com` | "<Company> is hiring …", "apply now to …" | job blocks | template (proposals) |
| `app@swissdevjobs.ch` | "Your application at <Company>", newsletter confirmations | — | to the classifier / review |
| `recommender@my.jobscout24.ch` | "Ces jobs pourraient vous intéresser" | **only opaque `click.my.jobs.ch/?qs=…` links**, no titles or companies; jobs are in the HTML | needs HTML. Do not follow the links: automated access to JobCloud, and it counts as clicks on the recommendations |
| `hamilton@myworkday.com` (Workday) | "Ihre Bewerbung bei <Company> als <Title>" | receipt | classifier / review |
| `hr@partnersgroup.com` | "PG People: Application Received for <Title> at <Company> - Next Steps", "Thank you for your application" | receipt | classifier / review |
| `donotreply@stadlerrail.com` | "Your application at Stadler" (receipt), "Your application as <Title> at Stadler" (rejection) | short | classifier / review |
| `notifications@smartrecruiters.com` | "Your application – <Title>" | rejection | classifier / review |
| `peopleandculture@viseca.ch` | "your application" | rejection | classifier / review |
| `jobs-noreply@ethz.ch` | "Confirmation: <Title> at ETH Zurich" | receipt | classifier / review |
| `avs@ghrgroup.ch` (agency) | "Auftrag A9454 - <Title>…", "… Beworben", "Info Auftrag …" | personal mails; "sent your documents to the customer" (= forwarded) | classifier / review |

Noise matched by the keyword search: `notification@my.jobs.ch` / `rebekka@my.jobs.ch` (unfinished
application reminder, newsletter "Jenseits der Absage"), `formazione@almalaurea.it`, `*@emeritus.org`,
`noreply@email.openai.com`, `no-reply@outlier.ai`, `newsletters-noreply@linkedin.com`. Threads can
contain your own replies (label SENT): skip them.

### Examples to review (open in Gmail)

- LinkedIn digest: <https://mail.google.com/mail/u/0/#all/1a16242043778054>
- LinkedIn rejection notice ("Your application to … at Navique"): <https://mail.google.com/mail/u/0/#all/1a1588dea785e19f>
- LinkedIn "application sent": <https://mail.google.com/mail/u/0/#all/1a1649c636b53732>
- jobs.ch recommendations: <https://mail.google.com/mail/u/0/#all/1a165289363d64ae>
- JobScout24 recommendations: <https://mail.google.com/mail/u/0/#all/1a16428732f497aa>
- Receipts: Workday/Hamilton <https://mail.google.com/mail/u/0/#all/1a14007bb04cd721>, Partners Group <https://mail.google.com/mail/u/0/#all/1a13af40124de4a8>, Stadler <https://mail.google.com/mail/u/0/#all/1a11c7321cc214f0>
- Rejections: Viseca <https://mail.google.com/mail/u/0/#all/1a13f6e520366ae7>, SmartRecruiters <https://mail.google.com/mail/u/0/#all/1a134ab457223923>, Stadler <https://mail.google.com/mail/u/0/#all/1a12455ec084359f>
- Agency (forwarded to the client): <https://mail.google.com/mail/u/0/#all/1a16735822d90427>

### Cost of reading mail with a Claude agent (measured)

- Each model turn of a headless `claude -p` routine carries ~26k tokens before any mail (Claude Code
  system prompt and tool definitions). Limiting the tools makes it worse (~37k: the Gmail tool
  definitions then load in full instead of on demand).
- A routine every 4 hours: ~1M input tokens/day (mostly cache reads, one cold cache write per run) and
  ~25k output tokens (the agent copies each mail body into the batch's input file). ~80% is fixed
  overhead; mail content is ~14k tokens/day.
- A classifier call through `claude -p` with a replaced system prompt and no tools: 576 tokens plus
  the mail.
- Python reading Gmail directly would cost no tokens for reading; only the fallback (classifier or
  local AI) would.
