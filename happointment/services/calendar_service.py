"""
Google Calendar integration (OAuth 2.0).

Design simplification (documented in DESIGN.md / README): rather than
running a separate OAuth flow per patient/doctor (which needs a verified
app + real Google accounts for every test user), the clinic's admin
authorizes ONE Google account once via /admin/google/connect. Events for
every booking are created on that single clinic calendar, with the patient
and doctor added as invitees (they get their own calendar invite email
from Google directly). This is the standard pattern for clinic-style
booking tools and satisfies "Google Calendar event created for both."

If no token has been authorized yet, calendar calls are silently skipped
(return None) rather than raising — booking must never fail because of
calendar/notification issues.
"""
import os
import json
from flask import current_app
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


def get_flow(state=None):
    client_config = _load_client_config()
    return Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        redirect_uri=current_app.config["GOOGLE_REDIRECT_URI"],
        state=state,
    )


def _load_client_config() -> dict:
    """Loads the OAuth client config from either GOOGLE_CLIENT_SECRETS_JSON
    (the raw JSON content, pasted directly into an env var — simplest for
    hosts like Render where "secret files" have path ambiguity once a
    custom root directory is set) or, if that's not set, from the JSON
    file at GOOGLE_CLIENT_SECRETS_FILE (the normal local-dev path)."""
    raw_json = current_app.config.get("GOOGLE_CLIENT_SECRETS_JSON")
    if raw_json:
        return json.loads(raw_json)
    with open(current_app.config["GOOGLE_CLIENT_SECRETS_FILE"]) as f:
        return json.load(f)


def has_client_config() -> bool:
    if current_app.config.get("GOOGLE_CLIENT_SECRETS_JSON"):
        return True
    return os.path.exists(current_app.config["GOOGLE_CLIENT_SECRETS_FILE"])


def _load_credentials():
    token_file = current_app.config["GOOGLE_TOKEN_FILE"]
    if not os.path.exists(token_file):
        return None
    with open(token_file) as f:
        data = json.load(f)
    creds = Credentials.from_authorized_user_info(data, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(token_file, "w") as f:
            f.write(creds.to_json())
    return creds


def save_credentials(creds: Credentials):
    os.makedirs(os.path.dirname(current_app.config["GOOGLE_TOKEN_FILE"]), exist_ok=True)
    with open(current_app.config["GOOGLE_TOKEN_FILE"], "w") as f:
        f.write(creds.to_json())


def is_connected() -> bool:
    return _load_credentials() is not None


def _service():
    creds = _load_credentials()
    if creds is None:
        return None
    return build("calendar", "v3", credentials=creds)


def create_event(summary: str, description: str, start_iso: str, end_iso: str,
                  attendee_emails: list[str]) -> str | None:
    service = _service()
    if service is None:
        current_app.logger.info("Google Calendar not connected — skipping event creation.")
        return None
    try:
        event = {
            "summary": summary,
            "description": description,
            # Google's API requires either a UTC-offset in the dateTime string
            # or an explicit timeZone — bare "2026-08-26T11:00:00" without
            # either is rejected with a 400. Our slot times are stored as
            # naive local clinic time, so we declare the zone explicitly.
            "start": {"dateTime": start_iso, "timeZone": current_app.config["CLINIC_TIMEZONE"]},
            "end": {"dateTime": end_iso, "timeZone": current_app.config["CLINIC_TIMEZONE"]},
            "attendees": [{"email": e} for e in attendee_emails],
        }
        created = service.events().insert(
            calendarId="primary", body=event, sendUpdates="all"
        ).execute()
        return created.get("id")
    except Exception as exc:
        current_app.logger.warning(f"Calendar event creation failed: {exc}")
        return None


def update_event(event_id: str, **fields) -> bool:
    service = _service()
    if service is None or not event_id:
        return False
    try:
        event = service.events().get(calendarId="primary", eventId=event_id).execute()
        event.update(fields)
        service.events().update(
            calendarId="primary", eventId=event_id, body=event, sendUpdates="all"
        ).execute()
        return True
    except Exception as exc:
        current_app.logger.warning(f"Calendar event update failed: {exc}")
        return False


def delete_event(event_id: str) -> bool:
    service = _service()
    if service is None or not event_id:
        return False
    try:
        service.events().delete(
            calendarId="primary", eventId=event_id, sendUpdates="all"
        ).execute()
        return True
    except Exception as exc:
        current_app.logger.warning(f"Calendar event deletion failed: {exc}")
        return False