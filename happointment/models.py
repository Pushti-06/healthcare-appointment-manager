from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from extensions import db


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    role = db.Column(db.String(10), nullable=False)  # patient / doctor / admin
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    doctor_profile = db.relationship(
        "DoctorProfile", backref="user", uselist=False, cascade="all, delete-orphan"
    )

    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        return check_password_hash(self.password_hash, raw)


class DoctorProfile(db.Model):
    __tablename__ = "doctor_profiles"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, unique=True)
    specialization = db.Column(db.String(120), nullable=False)
    working_hours_start = db.Column(db.String(5), default="09:00")  # "HH:MM"
    working_hours_end = db.Column(db.String(5), default="17:00")
    slot_duration_minutes = db.Column(db.Integer, default=30)

    leaves = db.relationship("Leave", backref="doctor", cascade="all, delete-orphan")
    appointments = db.relationship("Appointment", backref="doctor", cascade="all, delete-orphan")


class Leave(db.Model):
    __tablename__ = "leaves"
    id = db.Column(db.Integer, primary_key=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("doctor_profiles.id"), nullable=False)
    date = db.Column(db.Date, nullable=False)  # whole day off
    reason = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint("doctor_id", "date", name="uq_doctor_leave_date"),)


class Appointment(db.Model):
    __tablename__ = "appointments"
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    doctor_id = db.Column(db.Integer, db.ForeignKey("doctor_profiles.id"), nullable=False)

    slot_start = db.Column(db.DateTime, nullable=False)
    slot_end = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), default="booked")  # booked/cancelled/completed

    symptoms_text = db.Column(db.Text)
    pre_visit_urgency = db.Column(db.String(10))       # Low/Medium/High
    pre_visit_summary_json = db.Column(db.Text)         # raw JSON from LLM (or mock)
    llm_pre_visit_failed = db.Column(db.Boolean, default=False)

    post_visit_notes = db.Column(db.Text)
    post_visit_summary_json = db.Column(db.Text)
    llm_post_visit_failed = db.Column(db.Boolean, default=False)

    calendar_event_id_patient = db.Column(db.String(255))
    calendar_event_id_doctor = db.Column(db.String(255))

    cancel_reason = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    reminder_24h_sent = db.Column(db.Boolean, default=False)
    reminder_1h_sent = db.Column(db.Boolean, default=False)

    patient = db.relationship("User", foreign_keys=[patient_id])
    medication_reminders = db.relationship(
        "MedicationReminder", backref="appointment", cascade="all, delete-orphan"
    )

    # THE core double-booking guard: a doctor can only have ONE row per exact
    # slot_start. This is enforced at the database level so it holds even
    # under concurrent requests (see DESIGN.md, "Double-booking prevention").
    __table_args__ = (
        db.UniqueConstraint("doctor_id", "slot_start", name="uq_doctor_slot"),
    )


class MedicationReminder(db.Model):
    __tablename__ = "medication_reminders"
    id = db.Column(db.Integer, primary_key=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey("appointments.id"), nullable=False)
    medication_name = db.Column(db.String(120), nullable=False)
    frequency_hours = db.Column(db.Integer, nullable=False)  # e.g. every 8 hours
    next_due_at = db.Column(db.DateTime, nullable=False)
    times_sent = db.Column(db.Integer, default=0)
    max_sends = db.Column(db.Integer, default=10)
    active = db.Column(db.Boolean, default=True)


class EmailLog(db.Model):
    __tablename__ = "email_logs"
    id = db.Column(db.Integer, primary_key=True)
    to_email = db.Column(db.String(120), nullable=False)
    subject = db.Column(db.String(255), nullable=False)
    body = db.Column(db.Text)
    status = db.Column(db.String(20), default="pending")  # pending/sent/failed/simulated
    attempts = db.Column(db.Integer, default=0)
    last_error = db.Column(db.Text)
    appointment_id = db.Column(db.Integer, db.ForeignKey("appointments.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
