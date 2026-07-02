"""
confirm.py

The bridge between triage results and persistent memory. After a triage run
completes, this module presents the results to the user and asks them to confirm
before anything gets written to the memory store.

This is the guardrail that keeps memory accurate: the agent never learns from
its own unreviewed output. A human has to explicitly say "yes, these calls look
right" before the sender patterns get updated. This prevents wrong triage calls
from compounding into bad sender reputations over time.

Usage:
    python -m src.confirm                          # confirm latest checkpoint
    python -m src.confirm --all                    # confirm all, no prompting
    python -m src.confirm --show-memory            # show current memory state
    python -m src.confirm --clear sender@email.com # reset one sender's history
"""

import json
import os
import argparse
from src.memory_store import (
    initialize_db,
    confirm_batch_results,
    get_all_sender_patterns,
    clear_sender_history,
)

CHECKPOINT_PATH = "data/triage_results_checkpoint.json"
DB_PATH = "data/memory.db"

CATEGORY_COLORS = {
    "actionable":     "ACTION",
    "time-sensitive": "TIME  ",
    "informational":  "INFO  ",
    "noise":          "NOISE ",
}


def load_checkpoint(path: str = CHECKPOINT_PATH) -> list[dict]:
    """Loads triage results from the checkpoint file."""
    if not os.path.exists(path):
        print(f"No checkpoint file found at {path}.")
        print("Run `python -m src.triage --grouped --full` first to generate triage results.")
        raise SystemExit(1)

    with open(path) as f:
        results = json.load(f)

    # Only show live results, not mock-mode results
    live_results = [r for r in results if not r.get("mock", False)]
    if not live_results:
        print("Checkpoint contains only mock-mode results. Run a live triage first.")
        raise SystemExit(1)

    return live_results


def display_results(results: list[dict], show_reasoning: bool = True):
    """Prints triage results in a readable format for human review."""
    print(f"\n{'='*65}")
    print(f"TRIAGE RESULTS — {len(results)} emails")
    print(f"{'='*65}\n")

    parse_errors = [r for r in results if r.get("parse_error")]
    clean_results = [r for r in results if not r.get("parse_error")]

    for r in clean_results:
        label = CATEGORY_COLORS.get(r["category"], r["category"].upper()[:6])
        confidence_marker = "?" if r["confidence"] == "low" else \
                           "~" if r["confidence"] == "medium" else ""
        print(f"[{label}]{confidence_marker} {r['subject'][:55]}")
        print(f"         From: {r['from']}")
        if show_reasoning:
            print(f"         Why:  {r['reasoning'][:120]}")
        print()

    if parse_errors:
        print(f"--- {len(parse_errors)} email(s) flagged for manual review (parse errors) ---")
        for r in parse_errors:
            print(f"  {r['subject'][:55]} — From: {r['from']}")
        print()


def confirm_interactive(results: list[dict]) -> list[dict]:
    """
    Walks the user through each result and asks for confirmation.
    Returns only the results the user explicitly approved.

    Skips parse errors automatically -- we never learn from uncertain results.
    Low-confidence results are flagged with an extra warning before asking.
    """
    confirmed = []
    skipped = 0

    clean_results = [r for r in results if not r.get("parse_error")]
    print(f"\nReviewing {len(clean_results)} results for memory confirmation.")
    print("Press Enter to confirm, 's' to skip, 'q' to stop and save what you've confirmed so far.\n")

    for i, r in enumerate(clean_results, 1):
        label = CATEGORY_COLORS.get(r["category"], r["category"].upper())
        print(f"[{i}/{len(clean_results)}] [{label}] ({r['confidence']}) {r['subject'][:55]}")
        print(f"  From: {r['from']}")
        print(f"  Why:  {r['reasoning'][:120]}")

        if r["confidence"] == "low":
            print("  ⚠ Low confidence — consider skipping this one.")
        elif r["confidence"] == "medium":
            print("  ~ Medium confidence — judgment call on your part.")

        choice = input("  Confirm? [Enter=yes / s=skip / q=quit]: ").strip().lower()

        if choice == "q":
            print(f"\nStopped early. {len(confirmed)} confirmed so far.")
            break
        elif choice == "s":
            skipped += 1
        else:
            confirmed.append(r)

        print()

    return confirmed


def confirm_all(results: list[dict]) -> list[dict]:
    """
    Confirms all non-parse-error, non-low-confidence results automatically.
    Used with --all flag when the user trusts the full triage run.
    Low-confidence results are still skipped for safety.
    """
    return [
        r for r in results
        if not r.get("parse_error") and r.get("confidence") != "low"
    ]


def show_memory_state(db_path: str = DB_PATH):
    """Displays everything the agent currently remembers about senders."""
    patterns = get_all_sender_patterns(db_path)

    if not patterns:
        print("\nMemory is empty -- no confirmed triage results yet.")
        return

    print(f"\n{'='*65}")
    print(f"SENDER MEMORY — {len(patterns)} known senders")
    print(f"{'='*65}\n")

    # Sort by sample size so well-established patterns appear first
    sorted_patterns = sorted(
        patterns.items(),
        key=lambda x: x[1]["sample_size"],
        reverse=True
    )

    for sender, pattern in sorted_patterns:
        print(f"{sender}")
        print(f"  Pattern: {pattern['pattern']} (based on {pattern['sample_size']} confirmed results)")
        print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Review triage results and confirm them into sender memory."
    )
    parser.add_argument("--all", action="store_true",
                        help="Confirm all high/medium-confidence results automatically, no prompting.")
    parser.add_argument("--show-memory", action="store_true",
                        help="Show the current state of sender memory and exit.")
    parser.add_argument("--clear", metavar="EMAIL",
                        help="Clear all memory for a specific sender email address.")
    parser.add_argument("--checkpoint", default=CHECKPOINT_PATH,
                        help=f"Path to triage results checkpoint (default: {CHECKPOINT_PATH})")
    args = parser.parse_args()

    initialize_db(DB_PATH)

    # --show-memory: just display and exit
    if args.show_memory:
        show_memory_state(DB_PATH)
        raise SystemExit(0)

    # --clear: reset a sender's history
    if args.clear:
        clear_sender_history(args.clear, DB_PATH)
        print(f"Cleared memory for {args.clear}.")
        raise SystemExit(0)

    # Load and display results
    results = load_checkpoint(args.checkpoint)
    display_results(results, show_reasoning=True)

    # Confirm either interactively or all at once
    if args.all:
        to_confirm = confirm_all(results)
        print(f"Auto-confirming {len(to_confirm)} results (skipping parse errors and low-confidence)...")
    else:
        to_confirm = confirm_interactive(results)

    if not to_confirm:
        print("Nothing confirmed. Memory unchanged.")
        raise SystemExit(0)

    # Write to memory
    result = confirm_batch_results(to_confirm, DB_PATH)
    print(f"\n✓ {result['confirmed']} results written to memory.")
    if result["skipped_parse_errors"]:
        print(f"  ({result['skipped_parse_errors']} parse errors skipped automatically.)")

    print("\nUpdated memory state:")
    show_memory_state(DB_PATH)
