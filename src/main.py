"""
main.py

The unified agent entry point. This is what makes the inbox-agent an actual agent
rather than a collection of disconnected scripts.

Single command: python -m src.main

Flow:
    1. Load triage results from checkpoint (run triage first if none exist)
    2. Display inbox summary grouped by category
    3. User picks an email by number
    4. Agent shows full details + reasoning
    5. If actionable/time-sensitive: offer to draft a reply
    6. If user wants to draft: run full drafting flow (intent -> draft -> approve)
    7. Loop back to inbox view until user quits

This is the "agent skill" concept from the project description: the agent doesn't
just classify -- it helps the user decide what to do next and drafts replies on demand.
"""

import json
import os
import sys
from src.drafting import drafting_flow
from src.memory_store import initialize_db, get_sender_pattern, confirm_batch_results

CHECKPOINT_PATH = "data/triage_results_checkpoint.json"
EMAILS_PATH = "data/sample_emails.json"
DB_PATH = "data/memory.db"

CATEGORY_ORDER = ["time-sensitive", "actionable", "informational", "noise"]

CATEGORY_LABELS = {
    "time-sensitive": "⏰ TIME-SENSITIVE",
    "actionable":     "✅ ACTIONABLE",
    "informational":  "ℹ  INFORMATIONAL",
    "noise":          "🔇 NOISE",
}

REPLY_WORTHY = {"time-sensitive", "actionable"}


def load_data() -> tuple[list[dict], dict[str, dict]]:
    """Load triage results and original emails. Exit cleanly if not ready."""
    if not os.path.exists(CHECKPOINT_PATH):
        print("\nNo triage results found.")
        print("Run this first: python -m src.triage --grouped --full")
        sys.exit(1)

    with open(CHECKPOINT_PATH) as f:
        all_results = json.load(f)

    # Only use live results, not mock
    results = [r for r in all_results if not r.get("mock", False)]
    if not results:
        print("\nCheckpoint contains only mock results. Run a live triage first.")
        print("Command: python -m src.triage --grouped --full")
        sys.exit(1)

    with open(EMAILS_PATH) as f:
        emails_list = json.load(f)
    emails = {e["id"]: e for e in emails_list}

    return results, emails


def display_category_menu(results: list[dict]) -> dict:
    """
    Shows category counts only. User picks a category first,
    then sees emails within that category.
    """
    counts = {}
    for category in CATEGORY_ORDER:
        count = len([r for r in results if r.get("category") == category])
        counts[category] = count

    print(f"\n{'='*65}")
    print(f"  INBOX — {len(results)} emails triaged")
    print(f"{'='*65}\n")
    print(f"  [T] {CATEGORY_LABELS['time-sensitive']:<25} ({counts['time-sensitive']} emails)")
    print(f"  [A] {CATEGORY_LABELS['actionable']:<25} ({counts['actionable']} emails)")
    print(f"  [I] {CATEGORY_LABELS['informational']:<25} ({counts['informational']} emails)")
    print(f"  [N] {CATEGORY_LABELS['noise']:<25} ({counts['noise']} emails)")
    print(f"\n{'='*65}")
    return counts


def display_category_emails(results: list[dict], category: str) -> list[dict]:
    """Shows emails within a specific category. Returns ordered list for picking."""
    group = [r for r in results if r.get("category") == category]
    label = CATEGORY_LABELS.get(category, category.upper())

    print(f"\n{label} — {len(group)} emails")
    print("-" * 50)

    for i, result in enumerate(group, 1):
        parse_flag = " [!]" if result.get("parse_error") else ""
        conf = "?" if result.get("confidence") == "low" else \
               "~" if result.get("confidence") == "medium" else ""
        print(f"  {i:>2}. {conf}{result['subject'][:50]}{parse_flag}")
        print(f"       From: {result['from']}")

    print(f"\n{'='*65}")
    return group


def display_email_detail(result: dict, email: dict):
    """Show full details of a selected email."""
    print(f"\n{'='*65}")
    label = CATEGORY_LABELS.get(result.get("category"), result.get("category", "").upper())
    print(f"{label} — {result['subject']}")
    print(f"{'='*65}")
    print(f"From:    {email['from']}")
    print(f"Date:    {email.get('date', 'unknown')}")
    print(f"\nBody:\n{email['body']}")
    print(f"\nAgent reasoning: {result.get('reasoning', 'N/A')}")
    print(f"Confidence: {result.get('confidence', 'unknown')}")

    if result.get("parse_error"):
        print("\n⚠  This email was flagged for manual review (parse error).")
        print("   The category shown is a safe default, not a real model judgment.")

    # Show sender memory if available
    pattern = get_sender_pattern(email["from"], DB_PATH)
    if pattern.get("known"):
        print(f"\nSender memory: {email['from']} is {pattern['pattern']} "
              f"(based on {pattern['sample_size']} past emails)")
    print(f"{'='*65}")


def get_user_choice(prompt: str, valid: set) -> str:
    """Get a valid choice from the user, case-insensitive."""
    while True:
        choice = input(prompt).strip().lower()
        if choice in valid:
            return choice
        print(f"  Please enter one of: {', '.join(sorted(valid))}")


def clear_screen():
    """Clear terminal screen — works on both Windows and Mac/Linux."""
    os.system('cls' if os.name == 'nt' else 'clear')


def get_user_name() -> str:
    """Ask for the user's name once at startup so drafts don't say [Your Name]."""
    print("\nWhat's your name? (used in email sign-offs)")
    name = input("> ").strip()
    return name if name else "Your Name"


def main():
    print("\n" + "="*65)
    print("  INBOX-TO-ACTION AGENT")
    print("  Triage → Review → Draft → Approve")
    print("="*65)

    # Get user's name upfront so drafts are personalized
    user_name = get_user_name()

    # Initialize memory
    initialize_db(DB_PATH)

    # Load data
    results, emails = load_data()

    while True:
        clear_screen()
        display_category_menu(results)

        print("\nEnter a category letter, or:")
        print("  [c] confirm all results into memory")
        print("  [q] quit")

        raw = input("\nYour choice: ").strip().lower()

        if raw == "q":
            print("\nGoodbye.")
            break

        if raw == "c":
            live_results = [r for r in results if not r.get("mock")]
            result = confirm_batch_results(live_results, DB_PATH)
            print(f"\n✓ {result['confirmed']} results confirmed into sender memory.")
            print(f"  ({result['skipped_parse_errors']} parse errors skipped.)")
            input("\nPress Enter to continue...")
            continue

        category_map = {
            "t": "time-sensitive",
            "a": "actionable",
            "i": "informational",
            "n": "noise",
        }

        if raw not in category_map:
            print("  Enter T, A, I, N, C, or Q.")
            input("Press Enter to continue...")
            continue

        selected_category = category_map[raw]
        group = [r for r in results if r.get("category") == selected_category]

        if not group:
            print(f"  No emails in this category.")
            input("Press Enter to continue...")
            continue

        # Category email list
        while True:
            clear_screen()
            category_emails = display_category_emails(results, selected_category)

            print("\nEnter a number to view an email, or [b] to go back.")
            sub_raw = input("Your choice: ").strip().lower()

            if sub_raw == "b":
                break

            try:
                idx = int(sub_raw) - 1
                if idx < 0 or idx >= len(category_emails):
                    print(f"  Please enter a number between 1 and {len(category_emails)}.")
                    input("Press Enter to continue...")
                    continue
            except ValueError:
                print("  Please enter a number or 'b'.")
                input("Press Enter to continue...")
                continue

            selected = category_emails[idx]
            email_id = selected["email_id"]

            if email_id not in emails:
                print(f"  Email data not found for {email_id}.")
                input("Press Enter to continue...")
                continue

            email = emails[email_id]

            clear_screen()
            display_email_detail(selected, email)

            category = selected.get("category", "")

            if selected.get("parse_error"):
                print("\nThis email was flagged as uncertain. Review it manually.")
                input("Press Enter to go back...")
                continue

            if category in REPLY_WORTHY:
                print("\nOptions:")
                print("  [d] draft a reply")
                print("  [b] go back to category list")
                action = get_user_choice("Your choice [d/b]: ", {"d", "b"})

                if action == "d":
                    drafting_flow(email, selected, user_name=user_name)
                    input("\nPress Enter to go back...")
            else:
                print(f"\nThis email is {category} — no reply needed.")
                input("Press Enter to go back...")


if __name__ == "__main__":
    main()
