#!/usr/bin/env python3
"""Fetch PDF attachments from Gmail using the Gmail API.

Authenticates via OAuth2, searches for emails matching sender/subject filters,
and downloads PDF attachments to a local directory. Idempotent — skips files
that already exist in the output directory.

Usage:
    python fetch_gmail.py --sender "noreply@example.com" --subject "statement" \
        --output download/standard_charted/ --dry-run
"""

import argparse
import base64
import json
import os
import sys
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
DEFAULT_CREDENTIALS = "credentials.json"
DEFAULT_TOKEN = "token.json"


def authenticate(credentials_path: str, token_path: str) -> Credentials:
    """Authenticate with Gmail API via OAuth2.

    On first run, opens a browser for consent. Subsequent runs use cached token.
    """
    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(credentials_path):
                print(f"Error: credentials file not found: {credentials_path}")
                print("Download OAuth2 credentials from Google Cloud Console.")
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w") as f:
            f.write(creds.to_json())

    return creds


def build_query(sender: str, subject: str, after: str | None = None) -> str:
    """Build a Gmail search query string."""
    parts = []
    if sender:
        parts.append(f"from:{sender}")
    if subject:
        parts.append(f"subject:{subject}")
    parts.append("has:attachment")
    if after:
        parts.append(f"after:{after}")
    return " ".join(parts)


def fetch_attachments(
    service,
    query: str,
    output_dir: Path,
    dry_run: bool = False,
) -> tuple[int, int]:
    """Search Gmail and download PDF attachments.

    Returns (downloaded_count, skipped_count).
    """
    results = service.users().messages().list(userId="me", q=query).execute()
    messages = results.get("messages", [])

    if not messages:
        print("No matching emails found.")
        return 0, 0

    # Paginate through all results
    all_messages = list(messages)
    while "nextPageToken" in results:
        results = (
            service.users()
            .messages()
            .list(userId="me", q=query, pageToken=results["nextPageToken"])
            .execute()
        )
        all_messages.extend(results.get("messages", []))

    print(f"Found {len(all_messages)} matching email(s).")

    downloaded = 0
    skipped = 0

    for msg_info in all_messages:
        msg = (
            service.users()
            .messages()
            .get(userId="me", id=msg_info["id"])
            .execute()
        )
        payload = msg.get("payload", {})
        parts = payload.get("parts", [])

        # Get email subject for logging
        headers = payload.get("headers", [])
        email_subject = next(
            (h["value"] for h in headers if h["name"].lower() == "subject"), "(no subject)"
        )

        for part in parts:
            filename = part.get("filename", "")
            if not filename.lower().endswith(".pdf"):
                continue

            dest = output_dir / filename
            if dest.exists():
                print(f"  Skip (exists): {filename}")
                skipped += 1
                continue

            if dry_run:
                print(f"  [DRY RUN] Would download: {filename} (from: {email_subject})")
                skipped += 1
                continue

            attachment_id = part["body"].get("attachmentId")
            if not attachment_id:
                continue

            att = (
                service.users()
                .messages()
                .attachments()
                .get(userId="me", messageId=msg_info["id"], id=attachment_id)
                .execute()
            )
            data = base64.urlsafe_b64decode(att["data"])

            output_dir.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            print(f"  Downloaded: {filename} ({len(data):,} bytes)")
            downloaded += 1

    return downloaded, skipped


def load_config(config_path: str) -> dict:
    """Load gmail settings from config.json if present."""
    if not os.path.exists(config_path):
        return {}
    with open(config_path) as f:
        cfg = json.load(f)
    return cfg.get("gmail", {})


def main():
    parser = argparse.ArgumentParser(
        description="Fetch PDF attachments from Gmail."
    )
    parser.add_argument("--sender", help="Filter by sender email address")
    parser.add_argument("--subject", help="Filter by subject keyword")
    parser.add_argument("--output", "-o", help="Output directory for downloaded PDFs")
    parser.add_argument(
        "--credentials",
        default=DEFAULT_CREDENTIALS,
        help=f"Path to OAuth2 credentials JSON (default: {DEFAULT_CREDENTIALS})",
    )
    parser.add_argument(
        "--token",
        default=DEFAULT_TOKEN,
        help=f"Path to cached token file (default: {DEFAULT_TOKEN})",
    )
    parser.add_argument(
        "--after",
        help="Only fetch emails after this date (YYYY/MM/DD)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List attachments without downloading",
    )
    parser.add_argument(
        "--config",
        default="config.json",
        help="Path to config.json for default settings",
    )

    args = parser.parse_args()

    # Load config defaults — only apply when no CLI flags given at all
    config = load_config(args.config)
    has_cli_filter = args.sender is not None or args.subject is not None
    if has_cli_filter:
        sender = args.sender
        subject = args.subject
    else:
        sender = config.get("sender")
        subject = config.get("subject")
    output = args.output or config.get("output")

    if not sender and not subject:
        parser.error("At least one of --sender or --subject is required.")
    if not output:
        parser.error("--output is required (or set gmail.output in config.json).")

    output_dir = Path(output)
    query = build_query(sender, subject, args.after)
    print(f"Gmail query: {query}")

    creds = authenticate(args.credentials, args.token)
    service = build("gmail", "v1", credentials=creds)

    downloaded, skipped = fetch_attachments(service, query, output_dir, args.dry_run)

    print(f"\nSummary: {downloaded} new file(s) downloaded, {skipped} skipped.")


if __name__ == "__main__":
    main()
