# Inbox-to-Action Agent — Running Writeup Log

> Append to this after every work session. Don't edit past entries — just add new ones.
> Format: what I built, why I made the decision I made, what broke, what's still uncertain.
> This becomes the final writeup with light editing on Day 6.

---

## Project summary (for reference, don't edit)

**What it does:** Takes a batch of emails, triages them by real stakes (not just keywords)
into actionable / informational / time-sensitive / noise, explains its reasoning for each call,
drafts a tone-matched reply only after the user gives plain-English intent and explicitly
approves it (simulated send/schedule, no real Gmail integration), tracks tasks/deadlines in a
to-do list, and remembers sender patterns across sessions.

**4 concepts demonstrated:**
1. Tool/API integration — Gemini calls
2. Memory/context engineering — persistent sender patterns, local JSON/SQLite
3. Guardrails — never auto-sends, flags uncertainty instead of guessing
4. Agent skill — tone-matched drafting + light cross-email awareness within a batch

**Stack:** Python, Gemini API free tier, Kaggle Notebook, no deployment, no real Gmail OAuth.

**Deadline:** July 6, 2026, 11:59 PM PT.

**Future scope (mention, don't build):** MCP server integration for real Gmail/calendar access.

---

## Day 0 — Planning

- Defined scope and day plan (see above).
- Open risk flagged: "memory persists across sessions" needs a concrete definition for a
  Kaggle Notebook context (kernel restart vs. dataset reload vs. single execution). Decision
  pending — will resolve on Day 1.
- Open risk flagged: "triage by real stakes, not keywords" needs an honest technical story —
  likely LLM-judgment-driven via structured prompt, not a separate hand-built scoring algorithm.
  Need to decide and document this explicitly so the writeup doesn't overclaim.

---

## Day 0 — Decisions locked

- **Environment:** Build locally (Python + VS Code/terminal), port to Kaggle Notebook near the
  end for submission. Reasoning: no prior Kaggle experience + 6-day deadline means learning a new
  environment and building core logic at the same time is too risky. Local-first also matches the
  goal of pushing the project to GitHub as the source of truth, with Kaggle as the submission copy.
  This also resolves the "memory across sessions" ambiguity: locally it means a SQLite file that
  persists on disk across separate script runs. Will reconfirm Kaggle's working-dir persistence
  behavior when porting on Day 5/6 (commit DB as a Kaggle dataset if a kernel restart is needed).

- **Triage approach:** LLM judgment (Gemini) PLUS a small set of hand-built signal extractors
  (deadline/date mentions, sender history pattern, whether it's a reply to an already-tracked
  thread) that get passed into the prompt as structured context. Reasoning: pure-LLM-judgment is
  honest but thin as an engineering demonstration — a judge sees one API call doing all the work.
  Concrete signals feeding the LLM's reasoning is a more defensible "real stakes, not just
  keywords" story and isn't much extra code.

<!-- New entries go below this line -->

## Note for Day 5/6 — Kaggle porting checklist (don't forget)

- Swap `.env` / python-dotenv for Kaggle's "Secrets" add-on for the Gemini API key.
- Confirm internet access is enabled on the notebook (off by default in some cases) before
  expecting Gemini API calls to work.
- `/kaggle/working/` persists for the session but resets on a fresh session/kernel restart unless
  saved as a notebook version or attached as a Kaggle Dataset — if memory.db needs to survive
  that, plan to save it as a dataset, otherwise treat persistence as "within one notebook run."

<!-- New entries go below this line -->

## Day 1 — Correction: SDK package choice

- Initially planned to use `google-generativeai`. Checked current status before installing and
  found it's deprecated (legacy as of Aug 2025) in favor of the unified `google-genai` SDK.
  Switched immediately — different import pattern (`from google import genai`, client-object
  style via `genai.Client(api_key=...)` instead of module-level `genai.configure()`). Glad this
  was caught before writing code against the wrong package; worth a one-line mention in the
  writeup as an example of validating assumptions against current docs rather than memory/training
  data, which is itself a small "guardrail" instinct worth demonstrating.

<!-- New entries go below this line -->

## Day 1 — Model name verification

- Verified current Gemini free-tier model status before writing client code, given how fast
  model names churn (gemini-2.0-flash and 2.0-flash-lite were shut down June 1, 2026).
  Confirmed `gemini-2.5-flash` is current, stable, and still free-tier as of late June 2026 —
  going with this rather than chasing the newer gemini-3 preview family, which has murkier
  free-tier guarantees. Stability > novelty for a 6-day deadline.

<!-- New entries go below this line -->

## Day 1 — First successful Gemini API call

- Full pipeline confirmed working end-to-end: .env loaded correctly via python-dotenv, API key
  valid, google-genai client configured correctly, gemini-2.5-flash responded successfully to a
  test prompt on the first real run. No errors.
- Minor snag along the way: PowerShell blocked venv activation by default execution policy.
  Resolved with `Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned` — scoped to
  the current process only, not a machine-wide security change. Worth a one-line mention in the
  writeup's "setup notes" section since this trips up a lot of first-time Windows + venv users.
- Environment is now fully validated: Python 3.x, venv, google-genai, python-dotenv all working.
  Day 1 remaining task: build the realistic sample inbox dataset (data/sample_emails.json).

<!-- New entries go below this line -->

## Day 1 — Dataset expanded to realistic scale (77 emails)

- Original 18-email dataset felt too "clean" for a real triage stress test — categories were too
  obvious. Decided to expand to ~75-100 emails for realism, with new intricate patterns:
  - Sender-reputation vs. content conflicts (Prof. Reyes is usually FYI, but e037/e064 is a real,
    time-sensitive deadline — tests whether memory bias wrongly downgrades it)
  - Tone-vs-content conflicts (Maria Chen uses exclamation marks constantly as a personality
    trait, not urgency signal — tests whether the model overweights tone)
  - Keyword-loud noise vs. keyword-free real urgency (marketing spam shouting "URGENT" vs. a
    venue cancellation email with zero urgency keywords but genuinely high stakes)
  - Multi-message escalating threads (t001 venue crisis, t003 client pressure escalating to a
    near-miss with procurement review)
  - A buried/resolved-itself thread (t002) to test against over-flagging
  - Cross-sender duplicate real-world event awareness, deep reply chains, ambiguous terse tone
  - Final size: 77 emails, 44 unique senders, 15 repeat senders, 6 multi-message threads

- Budget/cost decision: rather than developing and testing triage logic against the full 77-email
  set (expensive in free-tier API calls during iterative prompt debugging), split into two files:
  `sample_emails.json` (full 77, for final demo/validation) and `sample_emails_dev.json` (19-email
  curated subset covering every tricky pattern, for cheap fast iteration during Day 2 prompt
  development). Develop against dev subset first; only run the full set once logic is stable.
  This directly addresses the free-tier rate limit risk flagged on Day 0.

- Caught and fixed a data-quality issue before it caused confusion: three thread replies (e064,
  e071, e074) initially had a thread_id but their original messages (e037, e012, e014) didn't,
  meaning thread matching would silently fail for those pairs. Considered building subject-line
  fallback matching as a way to demonstrate handling messy real-world thread data, but decided
  against it — extra engineering scope not worth it against the July 6 deadline with 4 concepts
  already committed. Backfilled clean thread_id pairs instead. Worth a one-line mention in the
  writeup as an example of deliberately scoping out a feature rather than letting "more realistic"
  quietly become "more work."

<!-- New entries go below this line -->

## Day 1 — COMPLETE

Final state at end of Day 1:
- Project structure: `src/`, `data/`, `docs/` set up, git initialized
- venv created and working (with PowerShell execution policy fix noted)
- Dependencies installed: `google-genai`, `python-dotenv` (correctly avoided the deprecated
  `google-generativeai` package after checking current status)
- `.env` holding API key, confirmed `.gitignore` excludes it from version control
- `src/gemini_client.py` written and tested — confirmed live call to `gemini-2.5-flash` works
- Dataset finalized: `data/sample_emails.json` (77 emails, full realistic set) and
  `data/sample_emails_dev.json` (19-email curated subset for cheap iteration)
- Both files validated as well-formed JSON with correct counts on the actual dev machine

All Day 1 goals from the original plan met. Ready to start Day 2: triage logic.

<!-- New entries go below this line -->

## Day 2 — Hit real free-tier rate limit, fixed with deliberate pacing

- First real run of triage.py against the 19-email dev set failed immediately with a 429
  RESOURCE_EXHAUSTED error. Actual limit: 5 requests/minute per model on the free tier (tighter
  than some older docs/blogs suggested -- confirms the Day 0 risk flag about free-tier quota was
  correct to take seriously).
- Fix: added a 13-second delay between sequential API calls in triage_batch (keeps us safely
  under 5 req/min), plus streaming progress output per email instead of waiting silently for the
  whole batch -- a 19-email run now takes ~4 minutes, which needs to be visible progress, not a
  black box.
- Worth noting in the writeup: this is a real, concrete example of a "guardrail" in a different
  sense than originally planned -- not just "guardrails against bad actions" but "guardrails
  against violating the service's own constraints," which matters for any agent making real API
  calls in a loop. Good demonstration material.
- Engineering note for later: this pacing strategy works for a 19-email dev run but will make the
  full 77-email batch take ~17 minutes. Acceptable for occasional full-batch validation runs, not
  for interactive use -- worth a one-line caveat in the final writeup's limitations section.

<!-- New entries go below this line -->

## Day 2 — Rate limit fix v2: retry-with-backoff added

- 15s spacing alone still wasn't enough margin -- hit a second 429 around email 7/19 even with
  13s delay. Added a proper retry-with-backoff wrapper (call_with_retry) that catches
  ClientError/RESOURCE_EXHAUSTED specifically and waits progressively longer (20s, 40s, 60s, 80s)
  before retrying, up to 4 attempts, rather than just guessing a bigger fixed delay. Bumped base
  spacing to 15s as well -- two layers of protection instead of one fragile fixed number.
- Reasoning quality observed in the partial run before the failure was genuinely strong evidence
  the prompt design is working: the model correctly distinguished "actionable" from
  "time-sensitive" with explicit citation of which evidence it used (e.g. recommendation letter
  email correctly flagged actionable specifically because a concrete document request was made,
  not just because a deadline existed). Good material to quote (paraphrased) in the final writeup
  as a worked example of grounded reasoning vs. keyword matching.

<!-- New entries go below this line -->

## Day 2 — Rate limit root cause confirmed via AI Studio dashboard

- Checked AI Studio's usage dashboard directly rather than guessing further. Confirmed: 8 total
  429 TooManyRequests errors, clustered tightly together during today's testing window -- pattern
  consistent with hitting the per-minute (RPM) cap repeatedly during rapid iterative testing
  (gemini_client.py test call + 3 separate triage.py attempts with retries, all in a short span),
  not daily quota (RPD) exhaustion. Decision: wait ~15-20 min for the per-minute window to clear
  rather than treat this as a daily-cap problem or stop for the day.
- Noted in passing: AI Studio's dashboard already tracks a "Gemini 3.5 Flash" model series
  alongside 2.5 Flash, which didn't surface clearly in earlier research -- flag to revisit if/when
  considering a model upgrade later, since the lineup is moving faster than expected.
- Practical lesson worth a line in the writeup: free-tier rate limits aren't just a "send slower"
  problem -- repeated failed attempts during debugging also count against the same quota, so
  aggressive iterative testing can compound the very problem it's trying to fix. Worth designing
  test/debug workflows to minimize redundant calls (e.g. test signal logic and parsing offline
  without hitting the API at all, which is what was done before any live triage.py run).

<!-- New entries go below this line -->

## Day 2 — STOPPED HERE, resume tomorrow

Current state at end of Day 2 session:
- `src/signals.py` complete and validated (offline, no API needed) -- near-term date detection
  and thread position detection both confirmed working correctly against known test cases.
- `src/triage.py` complete with: structured prompt design (signals + content, tone explicitly
  discounted as evidence), defensive JSON parsing (handles markdown-fenced responses and
  malformed output without crashing), and retry-with-backoff logic for rate limit handling.
- Live testing against the 19-email dev set hit free-tier RPM limits repeatedly. Confirmed via
  AI Studio dashboard this was a real per-minute quota collision from cumulative testing today
  (gemini_client.py test + 3 triage.py attempts), not a code bug. One email (e001, lecture room
  change) completed successfully before the limit hit, and the reasoning quality was strong --
  correctly identified time-sensitivity from an implicit "this week" window with no urgency
  keywords present, citing the actual consequence (wrong room) as justification.
- Decision: stop for the day rather than keep retrying against a tight per-minute window late in
  the session. Resume tomorrow with a fresh quota window, run a single clean test of
  `python -m src.triage` against the dev set, and actually review all 19 reasoning outputs
  together before deciding if the prompt needs iteration.

NOT YET DONE (carry to tomorrow):
- Full review of all 19 dev-set triage results for reasoning quality (only got 1/19 before rate
  limit hit -- need a clean run to evaluate this properly)
- Day 3 memory store: schema designed (SQLite, single `sender_history` table logging
  sender/category/confidence/timestamp per triage event) but not yet built. Key design decision
  already locked: memory must INFORM the LLM's reasoning as one signal among several, never
  override it outright -- this is what makes e037 (Prof. Reyes' real deadline despite mostly-FYI
  history) a meaningful test rather than something the system would auto-fail by design.
- Open question not yet resolved: should memory update automatically after every triage run, or
  only after some confirmation step? Tradeoffs not yet discussed -- pick this up tomorrow before
  writing memory_store.py.

<!-- New entries go below this line -->

## Day 2 — Switched model to gemini-2.5-flash-lite to resolve persistent rate limiting

- Even after waiting and reducing call frequency, hit a 429 on the very first request again --
  researched current limits more carefully and found gemini-2.5-flash's free tier RPM is tighter
  than initially assumed (sources converge around 10 RPM, with real-world reports of even lower
  effective throughput under load). Confirmed via error body that this was RPM-type (rate
  limited, recoverable in under a minute) rather than RPD-type (daily quota, recoverable only at
  midnight Pacific) -- the two return the same 429 status but different underlying cause.
- Decision: switch the triage model from gemini-2.5-flash to gemini-2.5-flash-lite. Flash-Lite's
  free tier gives meaningfully more headroom (~15 RPM / ~1000 RPD vs Flash's ~10 RPM / lower RPD).
  Classification/triage is a good fit for the lighter model -- this isn't open-ended reasoning or
  creative generation, it's structured categorization, so the quality tradeoff should be minimal.
  Considered alternatives: enabling Google Cloud billing for instant Tier 1 (30x RPM increase, no
  spend required) was a real option but rejected to keep the project entirely free/cardless per
  the original project constraints. Reduced batch delay from 15s to 6s accordingly, cutting full
  dev-set run time roughly in half.
- Worth a line in the final writeup: chose the cheaper/lighter model deliberately for the
  high-volume classification step rather than defaulting to the flagship model everywhere --
  matching model capability to task complexity is a real engineering decision, not just a
  workaround for rate limits.

<!-- New entries go below this line -->

## Day 2 — Flash-Lite confirmed fixing rate limits; new transient 503 handled

- Confirmed Flash-Lite switch resolved the 429 problem: emails 1-3 of the dev run completed with
  zero rate-limit hits. Also noticed a genuine, legitimate difference in judgment between models --
  Flash had called the lecture-room-change email "time-sensitive," Flash-Lite called the same
  email "informational." Both are defensible reads; this is a real example of triage involving
  actual judgment calls, not a single deterministic right answer, which is worth keeping in mind
  when evaluating outputs (and worth a line in the writeup about how "ground truth" for this task
  is inherently a bit fuzzy at the margins).
- Hit a new, different error: 503 UNAVAILABLE ("model currently experiencing high demand") on
  email 4. This is a distinct failure mode from 429 -- server-side overload on Google's
  infrastructure, not a client-side quota/rate issue -- plausible explanation is that free-tier
  lightweight models see more aggregate demand. The existing retry logic only caught ClientError
  (429-type) and correctly did NOT swallow this, since it wasn't built to handle it.
  Extended call_with_retry to also catch ServerError/503 with the same wait-and-retry pattern,
  logging which failure type triggered the retry for clearer debugging.
- Caught and fixed a leftover duplicate except/else block introduced while editing -- worth
  noting as a reminder to always compile-check generated code locally before handing it off,
  which is now a standing practice for every file in this project.

<!-- New entries go below this line -->

## Day 2 — Added checkpoint/resume so partial progress is never lost

- Sustained rate limiting persisted even on Flash-Lite -- worked cleanly for ~13 emails at 6s
  spacing, then hit a wall that survived 4 retries. Increased spacing to 12s for reliability over
  speed (a full 19-email run is now ~4 min, accepted as the real cost of the free tier).
- More importantly: realized re-running the whole batch from scratch after every failure was
  wasteful -- burning quota re-triaging emails that already had good results, on top of the
  emails that hadn't run yet. Added incremental checkpointing: results save to
  data/triage_results_checkpoint.json after every single email (not just at the end), and on
  re-run, already-completed email IDs are skipped automatically. Verified the skip/resume logic
  in isolation (no API needed) before relying on it live.
- This is a second concrete, demonstrable guardrail/reliability decision for the writeup: the
  system doesn't just retry on failure, it preserves all completed work across failures and
  reruns, which matters a lot for anything making metered real-world API calls.

<!-- New entries go below this line -->

## Day 2 — Diagnosed as likely RPD (daily quota) exhaustion, not RPM

- Checked AI Studio's usage dashboard again after a third consecutive run hit a wall that
  survived all 4 retries despite generous (12s) spacing. Dashboard showed ~20 successful requests
  to gemini-2.5-flash-lite today, against ~30 total errors (mix of 429 TooManyRequests and 503
  ServiceUnavailable), all concentrated in today's session.
- Concluded this is very likely RPD (requests per day) exhaustion rather than a pure RPM/pacing
  issue -- the pattern (failures persisting through long retry waits, regardless of delay tuning)
  matches RPD behavior described in research: recoverable only at daily reset (midnight Pacific),
  not by waiting minutes. Important realization: our own retry-with-backoff logic has likely been
  *consuming* daily quota while trying to recover from daily quota exhaustion -- each retry is
  itself a counted request. This is a genuine design lesson: retry logic tuned for transient
  per-minute limits can be counterproductive against a hard daily ceiling, since it can't
  distinguish between "wait a bit, it'll clear" and "you're done until tomorrow."
- Decision: stop testing for today. Resume tomorrow after the daily quota resets. No further code
  changes attempted today -- the code (model choice, pacing, retry logic, checkpointing) is
  believed correct; today's remaining failures are an exhausted resource, not a bug.
- Worth flagging as a genuine, non-trivial lesson for the final writeup: distinguishing RPM/transient
  failures from RPD/daily exhaustion matters architecturally. A more mature version of this system
  would ideally inspect the 429 error body for which specific quota dimension was exceeded (the
  API does return this in machine-readable form) and choose a different strategy accordingly --
  short backoff for RPM, hard stop with a clear message for RPD -- rather than treating all 429s
  the same way. Noted as a concrete "future improvement" for the writeup rather than something to
  build right now given the time budget.

<!-- New entries go below this line -->

## Day 2 — Added mock mode, smart RPD/RPM detection, and CLI flags to prevent repeat-blowups

Direct response to "what if the same thing happens tomorrow" -- three structural changes, all
free, all tested offline before relying on them:

1. **Smart quota error classification**: call_with_retry now inspects the actual error response
   text for which quota dimension was exceeded (RPM vs RPD), rather than treating every 429 the
   same. If it detects RPD (daily) exhaustion specifically, it raises immediately with a clear
   "stop, this resets at midnight Pacific" message instead of burning more retries (and more
   quota) against a wall that waiting won't clear. This directly fixes today's actual problem:
   our own retry logic was consuming quota while trying to recover from quota exhaustion.

2. **--mock mode**: a fully offline, zero-API-cost test path. call_with_retry_mock returns a
   plausible fake response so the entire pipeline (signal extraction, prompt building, JSON
   parsing, checkpointing, batch looping, CLI argument handling) can be exercised and verified
   with zero real requests. Verified working with no .env file and no API key present at all --
   genuinely zero dependency on live credentials. This should be the default way to test any
   future code changes to the plumbing before ever touching the real API again.

3. **CLI flags (--limit N, --fresh)**: lets you test against a small number of emails (e.g.
   --limit 3) before committing to a full 19-email run, and --fresh to deliberately discard a
   checkpoint when wanted. Combined with mock mode, this means iterating on code changes no
   longer requires spending any real quota at all until you're confident the logic is right.

Also made the Gemini client initialization lazy (only created on first real, non-mock call)
specifically so mock mode has zero dependency on an API key being present -- tested this
explicitly by removing .env entirely and confirming mock mode still runs end to end.

Decision for tomorrow: test with `python -m src.triage --limit 3` first (cheap sanity check that
today's daily quota has actually reset) before running the full 19-email batch. If a real
RPD-exhaustion error is hit, the script will now say so explicitly and stop immediately rather
than retrying uselessly.

<!-- New entries go below this line -->

## Day 2 — Built batched/grouped triage to handle 77 emails on free tier ($0, no billing)

- Decision point: full 77-email dataset, run multiple times across the project, was not
  realistically viable on free tier with one-API-call-per-email (calculated ~8 min minimum for a
  single clean run, and likely multiple full runs needed across Days 2-6 -- real risk of
  repeatedly hitting the same RPD wall from today). Considered enabling Google Cloud Tier 1
  billing ($10 prepay, capped, no auto-reload) as the lower-engineering-risk fix, but the user
  explicitly chose to stay at $0 and accept more engineering time instead -- respecting that
  decision and building it properly rather than half-heartedly.
- Built grouped/batched triage: instead of one API call per email, group_size emails (default 5)
  go into a SINGLE prompt, and the model returns a JSON ARRAY of results instead of one object.
  This cuts request count ~5x -- 77 emails becomes 16 calls instead of 77, bringing both RPM and
  RPD pressure down to a level that should comfortably support multiple full-dataset runs across
  the remaining days without hitting today's walls.
- Designed specifically around the real risk this approach introduces (one bad response can now
  affect multiple emails, not just one): parse_batch_response matches results back to emails by
  email_id (not array position, which the model could get out of order), and any email_id that's
  missing or unparseable from the response falls back to an individually-flagged "informational +
  parse error" result rather than being silently dropped or corrupting a sibling email's result.
  Verified directly: ran the full 77-email dataset in mock mode and confirmed all 77 got results
  with zero drops.
- Checkpointing extended to work at the GROUP level for API calls but EMAIL level for resume
  granularity -- if a crash happens after group 9 of 16, re-running skips all 45 emails already
  covered by groups 1-9, not just whatever email happened to be processing during the crash.
  Verified this resume behavior directly with a simulated partial checkpoint.
- Caught and fixed a real bug during this work before it reached the user: an early edit
  accidentally deleted the original single-email triage_email function while leaving its caller
  intact, which would have caused a NameError at runtime. Caught via grep + view inspection before
  sending the file, not by the user hitting it live -- reinforces the value of compiling AND
  grep-checking function definitions after multi-part edits, not just syntax-checking.
- Also fixed: --mock mode initially only knew how to fake a single JSON object, not a JSON array,
  so testing grouped mode in mock initially (correctly) flagged every result as a parse error --
  which was actually the safety net working as designed, but meant mock mode couldn't exercise the
  happy path for the new grouped code. Updated the mock to detect batched vs single prompts via a
  structural marker and shape its fake response accordingly.
- New CLI flags: --grouped (opt into batched mode), --group-size N (default 5), --full (use the
  full 77-email dataset instead of the 19-email dev subset). All composable with existing --mock,
  --limit, --fresh flags.
- This is good material for the writeup: a genuine, deliberate architecture decision to keep the
  project free, with explicit engineering tradeoffs considered and designed around (graceful
  degradation per-email, ID-based matching instead of positional, extended checkpointing) rather
  than just "batch the calls" as a vague idea.

<!-- New entries go below this line -->

## Day 2 — Fixed real bug: mock checkpoint silently blocked a live run

- User ran a mock test (correctly, as instructed) then immediately ran a live --grouped command.
  The live run printed "Resuming from checkpoint: 19 emails already triaged" and returned mostly
  fake [MOCK MODE] results with zero real API calls made -- the checkpoint system didn't
  distinguish between mock and live results, so the mock run's fake data silently satisfied the
  live run's "is this email already done?" check.
- Root cause: checkpoint entries had no marker of which mode produced them. Fix: every result
  (single-email and grouped paths both) now carries a "mock": true/false tag. Checkpoint-loading
  logic in both triage_batch and triage_dataset_grouped now only trusts entries whose mock flag
  matches the CURRENT run's mode -- a mock checkpoint is invisible to a live run and vice versa.
  Older checkpoint entries from before this fix (no "mock" key at all) are also treated as
  untrusted, forcing a clean rerun rather than risking a silent mismatch.
- Verified the fix directly: ran mock twice (second run correctly resumes from mock checkpoint),
  then simulated what a live run's checkpoint-loading would see against that same mock checkpoint
  -- confirmed it correctly trusts 0 entries, forcing a full fresh real run as expected.
- Genuinely good lesson for the writeup: testing infrastructure itself (the --mock flag) can
  introduce its own class of bugs if it isn't clearly separated from the real data path. A
  zero-cost testing tool is only safe if it can't be mistaken for, or silently merge with, real
  results -- worth a line about this as a guardrail-adjacent lesson, not just a bugfix.

<!-- New entries go below this line -->

## Day 2 — Confirmed real RPD limit: 20/day for gemini-2.5-flash-lite. Increased group size.

- Live test of --grouped mode hit a 429 on group 1 -- but critically, this time the system
  worked exactly as designed: caught a transient 503 first (retried correctly), then hit a 429,
  classified it as RPD via the error body, and raised a clear "DAILY QUOTA EXHAUSTED, resume
  tomorrow" message instead of burning retries pointlessly. This is the smart error handling
  built earlier tonight working correctly on its first real test.
- The error response gave a concrete, confirmed number for the first time: 'quotaId':
  'GenerateRequestsPerDayPerProjectPerModel-FreeTier', 'quotaValue': '20' -- the real RPD limit
  for gemini-2.5-flash-lite on this project is 20 requests/day, not the 100-250 estimated from
  general research earlier. This explains why even the 19-email/4-call grouped run on a "fresh"
  daily quota still failed -- prior testing earlier the same day had already used some of the 20.
- Recalculated batching math against this confirmed number: group_size=5 gets the full 77-email
  dataset to 16/20 calls in one run -- technically fits, but leaves almost no margin for retries
  or re-running the same day. Increased default group_size to 10, bringing the full dataset to
  just 8/20 calls, leaving 12 calls of real margin (room for a retry, a partial dev-set check, or
  a second pass the same day). Verified in mock mode that group_size=10 still correctly chunks 77
  emails into 8 groups and all 77 still get results with zero drops -- the per-email_id matching
  safety net holds even with more emails packed into each single response.
- Honest risk noted but accepted: larger groups (10 emails per prompt) mean more content for the
  model to track per response, theoretically raising the chance of a formatting slip in the JSON
  array. Decided this is an acceptable tradeoff given the alternative (running out of daily quota
  before finishing the full dataset) is strictly worse, and the existing parse_batch_response
  safety net (ID-based matching, graceful per-email degradation) already exists specifically to
  handle this case if it occurs.

<!-- New entries go below this line -->

## Day 2 — Built fully automatic end-to-end run (no manual re-running needed)

- Real test against the full 77-email dataset (after midnight quota reset) confirmed: RPD is no
  longer the blocker (quota reset correctly), but sustained 503 ServerError ("model experiencing
  high demand") was hitting nearly every group, sometimes 3-4 consecutive overload responses in a
  row before clearing. Checkpoint/resume worked correctly across two manual re-runs (40/77 emails
  completed cleanly across groups 1-4), but the user reasonably wants this to run in one go
  without manually re-typing the command every time a group's retries are exhausted.
- Built an outer auto-resume loop in the CLI entry point: if the entire triage run dies with a
  RuntimeError (meaning even call_with_retry's internal retries were exhausted by a long 503
  streak), the outer loop automatically waits 60s and re-invokes the same run, up to 5 outer
  attempts total. Because checkpointing already preserves completed work at email-level
  granularity, each re-invocation only redoes whatever didn't finish -- this required no change
  to the checkpoint logic itself, just wrapping the existing safe-resume behavior in automatic
  retry rather than requiring the user to do it by hand.
- Critically: RPD "daily quota exhausted" errors are explicitly excluded from this auto-retry --
  detected via the same error-message check used elsewhere, and the outer loop stops immediately
  with SystemExit(1) rather than wasting 5 outer attempts (and real wall-clock time) retrying
  against a wall that literally cannot clear until midnight. Verified this distinction in isolated
  tests: a sustained-failure-then-success scenario correctly retries through to completion, while
  a simulated RPD error correctly stops after exactly one attempt with no wasted retries.
- Also increased call_with_retry's own resilience (max_retries 4->7, wait capped at 90s rather
  than multiplying unboundedly) and added more spacing between groups (8s->15s) to reduce the
  frequency of hitting sustained overload streaks in the first place, not just react better when
  they happen.
- This is good material for the writeup under "guardrails" / reliability: the system now
  distinguishes between "transient, worth automatically working through" and "structural, stop
  and tell the human" failures at TWO levels (per-call retry, and whole-run auto-resume), rather
  than treating every failure the same way. That's a meaningfully more mature reliability design
  than where this started (a single try with no retry logic at all, on Day 2's first attempt).

<!-- New entries go below this line -->

## Day 2 — COMPLETE. Full 77-email triage run succeeded after Tier 1 billing enabled.

- Tier 1 billing set up (pay-per-request, prepay $10, auto-reload off). Same API key, no code
  changes needed -- the key was already in .env, just needed the account tier upgraded. Total
  actual cost for the full 77-email run: fractions of a cent.
- Full 77-email triage completed cleanly in one run, resuming from the 40-email checkpoint
  already saved from earlier partial runs. Groups 5-8 completed without any RPD wall (confirmed
  the Tier 1 upgrade worked immediately). Some 503 transient overloads still occurred but the
  retry logic handled them without crashing.
- Reasoning quality assessment (human review):
  - Strong calls: e007 (social notifications correctly NOISE despite "URGENT!!!"), e022 (casual
    conference follow-up correctly NOISE), e037 (Prof. Reyes recommendation letter correctly
    TIME-SENSITIVE despite mostly-FYI sender history -- content correctly overrode pattern),
    e042 (bank security alert correctly ACTIONABLE), e072 (product recall correctly ACTIONABLE)
  - One clear failure: e015 ("URGENT URGENT URGENT - Last chance pricing") got TIME-SENSITIVE
    instead of NOISE -- the model correctly ignored the tone/caps but was still fooled by a
    real-sounding "prices go up tomorrow" deadline claim in obvious spam. Honest limitation:
    the prompt discounts tone as evidence but can't easily distinguish a real deadline claim
    from a fabricated one in marketing copy. Worth a line in the writeup as a known edge case.
  - Two parse errors: e013 (Scheduled maintenance) and e023 (Contract draft) were missing from
    their batch's JSON response -- flagged correctly by parse_batch_response rather than silently
    misfiled. Likely caused by the model truncating a long response under server load. The safety
    net worked as designed; these two emails need manual triage.
  - Overall: ~74/77 correct or defensible calls. Strong enough to build Day 3 on.

Day 2 real deliverable: triage logic working, prompt design validated at full dataset scale,
all engineering infrastructure (checkpointing, retry, mock mode, auto-resume, mock/live
separation) battle-tested against real-world failures and confirmed solid.

<!-- New entries go below this line -->

## Day 2 — Triage Results Narrative (for final writeup)

The triage system was run against the full 77-email dataset using gemini-2.5-flash-lite with a
structured prompt that explicitly instructed the model to judge emails by real stakes rather than
surface-level tone or keywords. Out of 77 emails, roughly 74 were triaged correctly or with
defensible reasoning. The strongest results came from exactly the cases the system was designed
for: emails that looked urgent but weren't (e.g., "URGENT: You have 3 new notifications!!!" from
a social network was correctly classified as noise despite the all-caps subject), emails that
carried real stakes without any urgency language (e.g., the venue cancellation email and the lease
renewal follow-up were both correctly flagged as actionable despite being written in calm, plain
language), and emails where sender history should theoretically bias toward "informational" but
the content itself warranted overriding that (Prof. Reyes' recommendation letter deadline was
correctly flagged as time-sensitive despite his other 9 emails in the dataset being routine FYI
updates). The system also correctly handled a multi-message thread -- recognizing that the client
contract pressure thread was escalating across three messages and flagging each one at the
appropriate urgency level. Two emails (e013 and e023) produced parse errors, meaning the model
dropped them from its batch JSON response, likely due to server load causing a truncated output
-- these were caught and flagged for manual review by the safety net rather than silently
misfiled, which is the designed guardrail working correctly. One genuine misclassification
occurred: e015 ("URGENT URGENT URGENT - Last chance pricing") was classified as time-sensitive
instead of noise. The model correctly ignored the tone (all-caps, triple "URGENT") but was still
fooled by a fabricated "prices go up tomorrow" deadline claim -- a real limitation of LLM-based
triage, since the model cannot verify whether a stated deadline is genuine or manufactured. This
is a known edge case that Day 3's sender memory partially addresses (building a "mostly noise"
reputation for that sender over time), and is worth documenting as a limitation rather than
pretending it didn't happen.

<!-- New entries go below this line -->

## Day 2 — Detailed failure analysis: the 3 problematic emails

### e015 — "URGENT URGENT URGENT - Last chance pricing" (wrong category: TIME-SENSITIVE instead of NOISE)

**What happened:** The model correctly ignored the tone signals (triple "URGENT", all-caps,
exclamation marks) -- which is exactly what the prompt instructed it to do. But it was still
fooled by the email's content claiming "prices go up tomorrow." That's a real-sounding deadline
statement, and the model treated it as genuine evidence of time-sensitivity.

**Why it happened:** The prompt tells the model "tone is not evidence" -- but it doesn't tell the
model "claimed deadlines from unknown senders should be treated skeptically." The model has no way
to verify whether "prices go up tomorrow" is a real constraint or a manufactured one. It took the
claim at face value, which is the wrong call for obvious spam.

**Future fix:** Two concrete solutions. First, sender reputation from memory (Day 3) -- once
`promo@dealsdealsdeals.com` has accumulated a history of "noise" classifications, the prompt can
include that context and the model can weigh a deadline claim from a known-noise sender
differently than the same claim from a trusted sender. Second, a domain trust signal in the
signal extractor -- flagging senders whose domain looks like a bulk marketing domain
(dealsdealsdeals.com) as "low-trust source," which would be passed into the prompt alongside the
other structured signals. Neither is a perfect fix, but together they significantly reduce the
chance of this class of false positive.

---

### e013 — "Scheduled maintenance Sunday 2-4am" (parse error: missing from batch response)
### e023 — "Contract draft attached" (parse error: missing from batch response)

**What happened:** Both emails were included in their respective batch prompts (groups of 10
emails sent to Gemini in one call), but were absent from the model's JSON array response. The
model returned a valid JSON array, just with fewer items than expected -- it silently dropped
these two emails from its output. The parse_batch_response function detected the missing email_ids
and correctly flagged both as parse errors rather than silently misfiling them or crashing.

**Why it happened:** Most likely cause is response truncation under server load -- both groups
had multiple 503 "server overloaded" retries before eventually succeeding, and a model under
strain may produce a shorter-than-expected output that cuts off before covering all 10 emails in
the batch. A secondary possible cause is prompt length: with 10 emails packed into one prompt,
the total input is long, and the model may occasionally "forget" to include all requested outputs
in its response. This is a known risk of the batching approach that was explicitly flagged when
the architecture was designed.

**Future fix:** Three options, in order of implementation effort. First (easiest): detect when
the returned array is shorter than expected and automatically retry just those missing email_ids
as a small separate call -- the email_id-based matching already in parse_batch_response makes
this straightforward to implement. Second: reduce batch group_size from 10 to 7-8 when server
load indicators (multiple 503 retries on prior groups) suggest the model is under strain.
Third (most robust): move to individual calls for any email that fails in a batch, using the
batch as the fast path and the single-call as the fallback -- this already exists in the codebase
as triage_email(), so it's a matter of wiring it in as a retry path rather than building
something new. For the capstone, the current behavior (flagged for manual review rather than
wrong) is acceptable; in a production system the first fix would be the minimum standard.

<!-- New entries go below this line -->

## Day 2 — Clean triage narrative (final writeup version)

### What the system does

The triage system reads a batch of emails and classifies each one into exactly one of four
categories: actionable (you need to do something specific), time-sensitive (there's a real
deadline even if no action is spelled out yet), informational (useful to know but nothing to do),
or noise (marketing, automated alerts, low-value content). For each email, it also writes a
plain-English explanation of why it made that call.

The system first extracts three concrete signals from each email before calling Gemini: whether
the email body contains near-term time language (words like "by Friday," "tomorrow," "deadline"),
what position the email sits in a thread (first message, follow-up, or final resolution), and
what the sender's historical pattern looks like. These signals are passed into the prompt
alongside the email content, giving the model structured evidence to reason from rather than
asking it to guess from tone alone. The prompt explicitly instructs the model to judge by real
stakes, not surface signals -- an email full of exclamation marks or the word "URGENT" is not
automatically urgent, and a calm plainly-worded email can carry real stakes.

### What worked well (74/77 emails)

- Loud emails that were actually noise: "URGENT: You have 3 new notifications!!!" correctly
  classified as noise -- model ignored all-caps and judged actual content (a like, a follow) as
  low-stakes automated alerts.
- Quiet emails that were genuinely urgent: venue cancellation email written in plain calm language
  with zero urgency keywords correctly flagged as actionable because the actual situation carries
  real stakes.
- Sender history vs. content conflict: Prof. Reyes (9 FYI emails, 1 real deadline) -- the
  recommendation letter email correctly flagged as time-sensitive despite his mostly-FYI history.
  This is the most important test: confirms the model doesn't learn "Prof. Reyes = ignore."
- Escalating threads: client contract pressure thread (3 emails, escalating stakes) handled
  correctly across all three messages, each flagged at the appropriate urgency level.
- Tone vs. content: Maria Chen writes everything with exclamation marks -- casual review request
  correctly classified as noise despite enthusiastic tone.

### What failed (3 emails)

e015 -- "URGENT URGENT URGENT - Last chance pricing" -- got TIME-SENSITIVE instead of NOISE.
Model correctly ignored tone but was fooled by "prices go up tomorrow" claim. Root cause: the
prompt discounts tone but doesn't tell the model to treat deadline claims from unknown/low-trust
senders skeptically. Future fix: sender memory (Day 3) + domain trust signal in the extractor.

e013 and e023 -- parse errors (dropped from batch response). Both emails were in their batch
prompts but absent from the model's JSON array response. Root cause: response truncation under
server load -- both groups had multiple 503 retries before succeeding, and a model under strain
may cut output short. The safety net caught them and flagged for manual review rather than
silently misfiling. Future fix: detect short arrays and retry missing email IDs as a separate
call -- the infrastructure for this already exists in triage_email().

### Overall verdict

74/77 correct or defensible. 2 parse errors caught by safety net. 1 genuine misclassification
with a clear root cause and concrete fix path. Strong result for a first-pass system on a
deliberately tricky dataset, and the failures are more useful than a perfect score -- they point
directly at what the system needs next (sender memory, domain trust signals, fallback retry for
dropped batch items).

<!-- New entries go below this line -->

## Day 3 — Memory store built and integrated

- Built src/memory_store.py: SQLite-backed persistent sender pattern memory.
  Schema: one row per confirmed triage event (sender_email, email_id, subject,
  category, confidence, confirmed_at) -- stores full history rather than a rolling
  summary, so richer pattern queries are possible later if needed.
- Key functions: initialize_db (creates table if not exists, safe to call every run),
  confirm_batch_results (writes a batch of confirmed results in one transaction,
  skipping parse errors), get_sender_pattern (returns structured pattern summary
  for a given sender -- "always informational", "usually noise", etc.),
  get_all_sender_patterns (full memory state for display), clear_sender_history
  (reset a sender's learned pattern if it's wrong).
- Design decision confirmed: memory updates only on EXPLICIT user confirmation,
  not automatically. parse_error results are explicitly skipped even in batch
  confirmation -- we don't learn from calls the model itself flagged as uncertain.
- Wired into signals.py: sender_history() stub replaced with a real memory lookup.
  When a MemoryStore instance is passed in, signals now include the actual pattern
  from the database rather than "no history yet."
- End-to-end integration test passed: confirmed 4 Prof. Reyes emails as
  informational, then ran signals on a new email from him -- sender_history correctly
  showed "always informational (4/4)" while has_near_term_date correctly flagged
  the Monday deadline. Both signals feed into the prompt, creating the intended
  tension: memory says informational, content says urgent -- LLM has to weigh both.
  Day 2 results confirmed it correctly sides with content in this case.

<!-- New entries go below this line -->

## Day 3 — Confirmation step built (the guardrail bridge between triage and memory)

- Built src/confirm.py: the module that lets the user review triage results and
  explicitly confirm them into memory before anything gets written to sender_memory
  table. This is the human-in-the-loop guardrail that keeps memory accurate.
- Three confirmation modes:
  1. Interactive (default): walks through each result one at a time, user presses
     Enter to confirm, 's' to skip, 'q' to stop and save what's confirmed so far.
     Low-confidence results get an extra warning, medium-confidence get a flag.
  2. --all: confirms all high/medium-confidence results automatically, skipping
     parse errors and low-confidence results. For when the user trusts the full run.
  3. Parse errors are always skipped in both modes -- never learn from uncertain calls.
- Additional CLI flags: --show-memory (display full memory state), --clear EMAIL
  (reset a specific sender's history if it's wrong).
- Design note worth including in writeup: the confirmation step isn't just a UX
  nicety -- it's an architectural decision about where human judgment sits in the
  pipeline. The agent classifies, the human verifies, then memory updates. This
  ordering means memory can only ever be as wrong as the human allows it to be,
  not as wrong as the model's worst call.

<!-- New entries go below this line -->

## Day 3 — COMPLETE. Memory wired in, full run with sender history active.

- Final fix: memory_store was built and confirmed.py was working, but triage.py's CLI entry
  point was still passing memory_store=None to triage_dataset_grouped. Added a MemoryStore
  wrapper class in the __main__ block that initializes the SQLite DB and passes get_sender_pattern
  lookups into every triage call. Now every email's signals include real sender history from
  data/memory.db rather than "no history yet."

- Second full 77-email run with memory active completed successfully (resumed from group 5
  checkpoint after another 503 on group 4, then ran cleanly groups 5-8). 503 server overload
  errors continue to be a persistent nuisance but the retry/resume infrastructure handles them.

- Memory impact assessment (honest):
  - Positive: e003 (ACT NOW Flash Sale) correctly reclassified from TIME-SENSITIVE to NOISE --
    the model re-evaluated events@trendybrand.com's content more skeptically with memory context.
  - Neutral/expected: most results consistent with run 1, which is correct behavior -- memory
    should inform, not override, and when content is unambiguous the model correctly ignores the
    pattern signal.
  - Persistent failure: e015 still TIME-SENSITIVE despite promo@dealsdealsdeals.com having a
    mixed noise/informational pattern in memory. Memory alone doesn't fix the "fabricated deadline
    claim" problem -- would need domain trust signal or stronger prompt instruction to address.
  - Parse errors: e013 and e023 continue to get dropped from their batch responses. This appears
    to be specific to those emails' position in their groups, possibly content-length related.
    Worth noting as a known persistent issue; the safety net correctly flags them each time.

- Day 3 deliverables confirmed:
  1. SQLite memory store persisting sender patterns across runs (data/memory.db, 43 senders)
  2. Confirmation step (confirm.py) requiring explicit human approval before memory updates
  3. Memory feeding into triage signals on every subsequent run
  4. --show-memory flag for inspecting what the agent has learned
  5. --clear flag for resetting wrong patterns

<!-- New entries go below this line -->

## Day 4 — Drafting module built with tone-matching and guardrails

Built src/drafting.py with the following design:

**Tone-matching:** the prompt instructs Gemini to analyze the original email's tone
and mirror it in the reply -- formal gets formal, casual gets casual, urgent/terse
gets direct. The user's intent drives the content, the original email's tone drives
the style. This is what "tone-matched drafting" means in the project description.

**Guardrails (the core Day 4 concept):**
1. Never drafts without being explicitly asked -- no auto-draft on triage
2. Pre-checks intent for obvious vagueness before spending an API call (catches
   "just reply", "you decide", "ok", single-word responses)
3. If the LLM itself determines intent is ambiguous even after the pre-check,
   returns a clarification request instead of a draft -- asks one specific question
4. Presents draft for human review before anything happens
5. Only after explicit "approve" does simulate_send() run
6. simulate_send() logs to data/sent_log.json -- never touches real Gmail, never
   makes real network calls to a mail server. The "simulated" flag is always True.
7. User can edit intent and redraft before approving -- approval is never forced

**Flow:** pick email → give intent → pre-check intent → draft → review →
approve/edit/reject → if approved, simulate send and log.

<!-- New entries go below this line -->

## Day 4 — COMPLETE. Drafting + guardrails working end to end.

Built src/drafting.py and src/main.py. Full agent flow now works from one command:
python -m src.main

Drafting guardrails confirmed working:
1. Vague intent ("just reply") caught by detect_ambiguous_intent() BEFORE any API call
2. Clarification requested with a specific useful question
3. Real intent → draft → review → explicit approve → simulated send logged
4. simulate_send() logs to data/sent_log.json, never touches real email infrastructure

Tone-matching issue and fix:
- First prompt attempt: model detected "urgent/terse" from deadline context and produced
  a one-line reply ("Will send by Sunday morning.") -- technically followed the tone
  instruction but wrong in practice since Prof. Reyes's email is politely worded, not terse
- Root cause: prompt conflated urgency of SITUATION with urgency of WRITING STYLE
- Fix: removed "urgent/terse" as a valid tone_detected value entirely, added explicit
  rules requiring minimum greeting + 2-3 sentence body + sign-off, and explicitly stated
  that deadline urgency does not mean terse writing style
- After fix: "Dear Professor Reyes, Thank you for your prompt reply..." -- correct formal
  tone, proper structure, sounds like a real reply a person would send

main.py -- the unified agent entry point:
- Single command: python -m src.main
- Shows inbox grouped by category (time-sensitive first)
- Pick any email by number to see full details + reasoning + sender memory
- Actionable/time-sensitive emails offer [d]raft reply option
- Informational/noise show "no reply needed" and go back
- [c] confirms all results to memory, [q] quits
- This is what makes the project an "agent" rather than a collection of scripts

<!-- New entries go below this line -->

## Day 5 — COMPLETE. Polish fixes confirmed working.

Two must-fix items addressed:

1. [Your Name] placeholder replaced with real user name -- main.py now asks for
   the user's name at startup and passes it through to drafting_flow -> draft_reply
   -> the prompt template. Sign-off confirmed showing real name ("Loki") in live test.

2. Inbox reprint on every navigation fixed -- added clear_screen() call (cls on
   Windows, clear on Mac/Linux) at the top of the main loop so the screen clears
   cleanly between views instead of scrolling the full 77-email list repeatedly.

Confirmed working end to end:
- Name prompt at startup
- Clean screen on navigation
- Proper formal draft with greeting, body, sign-off using real name
- Simulated send logged to data/sent_log.json

Day 5 deliberately kept minimal -- the agent is working correctly and the remaining
time is better spent on writeup and video than adding new features.

<!-- New entries go below this line -->
