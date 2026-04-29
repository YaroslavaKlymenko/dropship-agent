"""Entry point for the My-Art dropship agent pipeline.

Reads unread Gmail messages, saves them to the DB, classifies each one,
executes the appropriate action (draft, reservation, escalation), and
optionally marks messages as read.

Usage:
    python -m src.main
    python -m src.main --max-emails 5 --dry-run
    python -m src.main --no-mark-read
"""

import argparse
import sys
import time
from datetime import datetime

from src import classifier, gmail_client


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run_pipeline(
    max_emails: int = 20,
    dry_run: bool = False,
    mark_read: bool = True,
) -> dict:
    """Fetch unread emails, classify them, and execute intent actions.

    Args:
        max_emails: Maximum number of unread emails to fetch from Gmail.
        dry_run: If True, fetch and classify emails but skip all writes:
            no DB saves, no drafts, no mark-as-read.  Prints what would
            happen instead.
        mark_read: If True (and not dry_run), mark each processed message
            as read in Gmail after handling it.

    Returns:
        Stats dict with keys: fetched, new, duplicates, classified,
        drafts_created, needs_review, errors, duration_seconds.
    """
    stats: dict = {
        "fetched": 0,
        "new": 0,
        "duplicates": 0,
        "classified": 0,
        "drafts_created": 0,
        "needs_review": 0,
        "errors": 0,
        "duration_seconds": 0.0,
    }

    start = time.time()

    print("Connecting to Gmail…")
    service = gmail_client.get_gmail_service()

    print(f"Fetching up to {max_emails} unread email(s)…\n")
    messages = gmail_client.list_recent_emails(service, max_results=max_emails)
    stats["fetched"] = len(messages)

    if not messages:
        print("No unread emails found.")
        stats["duration_seconds"] = round(time.time() - start, 1)
        return stats

    for i, msg_stub in enumerate(messages, start=1):
        subject = "(unknown)"
        try:
            details = gmail_client.get_email_details(service, msg_stub["id"])
            subject = details.get("subject", "(no subject)")
            from_email = details.get("from_email", "")

            print(f"[{i}/{stats['fetched']}] {from_email} — {subject}")

            # ------------------------------------------------------------------
            # Dry-run: classify only, no writes
            # ------------------------------------------------------------------
            if dry_run:
                from src.llm.factory import get_llm_client
                llm = get_llm_client()
                classification = llm.classify_email(
                    subject=details.get("subject", ""),
                    body=details.get("body_text", ""),
                )
                intent = classification.get("intent", "other")
                confidence = classification.get("confidence", 0.0)
                skus = classification.get("product_skus") or []
                print(
                    f"          [DRY RUN] intent={intent}  "
                    f"confidence={confidence:.2f}  skus={skus or 'none'}"
                )
                print(
                    "          [DRY RUN] Skipped: DB save, draft creation, "
                    "mark-as-read.\n"
                )
                stats["new"] += 1
                continue

# ------------------------------------------------------------------
            # Build email_record directly (no DB)
            # ------------------------------------------------------------------
            email_record = {
                "id": msg_stub["id"],
                "gmail_message_id": details.get("gmail_message_id", msg_stub["id"]),
                "gmail_thread_id": details.get("gmail_thread_id", ""),
                "from_email": details.get("from_email", ""),
                "subject": details.get("subject", ""),
                "body_text": details.get("body_text", ""),
                "received_at": details.get("received_at", ""),
            }

            stats["new"] += 1

            # ------------------------------------------------------------------
            # Classify + handle
            # ------------------------------------------------------------------
            result = classifier.process_email(email_record)
            stats["classified"] += 1

            if result.get("draft_id"):
                stats["drafts_created"] += 1
            if result.get("needs_human_review"):
                stats["needs_review"] += 1
            if result.get("error"):
                stats["errors"] += 1

            _print_result(result)

            # ------------------------------------------------------------------
            # Mark as read
            # ------------------------------------------------------------------
            if mark_read:
                gmail_client.mark_as_read(service, msg_stub["id"])

        except Exception as e:
            stats["errors"] += 1
            print(f"          ERROR processing '{subject}': {e}\n")

    stats["duration_seconds"] = round(time.time() - start, 1)
    return stats


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _print_result(result: dict) -> None:
    """Print a single-email processing result in a human-readable format."""
    review_label = "YES — needs owner review" if result.get("needs_human_review") else "no"
    draft_label = result.get("draft_id") or "none"
    error_label = result.get("error") or "none"

    print(f"          intent  : {result.get('intent', '?')}")
    print(f"          action  : {result.get('action_taken', '?')}")
    print(f"          draft   : {draft_label}")
    print(f"          review  : {review_label}")
    if result.get("error"):
        print(f"          error   : {error_label}")
    print()


def _print_stats(stats: dict) -> None:
    """Print the final pipeline stats summary."""
    width = 44
    print("=" * width)
    print("Pipeline complete — summary")
    print("-" * width)
    print(f"  Fetched from Gmail   : {stats['fetched']}")
    print(f"  New (saved to DB)    : {stats['new']}")
    print(f"  Duplicates skipped   : {stats['duplicates']}")
    print(f"  Classified           : {stats['classified']}")
    print(f"  Drafts created       : {stats['drafts_created']}")
    print(f"  Needs human review   : {stats['needs_review']}")
    print(f"  Errors               : {stats['errors']}")
    print(f"  Duration             : {stats['duration_seconds']}s")
    print("=" * width)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="My-Art dropship agent — process unread partner emails.",
    )
    parser.add_argument(
        "--max-emails",
        type=int,
        default=20,
        metavar="INT",
        help="Maximum number of unread emails to fetch (default: 20).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Classify emails without writing anything: no DB saves, "
            "no drafts, no mark-as-read."
        ),
    )
    parser.add_argument(
        "--no-mark-read",
        action="store_true",
        help="Process emails but leave them unread in Gmail.",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# __main__
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    args = _parse_args()

    mark_read = not args.dry_run and not args.no_mark_read

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("=" * 60)
    print("Dropship Agent Pipeline")
    print(f"Started: {now}")
    print(
        f"Config:  max_emails={args.max_emails}, "
        f"dry_run={args.dry_run}, "
        f"mark_read={mark_read}"
    )
    print("=" * 60)
    print()

    stats = run_pipeline(
        max_emails=args.max_emails,
        dry_run=args.dry_run,
        mark_read=mark_read,
    )

    _print_stats(stats)

    sys.exit(1 if stats["errors"] > 0 else 0)
