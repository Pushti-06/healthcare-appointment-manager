# Healthcare Appointment & Follow-up Manager

A clinic appointment platform with separate **patient**, **doctor**, and **admin**
portals: symptom-aware booking, LLM pre-visit and post-visit summaries, email
notifications, Google Calendar sync, and medication reminders.

Built with Flask + SQLAlchemy + SQLite (swappable to Postgres), server-rendered
templates (no build step needed), and a pluggable LLM/email/calendar layer that
degrades gracefully when those services aren't configured — the app is fully
runnable and demoable with zero external API keys.

**Live demo:** [your-app.onrender.com](#) &nbsp;·&nbsp; **Design write-up:** [DESIGN.md](./DESIGN.md)

<!-- Once deployed, replace the # above with your actual Render/Railway URL. -->

### What's implemented

| | |
|---|---|
| 🔐 Role-based auth | Separate patient / doctor / admin portals |
| 📅 Safe booking | DB-level unique constraint prevents double-booking, even under concurrent requests |
| 🏖️ Leave handling | Marking a doctor on leave auto-cancels affected bookings and emails patients |
| 🤖 AI summaries | LLM-generated pre-visit urgency + questions, and post-visit patient-friendly summary — with a rule-based fallback if no LLM key is set |
| 📧 Email | Booking confirmations, reminders, cancellations — logged and retried on failure |
| 🗓️ Google Calendar | OAuth 2.0 sync — events created on booking, deleted on cancellation |
| 💊 Medication reminders | Background job fires reminder emails on the prescribed schedule |

### Quick links

- [Setup guide](#1-quick-start-local) · [Deployment](#2-deploying-render--railway--any-gunicorn-host)
- [LLM setup](#3-llm-setup) · [Email setup](#4-email-setup) · [Google Calendar setup](#5-google-calendar-setup)
- [DB schema](#6-database-schema) · [API routes](#7-api--route-map)
- [System design write-up](./DESIGN.md)

---

## 1. Quick start (local)

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env            # edit values as needed (all optional except SECRET_KEY)

python app.py                   # runs on http://localhost:5000
```

On first run the app creates `instance/app.db` (SQLite) and seeds a default
admin account from `ADMIN_EMAIL` / `ADMIN_PASSWORD` in `.env`
(defaults: `admin@clinic.local` / `admin123` — change these before deploying).

**Want it pre-populated for a demo instead of starting empty?** Run:
```bash
python seed_data.py
```
This adds **35 doctors across 14 departments** (Cardiology, Pediatrics,
Dermatology, Orthopedics, Neurology, Oncology, etc.), **70 patients**, and
**~280 appointments** spread across the last two months and the next two
weeks — a realistic mix of completed visits (with real pre- and
post-visit summaries already generated), upcoming bookings, and some
cancellations. Three doctors have an upcoming leave day with real
bookings deliberately left on it, so you can demo the
leave-conflict-cancellation flow live via Admin → that doctor → Manage
leave — it'll cancel the existing bookings and email the affected
patients on the spot. All synthetic data — safe to run anytime, and safe
to re-run (it skips anything already created).
Doctor logins: `firstname.lastname@clinic.local` / `doctor123`.
Patient logins: `firstname.lastname@example.com` / `patient123`.

Log in as admin → **Add doctor** → log in as that doctor to set working
hours/slot duration (or set them at creation) → register a patient account →
search doctors → book.

## 2. Deploying (Render / Railway / any Gunicorn host)

1. Push this repo to GitHub.
2. Create a new **Web Service** on Render (or Railway), pointing at the repo.
   - Build command: `pip install -r requirements.txt`
   - Start command: `gunicorn app:app` (already in `Procfile`)
3. Add the environment variables from `.env.example` in the host's dashboard.
   At minimum set `SECRET_KEY`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`.
4. For a persistent database, add a managed Postgres instance and set
   `DATABASE_URL` to its connection string (SQLite works for a demo but most
   free hosts wipe local disk on redeploy).
5. Redeploy. The admin account is auto-seeded on first boot.

## 3. LLM setup

No key needed to run — the app falls back to a deterministic rule-based
summarizer (keyword-based urgency detection + templated post-visit summary) so
grading/demoing never breaks on a missing/rate-limited key. To use a real LLM:

1. Get a free API key from [Groq](https://console.groq.com) (fast, generous
   free tier, OpenAI-compatible API) — or use OpenAI/any compatible provider.
2. Set in `.env`:
   ```
   LLM_API_KEY=your_key_here
   LLM_BASE_URL=https://api.groq.com/openai/v1
   LLM_MODEL=openai/gpt-oss-20b
   ```

**Prompts used** (from `services/llm_service.py`, as specified in the brief):

- **Pre-visit**: *"Analyse these symptoms and return: urgency level (Low /
  Medium / High), chief complaint, and three suggested questions for the
  doctor. Symptoms: `<symptoms>`"* — requested as strict JSON
  (`urgency`, `chief_complaint`, `questions[]`).
- **Post-visit**: *"Convert these clinical notes into a patient-friendly
  summary with medication schedule and follow-up steps: `<notes>`"* —
  requested as strict JSON (`summary`, `medication_schedule[]`, `follow_up[]`).

Any LLM failure (timeout, network error, malformed JSON, non-2xx) is caught,
logged, and silently replaced with the fallback — the `Appointment` row
records `llm_pre_visit_failed` / `llm_post_visit_failed` so the UI can show a
small "generated by fallback" note (visible on both dashboards).

**If you get a 404 from the LLM call** (visible in the terminal running
`python app.py`, since failures are logged there, not shown to the
patient): the model name in `LLM_MODEL` no longer exists. Groq retires and
adds models fairly often — check their current list at
[console.groq.com/docs/models](https://console.groq.com/docs/models) (or
`GET https://api.groq.com/openai/v1/models` with your key) and update
`LLM_MODEL` in `.env` to whatever's currently listed under "Production
Models," then restart the app (editing `.env` alone does **not** hot-reload
— Flask's reloader only watches `.py` files).

## 4. Email setup

No SMTP configured → emails are **simulated**: logged to `EmailLog` in the DB
and printed to stdout, so the full booking → confirmation → reminder →
cancellation flow is testable without credentials.

To send real email, set in `.env` (works with Gmail app passwords, SendGrid
SMTP relay, Mailgun SMTP, etc.):
```
SMTP_HOST=smtp.sendgrid.net
SMTP_PORT=587
SMTP_USER=apikey
SMTP_PASSWORD=your_sendgrid_api_key
SMTP_FROM=no-reply@yourclinic.com
```
Failed sends are retried automatically by the background scheduler, up to
`EMAIL_MAX_RETRIES` times.

## 5. Google Calendar setup

1. In [Google Cloud Console](https://console.cloud.google.com), create a
   project → enable the **Google Calendar API**.
2. Create an **OAuth 2.0 Client ID** (type: Web application). Add
   `http://localhost:5000/admin/google/callback` (and your deployed URL's
   equivalent) as an authorized redirect URI.
3. Download the client secrets JSON, save it as `client_secret.json` in the
   project root (path is configurable via `GOOGLE_CLIENT_SECRETS_FILE`).
4. Log in as admin → dashboard → **Connect** (next to Google Calendar) →
   approve access. This authorizes one clinic-wide calendar (see
   `services/calendar_service.py` docstring for why — single OAuth flow
   instead of one per patient/doctor, documented as a deliberate
   simplification in `DESIGN.md`).
5. From then on, every booking creates a calendar event with the patient and
   doctor added as invitees (Google emails them the invite directly); leave
   or cancellation deletes the event.

If never connected, calendar calls are silently skipped — booking still
works, it just won't create calendar events.

**If the connect button doesn't work:**
- Make sure `client_secret.json` is actually in the project root (same
  folder as `app.py`), not in a subfolder.
- The redirect URI in Google Cloud Console must match `GOOGLE_REDIRECT_URI`
  in `.env` **exactly** — same scheme (http vs https), same port, no
  trailing slash.
- Your Google account needs to be added as a **test user** on the OAuth
  consent screen while the app is unverified (Google Cloud Console →
  APIs & Services → OAuth consent screen → Test users), or Google blocks
  the login with an "app not verified" screen.
- Local `http://localhost` redirects are disabled by Google's OAuth
  library by default — the app already works around this for you when
  `GOOGLE_REDIRECT_URI` starts with `http://`, but only do this for local
  testing, never in a real deployment (use `https://` there).
- Any failure now shows a specific error message on the dashboard instead
  of crashing, which should say exactly what's wrong.
- If Connect succeeds and shows "connected" but events still don't appear
  on your calendar: set `CLINIC_TIMEZONE` in `.env` to your actual zone
  (defaults to `Asia/Kolkata`). Google's API rejects event times that don't
  carry an explicit time zone, and event-creation failures are logged to
  the terminal running `python app.py` rather than shown to the patient
  (a calendar hiccup should never block someone from booking) — check
  that terminal output if events still aren't showing up.

## 6. Database schema

| Table | Key columns | Notes |
|---|---|---|
| `users` | id, role, name, email, password_hash | role ∈ {patient, doctor, admin} |
| `doctor_profiles` | user_id (FK), specialization, working_hours_start/end, slot_duration_minutes | one-to-one with `users` |
| `leaves` | doctor_id (FK), date, reason | `UNIQUE(doctor_id, date)` |
| `appointments` | patient_id, doctor_id, slot_start, slot_end, status, symptoms_text, pre_visit_urgency, pre_visit_summary_json, post_visit_notes, post_visit_summary_json, calendar_event_id_*, llm_*_failed | **`UNIQUE(doctor_id, slot_start)`** — this is the double-booking guard, see `DESIGN.md` |
| `medication_reminders` | appointment_id (FK), medication_name, frequency_hours, next_due_at, times_sent, active | polled by the scheduler |
| `email_logs` | to_email, subject, status, attempts, last_error, appointment_id | every send attempt, for retry + audit |

## 7. API / route map

All routes are server-rendered (form POSTs), not a JSON API, per the
templates-based frontend — but the endpoint surface is:

| Route | Method | Role | Purpose |
|---|---|---|---|
| `/register`, `/login`, `/logout` | GET/POST | any | auth |
| `/patient/` | GET | patient | dashboard: list own appointments |
| `/patient/doctors` | GET | patient | search doctors by specialization |
| `/patient/doctors/<id>/book` | GET/POST | patient | view slots for a date, submit symptoms + book |
| `/patient/appointments/<id>` | GET | patient | view detail + post-visit summary |
| `/patient/appointments/<id>/cancel` | POST | patient | cancel own appointment |
| `/doctor/` | GET | doctor | dashboard: upcoming appointments |
| `/doctor/appointments/<id>` | GET | doctor | view pre-visit summary |
| `/doctor/appointments/<id>/complete` | POST | doctor | submit notes → generates post-visit summary, schedules med reminders |
| `/doctor/settings` | GET/POST | doctor | specialization / hours / slot length |
| `/admin/` | GET | admin | hospital stats, department breakdown, doctor list |
| `/admin/doctors/new` | GET/POST | admin | create a doctor account + profile |
| `/admin/doctors/<id>/leave` | GET/POST | admin | mark leave day → cancels + notifies affected patients |
| `/admin/google/connect`, `/admin/google/callback` | GET | admin | OAuth 2.0 flow |

## 8. Project structure

```
happointment/
├── app.py                  # app factory, admin auto-seed, scheduler startup
├── config.py                # env-driven config
├── extensions.py             # db / login_manager singletons
├── models.py                 # SQLAlchemy models
├── routes/
│   ├── auth.py, patient.py, doctor.py, admin.py, utils.py
├── services/
│   ├── booking_service.py    # slot generation, double-booking guard, leave conflicts
│   ├── llm_service.py        # pre/post-visit summaries + fallback
│   ├── email_service.py      # SMTP + simulation + retry
│   ├── calendar_service.py   # Google Calendar OAuth + CRUD
│   └── scheduler.py          # APScheduler: reminders + email retries
├── templates/                # Jinja2, split by role
├── static/css/style.css
├── requirements.txt, Procfile, .env.example
└── DESIGN.md                 # system design write-up
```

See `DESIGN.md` for the reasoning behind double-booking prevention, leave
conflict handling, the slot-hold approach, and notification failure handling.
