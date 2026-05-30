"""
email_service.py  –  Email delivery via Google Apps Script webhook.

Instead of running an SMTP server or paying for an email provider,
we relay emails through a Google Apps Script (GAS) deployed as a
web app. The script runs in Google's infrastructure and sends emails
via Gmail.

Workflow:
    1. Our Python code calls send_email() with recipient, subject, HTML body.
    2. send_email() POSTs a JSON payload to the GAS web app URL.
    3. GAS processes the request and returns HTTP 302 (a redirect) on success.
    4. We do NOT follow that redirect — the 302 itself is our success signal.

*** WHY allow_redirects=False? ***
    Google Apps Script always responds to a POST with an HTTP 302 redirect to
    script.googleusercontent.com. If you follow the redirect (allow_redirects=True),
    the final response is a 200 whose body may or may not contain "Success",
    making success detection unreliable. With allow_redirects=False we capture the
    302 directly — it is the definitive success signal from GAS.

Usage:
    from app.services.email_service import send_email, render_template

    html = render_template("welcome.html", NAME="Alice", EMAIL="alice@example.com")
    send_email("alice@example.com", "Welcome!", html)
"""

import logging
from pathlib import Path
from typing import Optional, List  # List is needed for the attachments type hint

import requests
from app.config import settings

logger = logging.getLogger(__name__)

# Build the path to the email HTML templates directory.
# Path(__file__) is this file's path; we go up two levels to reach app/,
# then down into templates/email/.
_TEMPLATE_DIR = Path(__file__).parent.parent / "templates" / "email"


def render_template(name: str, **kwargs) -> str:
    """Load an HTML email template and substitute {{KEY}} placeholders.

    Templates live in app/templates/email/ and use {{KEY}} syntax.
    For example, a template containing {{NAME}} gets the value of NAME=...

    Args:
        name:     Filename of the template (e.g., "welcome.html").
        **kwargs: Placeholder name → value pairs to substitute.

    Returns:
        The rendered HTML string with all {{KEY}} tokens replaced.

    Example:
        html = render_template("welcome.html", NAME="Alice", EMAIL="a@b.com")
    """
    path = _TEMPLATE_DIR / name
    html = path.read_text(encoding="utf-8")
    # Replace each {{KEY}} placeholder with the corresponding string value
    for key, value in kwargs.items():
        html = html.replace(f"{{{{{key}}}}}", str(value) if value is not None else "")
    return html


def send_email(
    to: str,
    subject: str,
    html_body: str,
    attachments: Optional[List[dict]] = None,
) -> bool:
    """Send an HTML email (with optional file attachments) via the Google Apps Script relay.

    *** FIX (root cause of emails not arriving) ***
    Previously used allow_redirects=True, which caused requests to follow
    the GAS 302 redirect automatically. The final page body rarely contained
    the exact string "Success", so the function always returned False and
    emails were silently dropped. Now we use allow_redirects=False and treat
    HTTP 302 directly as the success signal.

    If GOOGLE_SCRIPT_URL or EMAIL_TOKEN are not set (e.g., missing from the
    Render.com environment variables), this function logs a warning and returns
    False without raising — check the server logs if emails aren't arriving.

    Args:
        to:          Recipient email address.
        subject:     Email subject line.
        html_body:   Full HTML content for the email body.
        attachments: Optional list of file attachment dicts. Each dict must have:
                       "fileName" (str)  – name shown in the email, e.g. "export.csv"
                       "mimeType" (str)  – file type, e.g. "text/csv" or "application/pdf"
                       "data"     (str)  – the file content Base64-encoded as an ASCII string
                     The GAS script decodes this with Utilities.base64Decode() and passes
                     the resulting Blob to MailApp.sendEmail(attachments=[...]).
                     Defaults to None (no attachments) for all regular notification emails.

    Returns:
        True on success (GAS returned 302), False on failure.

    Example with attachment:
        csv_b64 = base64.b64encode(csv_text.encode("utf-8")).decode("ascii")
        send_email(
            "user@example.com",
            "Your export",
            html,
            attachments=[{"fileName": "data.csv", "mimeType": "text/csv", "data": csv_b64}],
        )
    """
    # Guard: if email env vars are not configured, log clearly and skip
    if not settings.google_script_url or not settings.email_token:
        logger.warning(
            "Email skipped — GOOGLE_SCRIPT_URL or EMAIL_TOKEN not set. "
            "Add them as environment variables on your deployment server (Render dashboard)."
        )
        return False

    # Build the JSON payload dictionary that the GAS web app expects.
    # This is the data body that will be sent inside the POST request.
    payload = {
        "token":       settings.email_token,  # Secret token — GAS checks this before sending
        "to":          to,                    # Recipient's email address
        "subject":     subject,               # The subject line of the email
        "body":        html_body,             # The full HTML content of the email body
        "name":        settings.email_name,   # "From" display name (e.g. "Smart Sleep Service")
        # attachments is a list of dicts. For regular emails this is [].
        # For the export email it contains one dict with the base64-encoded CSV file.
        # `attachments or []` converts None (the default) into an empty list safely.
        "attachments": attachments or [],
    }

    try:
        # requests.post() sends an HTTP POST request to the given URL.
        # `json=payload` automatically converts the dict to a JSON string and sets
        # the Content-Type header to "application/json".
        resp = requests.post(
            settings.google_script_url,
            json=payload,
            timeout=20,          # Give up after 20 seconds if no response
            # ─────────────────────────────────────────────────────────────────
            # *** THE KEY FIX — why emails weren't arriving ***
            #
            # HTTP redirects explained for beginners:
            #   When you visit a short URL like bit.ly/abc, the server responds
            #   with HTTP 302 ("Found — go here instead") pointing to the real URL.
            #   Browsers follow this automatically. HTTP clients (like requests) can
            #   too — but only if allow_redirects=True.
            #
            # Google Apps Script always responds with 302 on success.
            #
            # BEFORE the fix: allow_redirects=True caused requests to follow
            #   the 302 to script.googleusercontent.com. The final response was
            #   200 with an unpredictable body — success detection always failed.
            #
            # AFTER the fix: allow_redirects=False stops at the 302.
            #   The 302 itself IS the success signal — we don't need to follow it.
            # ─────────────────────────────────────────────────────────────────
            allow_redirects=False,
        )

        # HTTP 302 = "Found / Redirect" — this is GAS saying "request accepted"
        if resp.status_code == 302:
            # %s is a logging format placeholder — logger fills in the values.
            # Using logger.info (not print) because production servers collect logs.
            logger.info("Email sent to %s — subject: %s", to, subject)
            return True

        # HTTP 200 = "OK" — some GAS deployments skip the redirect and respond directly
        if resp.status_code == 200 and "success" in resp.text.lower():
            logger.info("Email sent to %s (200 OK) — subject: %s", to, subject)
            return True

        # Any other status code means something went wrong.
        # Log the full response body so we can debug what GAS returned.
        # resp.text[:400] limits the log line to 400 characters (avoids giant logs).
        logger.warning(
            "Email send failed: status=%s body=%s",
            resp.status_code,
            resp.text[:400],
        )
        return False

    except requests.exceptions.Timeout:
        # Raised when the server doesn't respond within the timeout (20 seconds).
        # Common if GAS is slow or the network is down.
        logger.error("Email send timed out after 20s — GAS may be unresponsive")
        return False
    except Exception as exc:
        # Catch-all for any other error: DNS failure, SSL error, etc.
        logger.error("Email send exception: %s", exc)
        return False
