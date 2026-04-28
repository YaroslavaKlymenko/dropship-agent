"""Gmail API client for My-Art dropshipping agent."""

import base64
import os
from email.mime.text import MIMEText
from email.utils import parsedate_to_datetime

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

# Paths relative to project root (where the script is run from)
_CREDENTIALS_FILE = "credentials.json"
_TOKEN_FILE = "token.json"


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def get_gmail_service():
    """Build and return an authenticated Gmail API service.

    On first run, opens a browser for OAuth2 consent and saves token.json.
    On subsequent runs, loads token.json and refreshes it if expired.

    Returns:
        Google API service object for Gmail v1.
    """
    creds: Credentials | None = None

    if os.path.exists(_TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(_TOKEN_FILE, _SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(_CREDENTIALS_FILE, _SCOPES)
            creds = flow.run_local_server(port=0)
        with open(_TOKEN_FILE, "w") as token_file:
            token_file.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


# ---------------------------------------------------------------------------
# Reading emails
# ---------------------------------------------------------------------------

def list_recent_emails(service, max_results: int = 10, query: str = "is:unread") -> list:
    """List recent emails matching a Gmail query.

    Args:
        service: Authenticated Gmail service object.
        max_results: Maximum number of messages to return.
        query: Gmail search query, e.g. 'is:unread' or
               'is:unread from:partner@example.com'.

    Returns:
        List of dicts with 'id' and 'threadId' keys.
    """
    result = (
        service.users()
        .messages()
        .list(userId="me", maxResults=max_results, q=query)
        .execute()
    )
    return result.get("messages", [])


def get_email_details(service, msg_id: str) -> dict:
    """Fetch and parse full details of a single email.

    Extracts only text/plain parts from multipart payloads.
    Cleans from_email to a bare address (strips display name).

    Args:
        service: Authenticated Gmail service object.
        msg_id: Gmail message ID.

    Returns:
        Dict with keys: gmail_message_id, gmail_thread_id, from_email,
        to_email, subject, body_text, received_at.
    """
    msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()

    headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}

    from_raw = headers.get("from", "")
    from_email = _extract_email_address(from_raw)
    to_email = _extract_email_address(headers.get("to", ""))
    subject = headers.get("subject", "")

    date_str = headers.get("date", "")
    try:
        received_at = parsedate_to_datetime(date_str).isoformat() if date_str else ""
    except Exception:
        received_at = ""

    body_text = _extract_plain_text(msg["payload"])

    return {
        "gmail_message_id": msg["id"],
        "gmail_thread_id": msg["threadId"],
        "from_email": from_email,
        "to_email": to_email,
        "subject": subject,
        "body_text": body_text,
        "received_at": received_at,
    }


def mark_as_read(service, msg_id: str) -> None:
    """Remove the UNREAD label from a message.

    Args:
        service: Authenticated Gmail service object.
        msg_id: Gmail message ID.
    """
    service.users().messages().modify(
        userId="me",
        id=msg_id,
        body={"removeLabelIds": ["UNREAD"]},
    ).execute()


# ---------------------------------------------------------------------------
# Writing emails
# ---------------------------------------------------------------------------

def create_draft(
    service,
    to: str,
    subject: str,
    body: str,
    thread_id: str | None = None,
    original_message_id: str | None = None,
) -> dict:
    """Create a Gmail draft (does not send).

    When thread_id is provided the draft is attached as a proper reply:
    the MIME message carries In-Reply-To / References headers (fetched from
    the original message) so Gmail shows it inside the existing thread.

    Args:
        service: Authenticated Gmail service object.
        to: Recipient email address.
        subject: Email subject (a 'Re: ' prefix is added automatically if
            the message is a reply and the subject doesn't already have one).
        body: Plain-text email body.
        thread_id: Gmail thread ID. Attaches the draft to that thread.
        original_message_id: Gmail internal message ID of the email being
            replied to. Used to fetch the RFC 2822 Message-ID header so
            Gmail can set In-Reply-To / References correctly.

    Returns:
        Created draft object returned by the Gmail API.
    """
    # Normalise subject for replies — never produce "Re: Re: …"
    if thread_id and not subject.startswith("Re: "):
        subject = f"Re: {subject}"

    mime_message = MIMEText(body, "plain", "utf-8")
    mime_message["to"] = to
    mime_message["subject"] = subject

    if original_message_id:
        rfc_msg_id = _get_rfc_message_id(service, original_message_id)
        if rfc_msg_id:
            mime_message["In-Reply-To"] = rfc_msg_id
            mime_message["References"] = rfc_msg_id

    raw = base64.urlsafe_b64encode(mime_message.as_bytes()).decode()
    draft_body: dict = {"message": {"raw": raw}}
    if thread_id:
        draft_body["message"]["threadId"] = thread_id

    try:
        return service.users().drafts().create(userId="me", body=draft_body).execute()
    except Exception as e:
        if thread_id and ("invalid" in str(e).lower() or "thread" in str(e).lower()):
            print(
                f"[gmail_client.create_draft] Warning: thread_id {thread_id!r} not found "
                f"in Gmail ({e}). Retrying as standalone draft."
            )
            draft_body["message"].pop("threadId", None)
            return service.users().drafts().create(userId="me", body=draft_body).execute()
        raise


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_rfc_message_id(service, gmail_msg_id: str) -> str | None:
    """Return the RFC 2822 Message-ID header value for a Gmail message.

    Args:
        service: Authenticated Gmail service object.
        gmail_msg_id: Gmail internal message ID (e.g. '18f2abc3d4e5f6').

    Returns:
        The Message-ID string (e.g. '<CABc123@mail.gmail.com>'),
        or None if not found or on any API error.
    """
    try:
        msg = (
            service.users()
            .messages()
            .get(
                userId="me",
                id=gmail_msg_id,
                format="metadata",
                metadataHeaders=["Message-ID"],
            )
            .execute()
        )
        headers = {
            h["name"].lower(): h["value"]
            for h in msg.get("payload", {}).get("headers", [])
        }
        return headers.get("message-id")
    except Exception as e:
        print(
            f"[gmail_client] Warning: could not fetch Message-ID for "
            f"{gmail_msg_id!r}: {e}"
        )
        return None


def _extract_email_address(value: str) -> str:
    """Strip display name from an email header value.

    "John Doe <john@example.com>" → "john@example.com"
    "john@example.com" → "john@example.com"
    """
    if "<" in value and ">" in value:
        return value.split("<")[1].rstrip(">").strip()
    return value.strip()


def _extract_plain_text(payload: dict) -> str:
    """Recursively find and decode the first text/plain part.

    Args:
        payload: Gmail message payload dict.

    Returns:
        Decoded plain-text string, or empty string if none found.
    """
    mime_type = payload.get("mimeType", "")

    if mime_type == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
        return ""

    for part in payload.get("parts", []):
        text = _extract_plain_text(part)
        if text:
            return text

    return ""


# ---------------------------------------------------------------------------
# __main__
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    service = get_gmail_service()
    print("Gmail connected successfully!")

    messages = list_recent_emails(service, max_results=3)
    print(f"\nFound {len(messages)} unread email(s):\n")

    for msg_stub in messages:
        details = get_email_details(service, msg_stub["id"])
        preview = details["body_text"][:80].replace("\n", " ")
        print(f"From:    {details['from_email']}")
        print(f"Subject: {details['subject']}")
        print(f"Body:    {preview}")
        print()
