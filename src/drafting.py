"""
drafting.py

Takes a triaged email + user's plain-English intent and drafts a tone-matched reply.

Core guardrails:
1. Never drafts without being explicitly asked (no auto-draft on triage)
2. Never sends without explicit user approval (simulated send only)
3. Never guesses at ambiguous intent -- flags it and asks for clarification
4. Tone is matched to the original email, not forced formal/informal

Flow:
    1. User picks an email from triage results
    2. User gives plain-English intent ("tell them I'll confirm by tomorrow")
    3. Agent detects tone of original email
    4. Agent drafts a reply matching that tone + the user's intent
    5. User reviews: approve / edit / reject
    6. On approval: simulated send (logged, never real)
"""

import json
import os
import time
from datetime import datetime
from google import genai
from google.genai import errors as genai_errors
from dotenv import load_dotenv

load_dotenv()

_client = None

def get_client():
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client

MODEL = "gemini-2.5-flash-lite"

DRAFT_PROMPT = """You are drafting a reply to an email on behalf of the recipient.

ORIGINAL EMAIL:
From: {sender}
Subject: {subject}
Body: {body}

TRIAGE CONTEXT:
Category: {category}
Reasoning: {reasoning}

USER'S INTENT (what they want to say):
{intent}

TONE INSTRUCTIONS:
Detect the writing STYLE of the original email (not the urgency of the situation):
- formal: structured language, titles, business context -> reply with "Dear [Name]," and formal sign-off
- casual: informal language, first names, relaxed phrasing -> reply with "Hi [Name]," and casual sign-off
- mixed: somewhere between formal and casual -> match the middle ground

CRITICAL RULES that override everything else:
1. EVERY reply must have: a greeting line, at least 2-3 sentences of body, and a sign-off with [Your Name].
2. A one-sentence reply is NEVER acceptable regardless of how urgent the situation is.
3. An urgent DEADLINE in the email does not mean a terse WRITING STYLE in the reply.
4. Prof. Reyes writing "I need your resume by Monday" is a polite professional email -- reply politely and professionally, not in telegram style.

Valid tone_detected values: "formal", "casual", "mixed" -- never "urgent" or "terse".

GUARDRAIL: If the user's intent is vague, contradictory, or unclear, do NOT draft a reply.
Instead, return a JSON object with "needs_clarification": true and a "question" field asking
the one most important clarifying question.

If the intent is clear, draft the reply and return JSON in exactly this format:
{{
  "needs_clarification": false,
  "tone_detected": "<formal/casual/urgent/mixed>",
  "subject": "<reply subject line, usually Re: original subject>",
  "body": "<the full reply body>",
  "warnings": "<any concerns about this reply, or empty string if none>"
}}

USER NAME (use this in the sign-off, not "[Your Name]"):
{user_name}

Respond ONLY with valid JSON, no markdown, no backticks.
"""

SIMULATED_SEND_LOG = "data/sent_log.json"


def call_with_retry(prompt: str, max_retries: int = 5, base_wait: float = 15.0):
    """Calls Gemini with retry on 503 server overload."""
    for attempt in range(max_retries):
        try:
            return get_client().models.generate_content(model=MODEL, contents=prompt)
        except genai_errors.ServerError as e:
            if "UNAVAILABLE" in str(e) or "503" in str(e):
                wait = base_wait * (attempt + 1)
                print(f"  [server overloaded -- waiting {wait:.0f}s before retry {attempt + 1}/{max_retries}]")
                time.sleep(wait)
            else:
                raise
        except genai_errors.ClientError:
            raise  # don't swallow quota errors
    raise RuntimeError(f"Drafting failed after {max_retries} retries due to server overload.")


def detect_ambiguous_intent(intent: str) -> bool:
    """
    Quick pre-check for obviously vague intents before spending an API call.
    Returns True if the intent is too vague to act on without clarification.
    """
    vague_phrases = [
        "i don't know", "not sure", "something", "whatever", "anything",
        "just reply", "figure it out", "you decide", "surprise me"
    ]
    lowered = intent.lower().strip()
    if len(lowered) < 5:
        return True
    return any(phrase in lowered for phrase in vague_phrases)


def draft_reply(email: dict, triage_result: dict, user_intent: str, user_name: str = "Your Name") -> dict:
    """
    Drafts a tone-matched reply based on the original email and user's intent.
    Returns either a draft ready for review, or a clarification request.
    """
    if detect_ambiguous_intent(user_intent):
        return {
            "needs_clarification": True,
            "question": "Could you be more specific about what you'd like to say? "
                        "For example: 'tell them I'll confirm by Friday' or 'decline politely, "
                        "cite scheduling conflicts'.",
            "tone_detected": None,
            "subject": None,
            "body": None,
            "warnings": None,
        }

    prompt = DRAFT_PROMPT.format(
        sender=email["from"],
        subject=email["subject"],
        body=email["body"],
        category=triage_result.get("category", "unknown"),
        reasoning=triage_result.get("reasoning", ""),
        intent=user_intent,
        user_name=user_name,
    )

    response = call_with_retry(prompt)
    raw = response.text.strip()

    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    try:
        result = json.loads(raw)
        result.setdefault("needs_clarification", False)
        result.setdefault("tone_detected", "unknown")
        result.setdefault("subject", f"Re: {email['subject']}")
        result.setdefault("body", "")
        result.setdefault("warnings", "")
        return result
    except json.JSONDecodeError:
        return {
            "needs_clarification": False,
            "tone_detected": "unknown",
            "subject": f"Re: {email['subject']}",
            "body": raw,
            "warnings": "Draft was returned in unexpected format -- review carefully before sending.",
        }


def present_draft(draft: dict, email: dict):
    """Displays the draft to the user for review."""
    print(f"\n{'='*60}")
    print("DRAFT REPLY")
    print(f"{'='*60}")
    print(f"To:      {email['from']}")
    print(f"Subject: {draft['subject']}")
    print(f"Tone:    {draft['tone_detected']}")
    if draft.get("warnings"):
        print(f"Warning: {draft['warnings']}")
    print(f"\n{draft['body']}")
    print(f"{'='*60}\n")


def simulate_send(email: dict, draft: dict, user_intent: str):
    """
    Simulates sending the reply -- logs to sent_log.json, never real email.
    This is the core guardrail: nothing leaves without explicit approval,
    and even then it is simulated, not real.
    """
    log_entry = {
        "sent_at": datetime.now().isoformat(),
        "to": email["from"],
        "original_subject": email["subject"],
        "reply_subject": draft["subject"],
        "reply_body": draft["body"],
        "tone_detected": draft["tone_detected"],
        "user_intent": user_intent,
        "simulated": True,
    }

    existing = []
    if os.path.exists(SIMULATED_SEND_LOG):
        with open(SIMULATED_SEND_LOG) as f:
            existing = json.load(f)

    existing.append(log_entry)
    with open(SIMULATED_SEND_LOG, "w") as f:
        json.dump(existing, f, indent=2)

    print(f"[SIMULATED SEND] Reply logged to {SIMULATED_SEND_LOG}")
    print(f"  To: {email['from']}")
    print(f"  Subject: {draft['subject']}")
    print(f"  (No real email was sent -- this is a simulation)")


def drafting_flow(email: dict, triage_result: dict, user_name: str = "Your Name"):
    """
    Full interactive drafting flow for a single email.
    Asks for intent, drafts, presents for review, handles approval/edit/reject.
    """
    print(f"\n{'='*60}")
    print(f"DRAFTING REPLY TO: {email['subject']}")
    print(f"From: {email['from']}")
    print(f"Category: {triage_result.get('category', 'unknown').upper()}")
    print(f"{'='*60}")

    print("\nWhat do you want to say? (plain English, e.g. 'tell them I'll confirm by Friday')")
    print("Type 'skip' to cancel drafting for this email.\n")
    user_intent = input("Your intent: ").strip()

    if user_intent.lower() == "skip":
        print("Skipped.")
        return None

    print("\nDrafting reply...")
    draft = draft_reply(email, triage_result, user_intent, user_name=user_name)

    if draft.get("needs_clarification"):
        print(f"\nIntent unclear. Before drafting, I need to know:")
        print(f"  {draft['question']}")
        user_intent = input("\nClarified intent: ").strip()
        if not user_intent or user_intent.lower() == "skip":
            print("Skipped.")
            return None
        print("\nRe-drafting with clarified intent...")
        draft = draft_reply(email, triage_result, user_intent, user_name=user_name)

    present_draft(draft, email)

    print("Options: [a]pprove and send | [e]dit intent and redraft | [r]eject")
    choice = input("Your choice: ").strip().lower()

    if choice == "a":
        simulate_send(email, draft, user_intent)
        return draft

    elif choice == "e":
        print("\nWhat would you like to change about your intent?")
        new_intent = input("New intent: ").strip()
        print("\nRe-drafting...")
        new_draft = draft_reply(email, triage_result, new_intent, user_name=user_name)
        present_draft(new_draft, email)
        confirm = input("Approve this version? [y/n]: ").strip().lower()
        if confirm == "y":
            simulate_send(email, new_draft, new_intent)
            return new_draft
        else:
            print("Draft rejected. Nothing sent.")
            return None

    else:
        print("Draft rejected. Nothing sent.")
        return None


if __name__ == "__main__":
    import sys

    checkpoint = "data/triage_results_checkpoint.json"
    emails_file = "data/sample_emails.json"

    if not os.path.exists(checkpoint):
        print("No triage checkpoint found. Run triage first.")
        sys.exit(1)

    with open(checkpoint) as f:
        triage_results = {r["email_id"]: r for r in json.load(f)}

    with open(emails_file) as f:
        emails = {e["id"]: e for e in json.load(f)}

    email_id = sys.argv[1] if len(sys.argv) > 1 else "e004"

    if email_id not in emails:
        print(f"Email {email_id} not found.")
        sys.exit(1)
    if email_id not in triage_results:
        print(f"No triage result for {email_id}. Run triage first.")
        sys.exit(1)

    drafting_flow(emails[email_id], triage_results[email_id])
