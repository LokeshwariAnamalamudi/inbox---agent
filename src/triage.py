"""
triage.py

Takes an email + its extracted signals, asks Gemini to classify it into one of:
actionable / informational / time-sensitive / noise, with a plain-English reason.

Key design choice: the LLM is told the signals explicitly and instructed not to be
fooled by tone alone (e.g. exclamation marks, ALL CAPS, the word "URGENT") when the
underlying content doesn't actually warrant it. This is what makes the triage
"real stakes, not just keywords" rather than a glorified keyword scanner.
"""

import json
import os
import time
from google import genai
from google.genai import errors as genai_errors
from dotenv import load_dotenv

from src.signals import extract_signals

load_dotenv()
_client = None

def get_client():
    """
    Lazily initializes the Gemini client only when actually needed for a real (non-mock) call.
    This means --mock mode works with zero API key required -- useful for testing on a machine
    without .env set up, or deliberately avoiding any chance of a real call during pure plumbing
    tests.
    """
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client

MODEL = "gemini-2.5-flash-lite"  # switched from gemini-2.5-flash: free tier gives ~15 RPM /
                                  # 1000 RPD on Flash-Lite vs ~10 RPM / lower RPD on standard Flash.
                                  # Classification/triage doesn't need Flash's full reasoning power,
                                  # so this trade is essentially free.

CATEGORIES = ["actionable", "informational", "time-sensitive", "noise"]

TRIAGE_PROMPT_TEMPLATE = """You are triaging a single email into exactly one category, based on REAL stakes -- not surface-level keywords or tone.

Categories (pick exactly one):
- "actionable": the recipient needs to do something specific (reply, decide, send a document, make a payment, etc.)
- "time-sensitive": there's a real deadline or window that matters, even if no specific action is spelled out yet
- "informational": useful to know, but truly no action or deadline is implied
- "noise": marketing, automated notices, or low-value content with no real relevance

IMPORTANT: Tone is not evidence. An email full of exclamation marks or the word "URGENT" is not automatically urgent.
A calm, plainly-worded email can carry real stakes. Judge based on the actual content and the structured signals below,
not the way it's written.

EMAIL:
From: {sender}
Subject: {subject}
Body: {body}

STRUCTURED SIGNALS (extracted separately, treat as evidence):
- Contains near-term time language (today/tomorrow/by Friday/deadline etc.): {has_near_term_date}
- Sender history: {sender_history}
- Thread position: {thread_position}

Respond ONLY with valid JSON, no markdown formatting, no backticks, in exactly this shape:
{{
  "category": "<one of: actionable, time-sensitive, informational, noise>",
  "reasoning": "<one or two plain-English sentences explaining the call, referencing the actual evidence used>",
  "confidence": "<low, medium, or high>"
}}
"""


def build_prompt(email: dict, signals: dict) -> str:
    return TRIAGE_PROMPT_TEMPLATE.format(
        sender=email["from"],
        subject=email["subject"],
        body=email["body"],
        has_near_term_date=signals["has_near_term_date"],
        sender_history=signals["sender_history"],
        thread_position=signals["thread_position"],
    )


def parse_triage_response(raw_text: str) -> dict:
    """
    Parses the model's JSON response defensively. Gemini occasionally wraps JSON in
    markdown fences despite instructions not to -- strip those before parsing.
    Falls back to a clearly-flagged error result rather than crashing, since a single
    malformed response shouldn't take down a whole batch run.
    """
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    cleaned = cleaned.strip()

    try:
        result = json.loads(cleaned)
        if result.get("category") not in CATEGORIES:
            raise ValueError(f"Unexpected category: {result.get('category')}")
        return result
    except (json.JSONDecodeError, ValueError) as e:
        return {
            "category": "informational",  # safe default, never silently drop an email
            "reasoning": f"PARSE ERROR -- flagged for manual review. Raw model output: {raw_text[:200]}",
            "confidence": "low",
            "parse_error": str(e),
        }


def classify_quota_error(error_str: str) -> str:
    """
    Inspects the error message text for which quota dimension was actually exceeded.
    Google's error responses include a 'quotaId' field that names the specific limit hit
    (e.g. 'GenerateRequestsPerDayPerProjectPerModel-FreeTier' vs '...PerMinute...'). Distinguishing
    these matters: an RPM hit clears in under a minute, but an RPD hit won't clear until midnight
    Pacific no matter how long you wait -- retrying against it just burns more of tomorrow's
    quota for nothing, since failed attempts still count as requests.
    """
    lowered = error_str.lower()
    if "perday" in lowered or "requestsperday" in lowered:
        return "RPD"  # daily cap -- retrying will not help today
    if "perminute" in lowered or "requestsperminute" in lowered:
        return "RPM"  # per-minute cap -- short wait should clear it
    return "UNKNOWN"


def call_with_retry(prompt: str, max_retries: int = 7, base_wait: float = 15.0, max_wait: float = 90.0):
    """
    Calls Gemini with retry logic covering two distinct failure modes:
    - 429 ClientError (RESOURCE_EXHAUSTED): rate or quota limit. Inspects the error body to tell
      RPM (per-minute, worth retrying) from RPD (daily, NOT worth retrying -- raises immediately
      with a clear message instead of burning more quota on guaranteed-to-fail attempts).
    - 503 ServerError (UNAVAILABLE): Google's infrastructure overloaded server-side, unrelated to
      your own quota. Always worth retrying -- observed in practice that flash-lite can have
      sustained overload streaks of 3-4+ consecutive 503s, so max_retries is set higher than the
      RPM case needs, with wait time capped (not unboundedly multiplying) so a long retry sequence
      doesn't spiral into multi-minute waits per attempt.
    """
    for attempt in range(max_retries):
        try:
            return get_client().models.generate_content(model=MODEL, contents=prompt)
        except genai_errors.ClientError as e:
            error_str = str(e)
            if "RESOURCE_EXHAUSTED" in error_str or "429" in error_str:
                quota_type = classify_quota_error(error_str)
                if quota_type == "RPD":
                    raise RuntimeError(
                        "DAILY QUOTA EXHAUSTED (RPD). Waiting will not help -- this resets at "
                        "midnight Pacific time. Stop and resume tomorrow. Completed results so "
                        "far are saved in the checkpoint file and will not be lost."
                    ) from e
                wait = min(base_wait * (attempt + 1), max_wait)
                print(f"  [rate limit (429, {quota_type}) -- waiting {wait:.0f}s before retry {attempt + 1}/{max_retries}]")
                time.sleep(wait)
            else:
                raise
        except genai_errors.ServerError as e:
            if "UNAVAILABLE" in str(e) or "503" in str(e):
                wait = min(base_wait * (attempt + 1), max_wait)
                print(f"  [server overloaded (503) -- waiting {wait:.0f}s before retry {attempt + 1}/{max_retries}]")
                time.sleep(wait)
            else:
                raise  # not a transient overload, don't swallow it
    raise RuntimeError(f"Failed after {max_retries} retries due to repeated rate limiting or server overload.")


def call_with_retry_mock(prompt: str, **kwargs):
    """
    Zero-cost stand-in for call_with_retry, used in --mock mode. Returns a plausible fake
    response so the rest of the pipeline (parsing, checkpointing, batch looping) can be tested
    without spending a single real API call. Detects whether this is a single-email or batched
    (multi-email) prompt based on a marker in the template, and shapes the fake response to match
    -- a JSON object for single, a JSON array for batched -- since the two parsers expect
    different shapes and a mismatch should be caught here, not surfaced as a confusing parse
    error during testing.
    """
    class FakeResponse:
        def __init__(self, text):
            self.text = text

    def guess_category(text_block: str) -> str:
        lowered = text_block.lower()
        if "no action needed" in lowered or "fyi" in lowered:
            return "informational"
        elif "deadline" in lowered or "by friday" in lowered or "by monday" in lowered:
            return "actionable"
        elif "urgent" in lowered or "act now" in lowered:
            return "noise"  # mock deliberately mirrors the "tone isn't evidence" rule
        return "informational"

    if "--- EMAIL " in prompt:
        # Batched prompt: extract each email_id and its block, return a JSON array
        import re
        blocks = re.split(r"--- EMAIL (\S+) ---", prompt)[1:]  # alternating: id, content, id, content...
        results = []
        for i in range(0, len(blocks), 2):
            eid = blocks[i]
            content = blocks[i + 1] if i + 1 < len(blocks) else ""
            results.append({
                "email_id": eid,
                "category": guess_category(content),
                "reasoning": "[MOCK MODE] Simulated batched response for offline testing, not a real model judgment.",
                "confidence": "medium",
            })
        return FakeResponse(json.dumps(results))

    # Single-email prompt: return a single JSON object
    return FakeResponse(json.dumps({
        "category": guess_category(prompt),
        "reasoning": "[MOCK MODE] This is a simulated response for offline testing, not a real model judgment.",
        "confidence": "medium",
    }))


BATCH_TRIAGE_PROMPT_TEMPLATE = """You are triaging a GROUP of {count} emails into categories, based on REAL stakes -- not surface-level keywords or tone.

Categories (pick exactly one per email):
- "actionable": the recipient needs to do something specific (reply, decide, send a document, make a payment, etc.)
- "time-sensitive": there's a real deadline or window that matters, even if no specific action is spelled out yet
- "informational": useful to know, but truly no action or deadline is implied
- "noise": marketing, automated notices, or low-value content with no real relevance

IMPORTANT: Tone is not evidence. An email full of exclamation marks or the word "URGENT" is not automatically urgent.
A calm, plainly-worded email can carry real stakes. Judge each email on its actual content and the structured signals
provided, not the way it's written. Judge each email independently based on its own content and signals -- do not let
one email's category influence another's unless they are explicitly part of the same thread.

EMAILS:
{emails_block}

Respond ONLY with a valid JSON array, no markdown formatting, no backticks, with exactly {count} objects in the SAME
ORDER as the emails above. Each object must include the email_id so results can be matched back correctly even if
order is ever ambiguous:
[
  {{
    "email_id": "<the id of this email, copied exactly>",
    "category": "<one of: actionable, time-sensitive, informational, noise>",
    "reasoning": "<one or two plain-English sentences explaining the call, referencing the actual evidence used>",
    "confidence": "<low, medium, or high>"
  }},
  ...
]
"""


def build_batch_prompt(emails: list[dict], all_emails: list[dict], memory_store=None) -> tuple[str, dict]:
    """
    Builds a single prompt covering multiple emails at once, to cut API request count.
    Returns the prompt plus a dict of signals used per email (for logging/inspection),
    keyed by email_id.
    """
    blocks = []
    signals_by_id = {}
    for email in emails:
        signals = extract_signals(email, all_emails, memory_store)
        signals_by_id[email["id"]] = signals
        blocks.append(
            f"--- EMAIL {email['id']} ---\n"
            f"From: {email['from']}\n"
            f"Subject: {email['subject']}\n"
            f"Body: {email['body']}\n"
            f"Signals: near_term_date={signals['has_near_term_date']}, "
            f"sender_history={signals['sender_history']}, "
            f"thread_position={signals['thread_position']}"
        )

    prompt = BATCH_TRIAGE_PROMPT_TEMPLATE.format(
        count=len(emails),
        emails_block="\n\n".join(blocks),
    )
    return prompt, signals_by_id


def parse_batch_response(raw_text: str, expected_emails: list[dict]) -> list[dict]:
    """
    Parses a batched JSON array response defensively. Critically: if the array is malformed,
    short, or unparseable, this does NOT silently drop emails -- every email_id from the
    original request gets a result, falling back to a flagged parse-error entry for any that
    can't be matched in the response. This is the key safety property that makes batching
    acceptable: one bad response degrades gracefully per-email rather than losing data.
    """
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    cleaned = cleaned.strip()

    parsed_by_id = {}
    parse_failed_entirely = False
    try:
        array = json.loads(cleaned)
        if not isinstance(array, list):
            raise ValueError("Expected a JSON array")
        for item in array:
            eid = item.get("email_id")
            if eid and item.get("category") in CATEGORIES:
                parsed_by_id[eid] = item
    except (json.JSONDecodeError, ValueError):
        parse_failed_entirely = True

    results = []
    for email in expected_emails:
        eid = email["id"]
        if eid in parsed_by_id:
            results.append(parsed_by_id[eid])
        else:
            reason = ("PARSE ERROR -- entire batch response was malformed."
                      if parse_failed_entirely else
                      "PARSE ERROR -- this email_id was missing from an otherwise-valid batch response.")
            results.append({
                "email_id": eid,
                "category": "informational",  # safe default, never silently drop an email
                "reasoning": f"{reason} Flagged for manual review.",
                "confidence": "low",
                "parse_error": True,
            })
    return results


def triage_batch_grouped(emails: list[dict], all_emails: list[dict], memory_store=None, mock: bool = False) -> list[dict]:
    """
    Triages a group of emails (typically 5) in a SINGLE API call instead of one call per email.
    This is the core fix for free-tier RPM/RPD pressure at full-dataset scale: 77 emails in
    groups of 5 is ~16 calls instead of 77, a ~5x reduction in requests.

    Tradeoff, stated explicitly: a malformed response now risks affecting multiple emails in one
    shot rather than just one. parse_batch_response is built specifically to degrade gracefully --
    matching by email_id rather than position, and falling back to a flagged per-email error for
    anything that can't be matched, rather than losing or misattributing results.
    """
    prompt, signals_by_id = build_batch_prompt(emails, all_emails, memory_store)

    response = call_with_retry_mock(prompt) if mock else call_with_retry(prompt)
    parsed_results = parse_batch_response(response.text, emails)

    final = []
    for email, result in zip(emails, parsed_results):
        final.append({
            "email_id": email["id"],
            "subject": email["subject"],
            "from": email["from"],
            "category": result["category"],
            "reasoning": result["reasoning"],
            "confidence": result["confidence"],
            "signals_used": signals_by_id[email["id"]],
            "mock": mock,  # tag every result so a checkpoint can never silently mix mock and live data
            **({"parse_error": result["parse_error"]} if result.get("parse_error") else {}),
        })
    return final


def triage_email(email: dict, all_emails: list[dict], memory_store=None, mock: bool = False) -> dict:
    """Runs the full triage pipeline for a single email and returns the result with signals attached."""
    signals = extract_signals(email, all_emails, memory_store)
    prompt = build_prompt(email, signals)

    response = call_with_retry_mock(prompt) if mock else call_with_retry(prompt)
    result = parse_triage_response(response.text)

    return {
        "email_id": email["id"],
        "subject": email["subject"],
        "from": email["from"],
        **result,
        "signals_used": signals,
        "mock": mock,  # tag every result so a checkpoint can never silently mix mock and live data
    }


def triage_batch(emails: list[dict], memory_store=None, delay_seconds: float = 12.0,
                  checkpoint_path: str = "data/triage_results_checkpoint.json",
                  mock: bool = False) -> list[dict]:
    """
    Triages a full batch of emails, giving each access to the whole batch for thread context.

    delay_seconds: pause between API calls. Observed in practice that even Flash-Lite's free tier
    hits sustained rate limits with 6s spacing over a long batch (worked for ~13 emails, then hit
    a wall that persisted through 4 retries). Bumped to 12s for more reliable completion -- a
    19-email run now takes ~4 minutes, prioritizing reliability over speed.

    checkpoint_path: results are saved to this file after EVERY email, and already-completed
    emails (by id) are skipped on a re-run -- but ONLY if they came from the same mode (mock vs
    live) as the current run, preventing a mock test run from silently satisfying a later live
    run's checkpoint and returning fake data instead of making real API calls.

    mock: if True, uses call_with_retry_mock instead of the real API -- zero cost, zero quota
    usage, for testing the pipeline's plumbing (parsing, checkpointing, batch logic) in isolation
    from actual model calls. No delay is applied between mock calls since there's no real rate
    limit to respect.
    """
    completed = {}
    if os.path.exists(checkpoint_path):
        with open(checkpoint_path) as f:
            for r in json.load(f):
                if r.get("mock") == mock:
                    completed[r["email_id"]] = r
        if completed:
            skipped = "mock" if mock else "live"
            print(f"Resuming from checkpoint: {len(completed)} {skipped}-mode emails already triaged.\n")
        else:
            print("Checkpoint exists but doesn't match current mode (mock vs live) -- starting fresh.\n")

    results = []

    for i, email in enumerate(emails, 1):
        if email["id"] in completed:
            results.append(completed[email["id"]])
            continue

        print(f"[{i}/{len(emails)}] Triaging: {email['subject'][:60]}...")
        result = triage_email(email, emails, memory_store, mock=mock)
        results.append(result)
        completed[email["id"]] = result
        print(f"  -> [{result['category'].upper()}] ({result['confidence']}) {result['reasoning']}\n")

        # Save progress after every single email -- not just at the end -- so nothing is lost
        # if a later email crashes the run.
        with open(checkpoint_path, "w") as f:
            json.dump(list(completed.values()), f, indent=2)

        if not mock and email is not emails[-1]:
            time.sleep(delay_seconds)

    return results


def triage_dataset_grouped(emails: list[dict], memory_store=None, group_size: int = 10,
                            delay_seconds: float = 15.0,
                            checkpoint_path: str = "data/triage_results_checkpoint.json",
                            mock: bool = False) -> list[dict]:
    """
    Triages a full dataset by chunking it into groups and making ONE API call per group instead
    of one call per email. This is the primary lever for handling the full 77-email dataset on
    the free tier: group_size=5 turns 77 emails into ~16 requests instead of 77, a ~5x reduction,
    which keeps both RPM and RPD pressure low enough to comfortably re-run the full dataset
    multiple times across the project without hitting the walls seen earlier in development.

    Checkpointing happens at the EMAIL level even though calls happen at the GROUP level -- if a
    crash happens after group 3 of 16 succeeds, re-running skips all 15 emails already covered by
    groups 1-3, not just whichever email triggered the crash.
    """
    completed = {}
    if os.path.exists(checkpoint_path):
        with open(checkpoint_path) as f:
            for r in json.load(f):
                # Only trust checkpointed results that match the CURRENT run's mode. A mock run's
                # fake results must never silently satisfy a live run's checkpoint (this caused a
                # real bug in practice: a mock test run populated the checkpoint, then a live run
                # right after saw "19/19 already done" and skipped every real API call, returning
                # leftover fake data instead). Results from older runs that predate this fix won't
                # have a "mock" key at all -- treat those as untrusted too, forcing a clean rerun.
                if r.get("mock") == mock:
                    completed[r["email_id"]] = r
        if completed:
            skipped = "mock" if mock else "live"
            print(f"Resuming from checkpoint: {len(completed)} {skipped}-mode emails already triaged.\n")
        else:
            print("Checkpoint exists but doesn't match current mode (mock vs live) -- starting fresh.\n")

    groups = [emails[i:i + group_size] for i in range(0, len(emails), group_size)]
    results = []

    for gi, group in enumerate(groups, 1):
        remaining_in_group = [e for e in group if e["id"] not in completed]

        for e in group:
            if e["id"] in completed:
                results.append(completed[e["id"]])

        if not remaining_in_group:
            continue  # entire group already done, skip the API call entirely

        print(f"[Group {gi}/{len(groups)}] Triaging {len(remaining_in_group)} email(s): "
              f"{', '.join(e['id'] for e in remaining_in_group)}")

        group_results = triage_batch_grouped(remaining_in_group, emails, memory_store, mock=mock)

        for r in group_results:
            results.append(r)
            completed[r["email_id"]] = r
            flag = " [PARSE ERROR]" if r.get("parse_error") else ""
            print(f"  -> [{r['category'].upper()}] ({r['confidence']}){flag} {r['subject'][:50]}")
        print()

        with open(checkpoint_path, "w") as f:
            json.dump(list(completed.values()), f, indent=2)

        if not mock and gi < len(groups):
            time.sleep(delay_seconds)

    by_id = {r["email_id"]: r for r in results}
    return [by_id[e["id"]] for e in emails]


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Triage a batch of emails using Gemini.")
    parser.add_argument("--mock", action="store_true",
                         help="Use fake responses instead of calling the real API (zero cost, for testing plumbing only).")
    parser.add_argument("--limit", type=int, default=None,
                         help="Only process the first N emails. Useful for a cheap sanity check before running the full batch.")
    parser.add_argument("--fresh", action="store_true",
                         help="Ignore any existing checkpoint and start over from scratch.")
    parser.add_argument("--grouped", action="store_true",
                         help="Use batched mode: multiple emails per API call (default group size 5). "
                              "Cuts request count ~5x, recommended for the full 77-email dataset.")
    parser.add_argument("--group-size", type=int, default=10,
                         help="Emails per API call when --grouped is used (default 10). "
                              "Confirmed free-tier RPD for gemini-2.5-flash-lite is 20/day -- "
                              "group_size=10 keeps the full 77-email dataset to 8 calls, leaving "
                              "real margin for retries or a second run the same day.")
    parser.add_argument("--full", action="store_true",
                         help="Use the full 77-email dataset (data/sample_emails.json) instead of the 19-email dev subset.")
    args = parser.parse_args()

    dataset_file = "data/sample_emails.json" if args.full else "data/sample_emails_dev.json"
    with open(dataset_file) as f:
        emails = json.load(f)

    if args.limit:
        emails = emails[:args.limit]

    checkpoint = "data/triage_results_checkpoint.json"
    if args.fresh and os.path.exists(checkpoint):
        os.remove(checkpoint)
        print("Cleared existing checkpoint, starting fresh.\n")

    # Wire in the memory store so sender history actually feeds into triage signals.
    # In mock mode, skip memory (no real results to learn from anyway).
    # In live mode, initialize the DB (no-op if it already exists) and pass the store in.
    memory_store = None
    if not args.mock:
        from src.memory_store import initialize_db, get_sender_pattern
        initialize_db()

        class MemoryStore:
            """Thin wrapper so triage_email/signals.py can call memory_store.get_sender_pattern()."""
            def get_sender_pattern(self, sender_email: str) -> dict:
                return get_sender_pattern(sender_email)

        memory_store = MemoryStore()
        print("Sender memory loaded (43 known senders will inform triage signals).\n"
              if os.path.exists("data/memory.db") else
              "No sender memory yet -- run `python -m src.confirm --all` after first triage to build it.\n")

    mode_label = "MOCK MODE (no real API calls, zero cost)" if args.mock else "LIVE MODE (real API calls)"
    call_style = f"GROUPED (size={args.group_size}, ~{-(-len(emails)//args.group_size)} calls)" if args.grouped else f"ONE CALL PER EMAIL ({len(emails)} calls)"
    print(f"Triaging {len(emails)} emails from {dataset_file}. {mode_label}. {call_style}.\n")

    # Outer auto-resume loop: if a whole run dies (e.g. a sustained 503 streak that outlasts even
    # call_with_retry's internal retries), automatically wait longer and re-invoke the same run
    # rather than requiring the user to manually re-type the command each time. The checkpoint
    # (email-level for triage_batch, group-level granularity for triage_dataset_grouped) means
    # each re-invocation only redoes the work that didn't complete, so this is safe to repeat.
    # An RPD "daily quota exhausted" error is NOT retried here -- that's a hard wall, not a
    # transient failure, and call_with_retry already raises a clear message for it; auto-retrying
    # against it would be pointless and is explicitly excluded.
    max_outer_attempts = 5
    outer_wait = 60.0  # generous cooldown between full-run attempts, longer than any single
                        # group's internal retry budget, to let sustained server overload clear

    results = None
    for outer_attempt in range(1, max_outer_attempts + 1):
        try:
            if args.grouped:
                results = triage_dataset_grouped(emails, memory_store=memory_store, mock=args.mock, group_size=args.group_size, checkpoint_path=checkpoint)
            else:
                results = triage_batch(emails, memory_store=memory_store, mock=args.mock, checkpoint_path=checkpoint)
            break  # success, exit the outer loop
        except RuntimeError as e:
            if "DAILY QUOTA EXHAUSTED" in str(e):
                print(f"\n{e}\n")
                raise SystemExit(1)  # hard stop, no point auto-retrying a daily wall

            if outer_attempt < max_outer_attempts:
                print(f"\n[Run attempt {outer_attempt}/{max_outer_attempts} failed: {e}]")
                print(f"[Waiting {outer_wait:.0f}s before automatically retrying the remaining work...]\n")
                time.sleep(outer_wait)
            else:
                print(f"\n[All {max_outer_attempts} attempts failed. Stopping -- completed results "
                      f"so far remain safely in the checkpoint file.]")
                raise

    if results is None:
        raise SystemExit(1)

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for r in results:
        print(f"[{r['category'].upper()}] ({r['confidence']}) {r['subject']}")
        print(f"  From: {r['from']}")
        print(f"  Reasoning: {r['reasoning']}\n")
