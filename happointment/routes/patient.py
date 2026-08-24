import json
from datetime import datetime, date
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from extensions import db
from models import DoctorProfile, Appointment, User
from routes.utils import role_required
from services.booking_service import generate_available_slots, book_slot, SlotUnavailable
from services import llm_service, email_service, calendar_service

bp = Blueprint("patient", __name__, url_prefix="/patient")


@bp.route("/")
@login_required
@role_required("patient")
def dashboard():
    appointments = (
        Appointment.query.filter_by(patient_id=current_user.id)
        .order_by(Appointment.slot_start.desc())
        .all()
    )
    upcoming = [a for a in appointments if a.status == "booked"]
    completed = [a for a in appointments if a.status == "completed"]
    specializations = [
        d[0] for d in db.session.query(DoctorProfile.specialization).distinct().limit(6)
    ]
    return render_template(
        "patient/dashboard.html", appointments=appointments,
        upcoming_count=len(upcoming), completed_count=len(completed),
        specializations=specializations,
    )


@bp.route("/doctors")
@login_required
@role_required("patient")
def search_doctors():
    specialization = request.args.get("specialization", "").strip()
    query = DoctorProfile.query.join(User)
    if specialization:
        query = query.filter(DoctorProfile.specialization.ilike(f"%{specialization}%"))
    doctors = query.all()
    specializations = [d[0] for d in db.session.query(DoctorProfile.specialization).distinct()]
    return render_template(
        "patient/search_doctors.html", doctors=doctors, specializations=specializations,
        selected=specialization,
    )


@bp.route("/doctors/<int:doctor_id>/book", methods=["GET", "POST"])
@login_required
@role_required("patient")
def book(doctor_id):
    doctor = DoctorProfile.query.get_or_404(doctor_id)
    day_str = request.args.get("date") or date.today().isoformat()
    day = datetime.strptime(day_str, "%Y-%m-%d").date()
    slots = generate_available_slots(doctor, day)

    if request.method == "POST":
        slot_start = datetime.fromisoformat(request.form["slot_start"])
        symptoms = request.form["symptoms"].strip()

        try:
            appt = book_slot(current_user.id, doctor, slot_start, symptoms)
        except SlotUnavailable as e:
            flash(str(e), "error")
            return redirect(url_for("patient.book", doctor_id=doctor_id, date=day_str))

        # LLM pre-visit summary — never allowed to break the booking flow.
        summary, failed = llm_service.generate_pre_visit_summary(symptoms)
        appt.pre_visit_summary_json = json.dumps(summary)
        appt.pre_visit_urgency = summary.get("urgency", "Low")
        appt.llm_pre_visit_failed = failed
        db.session.commit()

        # Calendar event (single-calendar design — see calendar_service docstring)
        event_id = calendar_service.create_event(
            summary=f"Appointment: {current_user.name} with Dr. {doctor.user.name}",
            description=f"Specialization: {doctor.specialization}\nUrgency: {appt.pre_visit_urgency}",
            start_iso=appt.slot_start.isoformat(),
            end_iso=appt.slot_end.isoformat(),
            attendee_emails=[current_user.email, doctor.user.email],
        )
        appt.calendar_event_id_patient = event_id
        appt.calendar_event_id_doctor = event_id
        db.session.commit()

        email_service.send_email(
            current_user.email, "Appointment confirmed",
            f"Your appointment with Dr. {doctor.user.name} is confirmed for "
            f"{appt.slot_start.strftime('%Y-%m-%d %H:%M')}.",
            appointment_id=appt.id,
        )
        email_service.send_email(
            doctor.user.email, "New appointment booked",
            f"New appointment with {current_user.name} on "
            f"{appt.slot_start.strftime('%Y-%m-%d %H:%M')}. Urgency: {appt.pre_visit_urgency}.",
            appointment_id=appt.id,
        )

        flash("Appointment booked!", "success")
        return redirect(url_for("patient.dashboard"))

    return render_template("patient/book.html", doctor=doctor, slots=slots, day=day_str)


@bp.route("/appointments/<int:appt_id>")
@login_required
@role_required("patient")
def view_appointment(appt_id):
    appt = Appointment.query.filter_by(id=appt_id, patient_id=current_user.id).first_or_404()
    post_summary = json.loads(appt.post_visit_summary_json) if appt.post_visit_summary_json else None
    return render_template("patient/appointment_detail.html", appt=appt, post_summary=post_summary)


@bp.route("/appointments/<int:appt_id>/cancel", methods=["POST"])
@login_required
@role_required("patient")
def cancel(appt_id):
    appt = Appointment.query.filter_by(id=appt_id, patient_id=current_user.id).first_or_404()
    appt.status = "cancelled"
    appt.cancel_reason = "Cancelled by patient"
    db.session.commit()
    calendar_service.delete_event(appt.calendar_event_id_patient)
    email_service.send_email(
        appt.doctor.user.email, "Appointment cancelled",
        f"{current_user.name} cancelled their appointment on "
        f"{appt.slot_start.strftime('%Y-%m-%d %H:%M')}.",
        appointment_id=appt.id,
    )
    flash("Appointment cancelled.", "success")
    return redirect(url_for("patient.dashboard"))
