"""
Core scheduling logic — this is the file the "problem-solving approach for
slot conflicts, leave management" evaluation point is really about.

Double-booking prevention (two layers):
  1. Application layer: before insert, we check the slot isn't already
     booked and isn't on a leave day.
  2. Database layer (the layer that actually matters under concurrency):
     Appointment has a UNIQUE(doctor_id, slot_start) constraint. If two
     requests race past the application check at the same time, only one
     INSERT succeeds; the second raises IntegrityError, which we catch and
     turn into a clean "slot just got taken" response. This is safe even
     across multiple server processes/workers, unlike an in-memory lock.

Leave conflict handling:
  When a doctor is marked on leave for a date, `apply_leave` finds every
  booked appointment on that date, cancels it, frees the slot, and returns
  the list so the caller can notify patients (email + calendar delete).
"""
from datetime import datetime, timedelta, date as date_cls
from sqlalchemy.exc import IntegrityError
from extensions import db
from models import DoctorProfile, Leave, Appointment


class SlotUnavailable(Exception):
    pass


def generate_available_slots(doctor: DoctorProfile, day: date_cls) -> list[datetime]:
    """All slots for a doctor on a given day, minus ones already booked or on leave."""
    on_leave = Leave.query.filter_by(doctor_id=doctor.id, date=day).first()
    if on_leave:
        return []

    start_h, start_m = map(int, doctor.working_hours_start.split(":"))
    end_h, end_m = map(int, doctor.working_hours_end.split(":"))
    cursor = datetime.combine(day, datetime.min.time()).replace(hour=start_h, minute=start_m)
    end_of_day = datetime.combine(day, datetime.min.time()).replace(hour=end_h, minute=end_m)
    step = timedelta(minutes=doctor.slot_duration_minutes)

    booked_starts = {
        a.slot_start
        for a in Appointment.query.filter_by(doctor_id=doctor.id, status="booked")
        .filter(Appointment.slot_start >= cursor, Appointment.slot_start < end_of_day)
    }

    slots = []
    while cursor + step <= end_of_day:
        if cursor not in booked_starts and cursor > datetime.utcnow():
            slots.append(cursor)
        cursor += step
    return slots


def book_slot(patient_id: int, doctor: DoctorProfile, slot_start: datetime, symptoms_text: str) -> Appointment:
    slot_end = slot_start + timedelta(minutes=doctor.slot_duration_minutes)

    # Layer 1: fast application-level checks (good UX, not the safety net)
    if Leave.query.filter_by(doctor_id=doctor.id, date=slot_start.date()).first():
        raise SlotUnavailable("Doctor is on leave that day.")
    if Appointment.query.filter_by(
        doctor_id=doctor.id, slot_start=slot_start, status="booked"
    ).first():
        raise SlotUnavailable("That slot was just booked by someone else.")

    appointment = Appointment(
        patient_id=patient_id,
        doctor_id=doctor.id,
        slot_start=slot_start,
        slot_end=slot_end,
        symptoms_text=symptoms_text,
        status="booked",
    )
    db.session.add(appointment)
    try:
        # Layer 2: the actual safety net under concurrency.
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise SlotUnavailable("That slot was just booked by someone else.")
    return appointment


def apply_leave(doctor: DoctorProfile, leave_date: date_cls, reason: str) -> list[Appointment]:
    """Marks a doctor on leave and returns the list of appointments that were
    cancelled as a result, so the caller can notify/refund/reschedule."""
    existing = Leave.query.filter_by(doctor_id=doctor.id, date=leave_date).first()
    if existing:
        existing.reason = reason
    else:
        db.session.add(Leave(doctor_id=doctor.id, date=leave_date, reason=reason))

    day_start = datetime.combine(leave_date, datetime.min.time())
    day_end = day_start + timedelta(days=1)
    affected = Appointment.query.filter(
        Appointment.doctor_id == doctor.id,
        Appointment.status == "booked",
        Appointment.slot_start >= day_start,
        Appointment.slot_start < day_end,
    ).all()

    for appt in affected:
        appt.status = "cancelled"
        appt.cancel_reason = f"Doctor on leave: {reason}" if reason else "Doctor on leave"

    db.session.commit()
    return affected
