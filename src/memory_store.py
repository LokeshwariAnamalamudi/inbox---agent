"""
memory_store.py

Persistent sender pattern memory using SQLite. Every time a triage result is
confirmed by the user, it gets written here. On the next triage run, this history
is surfaced as a structured signal in the prompt -- so the agent can reason about
patterns like "this sender is usually FYI" or "this sender always needs action."

Key design decision: memory only updates on EXPLICIT confirmation, not automatically
after every triage run. This prevents wrong calls from compounding into a bad
reputation for a sender over time, and keeps the human in the loop on what the
agent is learning. This is a guardrail, not just a convenience choice.

The database persists across separate script runs as a plain SQLite file on disk
(data/memory.db). This is the "remembers sender patterns across sessions" feature
promised in the project description.
"""

import sqlite3
import os
from datetime import datetime, timezone
from collections import Counter


DB_PATH = "data/memory.db"


def get_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    """Returns a connection to the SQLite database, creating it if it doesn't exist."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # lets us access columns by name, not just index
    return conn


def initialize_db(db_path: str = DB_PATH):
    """
    Creates the sender_memory table if it doesn't exist. Safe to call every run --
    the IF NOT EXISTS clause makes it a no-op if the table is already there.

    Schema design: one row per confirmed triage event, not one row per sender.
    This preserves the full history rather than overwriting a summary, so we can
    compute richer patterns (e.g. "was always noise until last week") later if needed.
    """
    with get_connection(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sender_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_email TEXT NOT NULL,
                email_id TEXT NOT NULL,
                subject TEXT NOT NULL,
                category TEXT NOT NULL,
                confidence TEXT NOT NULL,
                confirmed_at TEXT NOT NULL
            )
        """)
        conn.commit()


def record_confirmed_result(
    sender_email: str,
    email_id: str,
    subject: str,
    category: str,
    confidence: str,
    db_path: str = DB_PATH,
):
    """
    Writes a single confirmed triage result to memory. Called ONLY after the user
    has explicitly reviewed and approved the triage call -- not automatically after
    every run. This is the guardrail that keeps memory accurate over time.
    """
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO sender_memory
                (sender_email, email_id, subject, category, confidence, confirmed_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                sender_email.lower().strip(),
                email_id,
                subject,
                category,
                confidence,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()


def get_sender_pattern(sender_email: str, db_path: str = DB_PATH) -> dict:
    """
    Looks up everything we know about a sender and returns a structured summary
    suitable for injecting into the triage prompt as context. If we have no history
    for this sender, returns a clearly-marked "no history" result so the prompt
    knows not to treat the absence of data as evidence of anything.
    """
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT category, confidence, confirmed_at
            FROM sender_memory
            WHERE sender_email = ?
            ORDER BY confirmed_at ASC
            """,
            (sender_email.lower().strip(),),
        ).fetchall()

    if not rows:
        return {
            "known": False,
            "sample_size": 0,
            "pattern": "no history yet -- treat this sender without prior assumptions",
            "most_common_category": None,
            "category_breakdown": {},
        }

    categories = [row["category"] for row in rows]
    counts = Counter(categories)
    most_common = counts.most_common(1)[0][0]
    total = len(rows)

    # Build a human-readable breakdown, e.g. "informational: 7/9, actionable: 2/9"
    breakdown_str = ", ".join(
        f"{cat}: {cnt}/{total}" for cat, cnt in counts.most_common()
    )

    # Determine how strong the pattern is -- "always", "usually", "sometimes"
    top_fraction = counts[most_common] / total
    if top_fraction == 1.0:
        strength = "always"
    elif top_fraction >= 0.75:
        strength = "usually"
    elif top_fraction >= 0.5:
        strength = "often"
    else:
        strength = "sometimes"

    return {
        "known": True,
        "sample_size": total,
        "pattern": f"{strength} {most_common} ({breakdown_str})",
        "most_common_category": most_common,
        "category_breakdown": dict(counts),
    }


def confirm_batch_results(
    triage_results: list[dict],
    db_path: str = DB_PATH,
):
    """
    Writes a batch of confirmed triage results to memory in one transaction.
    Called after the user has reviewed a full triage run and approved the results.
    Parse errors (flagged results) are skipped -- we don't want to learn from
    calls the model itself flagged as uncertain.
    """
    confirmed = 0
    skipped = 0

    with get_connection(db_path) as conn:
        for result in triage_results:
            if result.get("parse_error"):
                skipped += 1
                continue  # don't learn from flagged/uncertain results

            conn.execute(
                """
                INSERT INTO sender_memory
                    (sender_email, email_id, subject, category, confidence, confirmed_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    result["from"].lower().strip(),
                    result["email_id"],
                    result["subject"],
                    result["category"],
                    result["confidence"],
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            confirmed += 1
        conn.commit()

    return {"confirmed": confirmed, "skipped_parse_errors": skipped}


def get_all_sender_patterns(db_path: str = DB_PATH) -> dict:
    """
    Returns pattern summaries for ALL known senders. Useful for displaying the
    full memory state to the user (e.g. 'here's what the agent has learned so far').
    """
    with get_connection(db_path) as conn:
        senders = conn.execute(
            "SELECT DISTINCT sender_email FROM sender_memory ORDER BY sender_email"
        ).fetchall()

    return {
        row["sender_email"]: get_sender_pattern(row["sender_email"], db_path)
        for row in senders
    }


def clear_sender_history(sender_email: str, db_path: str = DB_PATH):
    """
    Removes all memory for a specific sender. Useful if the agent has learned
    a wrong pattern and you want to reset it rather than carry bad history forward.
    """
    with get_connection(db_path) as conn:
        conn.execute(
            "DELETE FROM sender_memory WHERE sender_email = ?",
            (sender_email.lower().strip(),),
        )
        conn.commit()


if __name__ == "__main__":
    # Quick test: initialize the DB, write a few fake results, read them back
    import json

    TEST_DB = "data/test_memory.db"

    print("Initializing test database...")
    initialize_db(TEST_DB)

    print("Writing fake confirmed results for Prof. Reyes (9 informational, 1 actionable)...")
    fake_results = [
        {"from": "prof.reyes@university.edu", "email_id": f"e00{i}",
         "subject": f"Test email {i}", "category": "informational",
         "confidence": "high"}
        for i in range(1, 10)
    ] + [
        {"from": "prof.reyes@university.edu", "email_id": "e010",
         "subject": "Recommendation letter deadline", "category": "actionable",
         "confidence": "high"}
    ]
    result = confirm_batch_results(fake_results, TEST_DB)
    print(f"Confirmed: {result}")

    print("\nLooking up sender pattern for Prof. Reyes:")
    pattern = get_sender_pattern("prof.reyes@university.edu", TEST_DB)
    print(json.dumps(pattern, indent=2))

    print("\nLooking up unknown sender:")
    unknown = get_sender_pattern("unknown@newdomain.com", TEST_DB)
    print(json.dumps(unknown, indent=2))

    print("\nAll known senders:")
    all_patterns = get_all_sender_patterns(TEST_DB)
    for sender, p in all_patterns.items():
        print(f"  {sender}: {p['pattern']}")

    # Clean up test DB -- explicitly close all connections first (required on Windows,
    # which holds file handles open longer than Linux/Mac)
    import gc
    gc.collect()  # force any lingering connection objects to be garbage collected
    try:
        os.remove(TEST_DB)
        print("\nTest complete. Test database cleaned up.")
    except PermissionError:
        print(f"\nTest complete. (Note: could not auto-delete {TEST_DB} on Windows -- safe to delete manually.)")
