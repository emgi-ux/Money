"""Transactional email via SMTP (any provider: SES, Postmark, Resend, Mailgun...).

Configure SMTP_HOST, SMTP_PORT (587), SMTP_USER, SMTP_PASSWORD and MAIL_FROM.
Without SMTP_HOST, messages are written to the log instead (local development).
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage

log = logging.getLogger(__name__)
outbox: list[EmailMessage] = []  # last messages in log-only mode (inspected by tests)


def send_email(to: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = os.environ.get("MAIL_FROM", "Money <no-reply@localhost>")
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    host = os.environ.get("SMTP_HOST")
    if not host:
        outbox.append(msg)
        del outbox[:-20]
        log.warning("SMTP_HOST not set; email to %s not sent:\n%s", to, body)
        return
    port = int(os.environ.get("SMTP_PORT", "587"))
    with smtplib.SMTP(host, port, timeout=15) as smtp:
        smtp.starttls()
        if os.environ.get("SMTP_USER"):
            smtp.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
        smtp.send_message(msg)
