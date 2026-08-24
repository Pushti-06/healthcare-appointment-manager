from datetime import datetime, timedelta
from collections import Counter
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app
from flask_login import login_required, current_user
from extensions import db
from models import User, DoctorProfile, Leave, Appointment
from routes.utils import role_required
from services.booking_service import apply_leave
from services import email_service, calendar_service

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.route("/")
@login_required
@role_required("admin")
def dashboard():
    doctors = DoctorProfile.query.join(User).order_by(DoctorProfile.specialization).all()
    patient_count = User.query.filter_by(role="patient").count()
    today = datetime.utcnow().date()
    tomorrow = today + timedelta(days=1)
    appts_today = Appointment.query.filter(
        Appointment.status == "booked",
        Appointment.slot_start >= today, Appointment.slot_start < tomorrow,
    ).count()
    upcoming_count = Appointment.query.filter(Appointment.status == "booked").count()
    completed_count = Appointment.query.filter(Appointment.status == "completed").count()

    dept_counts = Counter(d.specialization for d in doctors)
    departments = sorted(dept_counts.items(), key=lambda kv: (-kv[1], kv[0]))

    return render_template(
        "admin/dashboard.html", doctors=doctors,
        patient_count=patient_count, doctor_count=len(doctors),
        appts_today=appts_today, upcoming_count=upcoming_count,
        completed_count=completed_count, departments=departments,
        calendar_connected=calendar_service.is_connected(),
    )


@bp.route("/doctors/new", methods=["GET", "POST"])
@login_required
@role_required("admin")
def new_doctor():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        if User.query.filter_by(email=email).first():
            flash("A user with that email already exists.", "error")
            return redirect(url_for("admin.new_doctor"))

        user = User(role="doctor", name=request.form["name"].strip(), email=email)
        user.set_password(request.form["password"])
        db.session.add(user)
        db.session.flush()

        profile = DoctorProfile(
            user_id=user.id,
            specialization=request.form["specialization"].strip(),
            working_hours_start=request.form.get("working_hours_start", "09:00"),
            working_hours_end=request.form.get("working_hours_end", "17:00"),
            slot_duration_minutes=int(request.form.get("slot_duration_minutes", 30)),
        )
        db.session.add(profile)
        db.session.commit()
        flash("Doctor profile created.", "success")
        return redirect(url_for("admin.dashboard"))

    return render_template("admin/new_doctor.html")


@bp.route("/doctors/<int:doctor_id>/leave", methods=["GET", "POST"])
@login_required
@role_required("admin")
def manage_leave(doctor_id):
    doctor = DoctorProfile.query.get_or_404(doctor_id)

    if request.method == "POST":
        leave_date = datetime.strptime(request.form["date"], "%Y-%m-%d").date()
        reason = request.form.get("reason", "").strip()

        # This does the actual conflict handling: cancels affected bookings
        # and returns them so we can notify + clean up calendar events.
        affected = apply_leave(doctor, leave_date, reason)

        for appt in affected:
            calendar_service.delete_event(appt.calendar_event_id_patient)
            email_service.send_email(
                appt.patient.email,
                "Your appointment has been cancelled",
                f"Unfortunately Dr. {doctor.user.name} is on leave on "
                f"{leave_date.strftime('%Y-%m-%d')} and your appointment "
                f"({appt.slot_start.strftime('%Y-%m-%d %H:%M')}) has been cancelled. "
                f"Please rebook for another day. We're sorry for the inconvenience.",
                appointment_id=appt.id,
            )

        if affected:
            flash(f"Leave recorded. {len(affected)} appointment(s) cancelled and patients notified.", "success")
        else:
            flash("Leave recorded. No existing appointments were affected.", "success")
        return redirect(url_for("admin.manage_leave", doctor_id=doctor_id))

    leaves = Leave.query.filter_by(doctor_id=doctor.id).order_by(Leave.date.desc()).all()
    return render_template("admin/manage_leave.html", doctor=doctor, leaves=leaves)


@bp.route("/google/connect")
@login_required
@role_required("admin")
def google_connect():
    """Kicks off the Google Calendar OAuth flow. Only does something once
    client_secret.json is in place — see README "Google Calendar setup"."""
    import os
    if not os.path.exists(current_app.config["GOOGLE_CLIENT_SECRETS_FILE"]):
        flash(
            "Google Calendar isn't set up yet — add client_secret.json first "
            "(see README, 'Google Calendar setup').", "error"
        )
        return redirect(url_for("admin.dashboard"))

    # Google's OAuth library refuses http:// redirect URIs by default (only
    # allows https://). That's correct for production, but blocks local
    # testing at http://localhost — allow it only when the configured
    # redirect really is localhost/http, never in a real deployment.
    redirect_uri = current_app.config["GOOGLE_REDIRECT_URI"]
    if redirect_uri.startswith("http://"):
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

    try:
        flow = calendar_service.get_flow()
        auth_url, state = flow.authorization_url(access_type="offline", prompt="consent")
    except Exception as exc:
        current_app.logger.warning(f"Google OAuth flow setup failed: {exc}")
        flash(f"Couldn't start Google Calendar connection: {exc}", "error")
        return redirect(url_for("admin.dashboard"))

    session["google_oauth_state"] = state
    return redirect(auth_url)


@bp.route("/google/callback")
@login_required
@role_required("admin")
def google_callback():
    import os
    redirect_uri = current_app.config["GOOGLE_REDIRECT_URI"]
    if redirect_uri.startswith("http://"):
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

    state = session.get("google_oauth_state")
    try:
        flow = calendar_service.get_flow(state=state)
        flow.fetch_token(authorization_response=request.url)
        calendar_service.save_credentials(flow.credentials)
    except Exception as exc:
        current_app.logger.warning(f"Google OAuth callback failed: {exc}")
        flash(
            f"Google Calendar connection failed: {exc}. Common causes: the "
            f"redirect URI in Google Cloud Console doesn't exactly match "
            f"{redirect_uri}, or your Google account isn't added as a test "
            f"user on the OAuth consent screen.", "error"
        )
        return redirect(url_for("admin.dashboard"))

    flash("Google Calendar connected for the clinic.", "success")
    return redirect(url_for("admin.dashboard"))
