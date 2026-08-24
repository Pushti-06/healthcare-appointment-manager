"""
Email notifications. Uses plain smtplib against SMTP_HOST/PORT/USER/PASSWORD
(works with Gmail app passwords, SendGrid SMTP relay, Mailgun SMTP, etc. —
any provider works since this doesn't depend on a vendor SDK).

Every send attempt is logged to EmailLog. If SMTP isn't configured (no
SMTP_HOST in .env), emails are "simulated" — written to the log and to
stdout — so the app is fully runnable/demoable without real credentials.
Failed sends are retried by the background scheduler (see scheduler.py)
up to EMAIL_MAX_RETRIES times.
"""
import smtplib
from email.mime.text import MIMEText
from flask import current_app
from extensions import db
from models import EmailLog


def _send_raw(to_email: str, subject: str, body: str):
    cfg = current_app.config
    if not cfg["SMTP_HOST"]:
        # No SMTP configured -> simulate so the whole flow still works end to end.
        print(f"[SIMULATED EMAIL] to={to_email} subject={subject!r}\n{body}\n")
        return "simulated"

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = cfg["SMTP_FROM"]
    msg["To"] = to_email

    with smtplib.SMTP(cfg["SMTP_HOST"], cfg["SMTP_PORT"], timeout=10) as server:
        server.starttls()
        if cfg["SMTP_USER"]:
            server.login(cfg["SMTP_USER"], cfg["SMTP_PASSWORD"])
        server.sendmail(cfg["SMTP_FROM"], [to_email], msg.as_string())
    return "sent"


def send_email(to_email: str, subject: str, body: str, appointment_id: int | None = None) -> EmailLog:
    log = EmailLog(to_email=to_email, subject=subject, body=body, appointment_id=appointment_id)
    db.session.add(log)
    db.session.flush()  # get an id without a separate commit

    try:
        status = _send_raw(to_email, subject, body)
        log.status = status
        log.attempts += 1
    except Exception as exc:
        log.status = "failed"
        log.attempts += 1
        log.last_error = str(exc)[:500]
        current_app.logger.warning(f"Email send failed to {to_email}: {exc}")

    db.session.commit()
    return log


def retry_failed_emails():
    """Called periodically by the scheduler."""
    max_retries = current_app.config["EMAIL_MAX_RETRIES"]
    failed = EmailLog.query.filter(
        EmailLog.status == "failed", EmailLog.attempts < max_retries
    ).all()
    for log in failed:
        try:
            status = _send_raw(log.to_email, log.subject, log.body)
            log.status = status
            log.attempts += 1
            log.last_error = None
        except Exception as exc:
            log.status = "failed"
            log.attempts += 1
            log.last_error = str(exc)[:500]
    if failed:
        db.session.commit()
