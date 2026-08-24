import json
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from extensions import db
from models import Appointment, MedicationReminder
from routes.utils import role_required
from services import llm_service, email_service, calendar_service
from datetime import datetime, timedelta

bp = Blueprint("doctor", __name__, url_prefix="/doctor")


@bp.route("/")
@login_required
@role_required("doctor")
def dashboard():
    profile = current_user.doctor_profile
    appointments = (
        Appointment.query.filter_by(doctor_id=profile.id, status="booked")
        .order_by(Appointment.slot_start.asc())
        .all()
    )
    today = datetime.utcnow().date()
    today_count = sum(1 for a in appointments if a.slot_start.date() == today)
    completed_count = Appointment.query.filter_by(doctor_id=profile.id, status="completed").count()
    high_urgency_count = sum(1 for a in appointments if a.pre_visit_urgency == "High")
    return render_template(
        "doctor/dashboard.html", appointments=appointments, profile=profile,
        today_count=today_count, completed_count=completed_count,
        upcoming_count=len(appointments), high_urgency_count=high_urgency_count,
    )


@bp.route("/appointments/<int:appt_id>")
@login_required
@role_required("doctor")
def view_appointment(appt_id):
    appt = Appointment.query.filter_by(
        id=appt_id, doctor_id=current_user.doctor_profile.id
    ).first_or_404()
    pre_summary = json.loads(appt.pre_visit_summary_json) if appt.pre_visit_summary_json else None
    return render_template("doctor/appointment_detail.html", appt=appt, pre_summary=pre_summary)


@bp.route("/appointments/<int:appt_id>/complete", methods=["POST"])
@login_required
@role_required("doctor")
def complete_visit(appt_id):
    appt = Appointment.query.filter_by(
        id=appt_id, doctor_id=current_user.doctor_profile.id
    ).first_or_404()

    notes = request.form["notes"].strip()
    med_name = request.form.get("medication_name", "").strip()
    med_freq = request.form.get("medication_frequency_hours", "").strip()

    appt.post_visit_notes = notes
    summary, failed = llm_service.generate_post_visit_summary(notes)
    appt.post_visit_summary_json = json.dumps(summary)
    appt.llm_post_visit_failed = failed
    appt.status = "completed"
    db.session.commit()

    if med_name and med_freq:
        reminder = MedicationReminder(
            appointment_id=appt.id,
            medication_name=med_name,
            frequency_hours=int(med_freq),
            next_due_at=datetime.utcnow() + timedelta(hours=int(med_freq)),
        )
        db.session.add(reminder)
        db.session.commit()

    email_service.send_email(
        appt.patient.email, "Your visit summary",
        f"Summary from your visit with Dr. {current_user.name}:\n\n{summary.get('summary', '')}",
        appointment_id=appt.id,
    )
    flash("Visit marked complete and summary sent to patient.", "success")
    return redirect(url_for("doctor.dashboard"))


@bp.route("/settings", methods=["GET", "POST"])
@login_required
@role_required("doctor")
def settings():
    profile = current_user.doctor_profile
    if request.method == "POST":
        profile.specialization = request.form["specialization"]
        profile.working_hours_start = request.form["working_hours_start"]
        profile.working_hours_end = request.form["working_hours_end"]
        profile.slot_duration_minutes = int(request.form["slot_duration_minutes"])
        db.session.commit()
        flash("Settings updated.", "success")
        return redirect(url_for("doctor.settings"))
    return render_template("doctor/settings.html", profile=profile)
