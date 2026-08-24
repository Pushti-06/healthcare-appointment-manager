# System Design Write-up

## Double-booking prevention

Booking uses two layers, and only one of them is actually load-bearing.

**Layer 1 (UX, not safety):** before inserting, `book_slot()` checks that the
doctor isn't on leave that day and that no `booked` appointment already
exists at that `slot_start`. This gives instant, friendly feedback in the
common case but is *not* safe under concurrency — two requests can both pass
this check in the gap before either commits.

**Layer 2 (the actual guarantee):** `appointments` has a database-level
`UNIQUE(doctor_id, slot_start)` constraint. When two patients race for the
same slot, both application checks may pass, but only one `INSERT` can
succeed — the second raises `IntegrityError`, which is caught and turned
into a clean "that slot was just taken" response, and the transaction is
rolled back so no partial state (LLM summary, email, calendar event) is
created for the losing request. This is verified in testing: a same-slot
double-booking attempt is rejected even when both requests reach the
booking function back-to-back with no delay between them.

This approach was chosen over an in-memory lock (e.g. a Python `threading.Lock`
or a dict of "currently booking" slots) because in-memory locks only work
within a single process. The moment the app scales to multiple worker
processes or instances (which any real deployment would), an in-memory lock
stops being a source of truth. A DB constraint is authoritative regardless of
how many app instances are running, at the cost of nothing more than
catching one extra exception type.

## Slot hold mechanism

The booking flow here is single-step: the patient picks a slot and submits
symptoms in the same form POST, so there's no multi-minute "reserved while
you fill out a form" window that needs an explicit TTL-based hold — the
unique constraint above effectively acts as an instant hold at commit time.

If the flow were extended to a multi-step checkout (e.g. "hold this slot for
5 minutes while you fill in symptoms, insurance details, etc."), the right
mechanism would be a short-lived `held_by`/`held_until` pair on the slot (or
a Redis key with a TTL, e.g. `hold:doctor_id:slot_start` expiring in 300s).
The confirm step would then re-check the hold belongs to the current session
before the same unique-constraint-backed insert runs — the hold prevents
*other users* from seeing the slot as available in the UI, but the DB
constraint remains the actual correctness guarantee, since holds can expire,
be lost, or be bypassed by a direct API call.

## Doctor leave conflict handling

When an admin marks a doctor on leave (`apply_leave()` in
`booking_service.py`), the operation is transactional and does three things
in one place: (1) upserts the `Leave` row for that doctor/date, (2) queries
every `booked` appointment for that doctor on that date, and (3) marks each
one `cancelled` with a reason before committing. The function returns the
list of affected appointments so the route layer can act on side effects
*after* the DB state is safely committed: emailing each affected patient
("Dr. X is on leave on this date, please rebook") and deleting the
corresponding Google Calendar event. Splitting it this way — commit the
state change first, then fan out notifications — means a slow or failing
email/calendar call can never leave the leave-day or the appointment status
inconsistent; worst case, a notification retries later while the booking
record is already correctly cancelled.

Leave is also checked going forward: `generate_available_slots()` returns an
empty list for any day with a `Leave` row for that doctor, so new bookings
can't be made against a day the doctor has already blocked out.

## Notification failure handling

Every email attempt (booking confirmation, reminders, cancellation, leave
notice, visit summary) is logged as an `EmailLog` row with a `status`
(`sent`, `failed`, or `simulated` when no SMTP is configured) and an
`attempts` counter, *before* the send is attempted — so even a crash mid-send
leaves an auditable record rather than a silent gap. If sending raises, the
row is marked `failed` with the error text, and the booking/leave/completion
flow itself is never rolled back or blocked on it — a bounced or slow email
provider cannot break a medical appointment being recorded. A background
APScheduler job (`retry_failed_emails`, run every `SCHEDULER_INTERVAL_SECONDS`)
periodically re-attempts any `failed` row under `EMAIL_MAX_RETRIES`, so a
transient SMTP outage self-heals without user intervention. The same
scheduler tick also handles medication reminders and appointment reminders,
each idempotently guarded by a boolean flag (`reminder_24h_sent`,
`reminder_1h_sent`) or a `next_due_at` timestamp so a job that runs slightly
late or is retried never double-sends.

LLM calls follow the identical philosophy: a failure is caught, logged on
the appointment (`llm_pre_visit_failed` / `llm_post_visit_failed`), and
replaced with a deterministic fallback rather than surfaced to the user or
allowed to block the booking/completion flow — see `services/llm_service.py`.
