"""
signals.py

Deterministic, hand-built signal extractors used to enrich the prompt sent to Gemini.
These do NOT make triage decisions themselves -- they just surface concrete facts
(near-term dates, sender history, thread position) that get handed to the LLM as
structured context. Keeping this separate from the LLM call is the "real stakes, not
just keywords" story: the LLM reasons over evidence, it doesn't decide alone.
"""

import re
from datetime import datetime

# Deliberately simple keyword/pattern list for near-term time pressure.
# This is NOT meant to catch every case -- it's a cheap signal, not the final answer.
NEAR_TERM_PATTERNS = [
    r"\btoday\b", r"\btonight\b", r"\btomorrow\b", r"\bthis (morning|afternoon|evening|weekend)\b",
    r"\bby (friday|monday|tuesday|wednesday|thursday|saturday|sunday|end of day|eod|end of week)\b",
    r"\bwithin (the next )?\d+ (hour|hours|day|days)\b",
    r"\b\d+ (hour|hours|day|days) (left|remaining)\b",
    r"\bdeadline\b", r"\bdue (today|tomorrow|this week|by)\b",
    r"\bASAP\b", r"\bas soon as possible\b",
]

def has_near_term_date(body: str) -> bool:
    """Cheap, deterministic check for near-term time-pressure language."""
    text = body.lower()
    return any(re.search(pat, text) for pat in NEAR_TERM_PATTERNS)


def sender_history(sender_email: str, memory_store=None) -> dict:
    """
    Returns what we know about this sender's historical pattern, looked up from the
    persistent SQLite memory store. If memory_store is None (e.g. during early testing
    before Day 3 was integrated), falls back to a clearly-marked "no history" result
    rather than crashing -- this keeps signals.py usable in isolation.

    Day 3 integration: callers pass in an initialized MemoryStore instance, which this
    function queries via get_sender_pattern(). The result feeds directly into the triage
    prompt as structured context, so the LLM can reason about patterns like "this sender
    is usually informational" when making its judgment.
    """
    if memory_store is None:
        return {
            "known": False,
            "pattern": "no history yet -- treat this sender without prior assumptions",
            "sample_size": 0,
        }
    return memory_store.get_sender_pattern(sender_email)


def is_thread_reply(email: dict, all_emails: list[dict]) -> dict:
    """
    Checks whether this email belongs to a multi-message thread within the current
    batch, and roughly where it sits in that thread (first message, or a later one).
    """
    thread_id = email.get("thread_id")
    if not thread_id:
        return {"in_thread": False}

    thread_messages = [e for e in all_emails if e.get("thread_id") == thread_id]
    thread_messages.sort(key=lambda e: e["date"])

    position = next((i for i, e in enumerate(thread_messages) if e["id"] == email["id"]), 0)

    return {
        "in_thread": True,
        "thread_length": len(thread_messages),
        "position": position + 1,  # 1-indexed for human readability
        "is_first_message": position == 0,
        "is_latest_message": position == len(thread_messages) - 1,
    }


def extract_signals(email: dict, all_emails: list[dict], memory_store=None) -> dict:
    """Bundles all signal extractors into one dict to hand to the LLM as context."""
    return {
        "has_near_term_date": has_near_term_date(email["body"]),
        "sender_history": sender_history(email["from"], memory_store),
        "thread_position": is_thread_reply(email, all_emails),
    }
