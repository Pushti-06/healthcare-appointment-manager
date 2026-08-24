"""
Background job: medication reminders + email retries.
Runs inside the same process via APScheduler (fine for a single free-tier
dyno/instance; documented in DESIGN.md as the scale limit — a real
multi-instance deploy would move this to a proper queue/worker like
Celery + Redis so jobs don't run once per instance).
"""
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from models import Appointment, MedicationReminder
from services import email_service
from extensions import db


def _send_appointment_reminders(app):
    now = datetime.utcnow()
    upcoming = Appointment.query.filter(
        Appointment.status == "booked", Appointment.slot_start > now
    ).all()
    for appt in upcoming:
        delta = appt.slot_start - now
        if timedelta(hours=23, minutes=30) <= delta <= timedelta(hours=24, minutes=30) and not appt.reminder_24h_sent:
            email_service.send_email(
                appt.patient.email,
                "Appointment reminder — tomorrow",
                f"Reminder: you have an appointment with Dr. {appt.doctor.user.name} "
                f"on {appt.slot_start.strftime('%Y-%m-%d %H:%M')}.",
                appointment_id=appt.id,
            )
            appt.reminder_24h_sent = True
            db.session.commit()
        elif timedelta(minutes=30) <= delta <= timedelta(hours=1, minutes=30) and not appt.reminder_1h_sent:
            email_service.send_email(
                appt.patient.email,
                "Appointment reminder — in about an hour",
                f"Reminder: your appointment with Dr. {appt.doctor.user.name} is coming up "
                f"at {appt.slot_start.strftime('%H:%M')} today.",
                appointment_id=appt.id,
            )
            appt.reminder_1h_sent = True
            db.session.commit()


def _send_medication_reminders(app):
    now = datetime.utcnow()
    due = MedicationReminder.query.filter(
        MedicationReminder.active.is_(True), MedicationReminder.next_due_at <= now
    ).all()
    for rem in due:
        appt = rem.appointment
        email_service.send_email(
            appt.patient.email,
            f"Medication reminder: {rem.medication_name}",
            f"It's time to take your medication: {rem.medication_name}.",
            appointment_id=appt.id,
        )
        rem.times_sent += 1
        rem.next_due_at = now + timedelta(hours=rem.frequency_hours)
        if rem.times_sent >= rem.max_sends:
            rem.active = False
        db.session.commit()


def _tick(app):
    with app.app_context():
        _send_appointment_reminders(app)
        _send_medication_reminders(app)
        email_service.retry_failed_emails()


def init_scheduler(app):
    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(
        func=lambda: _tick(app),
        trigger="interval",
        seconds=app.config["SCHEDULER_INTERVAL_SECONDS"],
        id="reminder_job",
        replace_existing=True,
    )
    scheduler.start()
    return scheduler
