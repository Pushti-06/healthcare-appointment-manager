"""
Seed script — populates the app with a realistic, hospital-scale set of
synthetic demo data: ~35 doctors across 14 departments, ~70 patients, and
a few hundred appointments spread across the past two months and the
next two weeks (booked / completed / cancelled), so every dashboard
looks like it belongs to a running clinic rather than a fresh install.

None of this is real people's data — names are generated from common
Indian first/last name pools for demo purposes only, and emails are
synthetic (@clinic.local / @example.com). Safe to run against a fresh
DB; safe to re-run (skips anything already created by email).

Usage:
    python seed_data.py
"""
import json
import random
from datetime import datetime, timedelta

from app import create_app
from extensions import db
from models import User, DoctorProfile, Appointment, Leave, MedicationReminder
from services import llm_service

random.seed(42)

DEPARTMENTS = [
    "Cardiology", "General Physician", "Pediatrics", "Dermatology",
    "Orthopedics", "ENT", "Gynecology", "Psychiatry", "Neurology",
    "Ophthalmology", "Urology", "Endocrinology", "Pulmonology", "Oncology",
]

DOCTOR_FIRST = [
    "Ananya", "Rohit", "Kavita", "Sameer", "Priya", "Arjun", "Divya",
    "Vikram", "Neha", "Rajesh", "Pooja", "Manish", "Shreya", "Amitabh",
    "Ritu", "Suresh", "Nandini", "Karthik", "Deepa", "Vivek", "Anjali",
    "Gaurav", "Swati", "Nikhil", "Meenal", "Harish", "Tanvi", "Ashok",
    "Lakshmi", "Rajeev", "Sonal", "Prakash", "Radhika", "Naveen", "Aarti",
]
DOCTOR_LAST = [
    "Sharma", "Verma", "Nair", "Khan", "Iyer", "Mehta", "Reddy", "Singh",
    "Gupta", "Kumar", "Joshi", "Rao", "Chatterjee", "Bose", "Pillai",
    "Malhotra", "Kapoor", "Desai", "Agarwal", "Menon", "Chauhan", "Nayar",
]

PATIENT_FIRST = [
    "Isha", "Rahul", "Meera", "Aditya", "Sneha", "Karan", "Riya", "Aman",
    "Pallavi", "Yash", "Simran", "Rohan", "Tanya", "Varun", "Ishita",
    "Siddharth", "Anushka", "Dev", "Nisha", "Akash", "Kritika", "Sahil",
    "Bhavna", "Manoj", "Ritika", "Sanjay", "Payal", "Abhishek", "Juhi",
    "Tarun", "Komal", "Vishal", "Shalini", "Rakesh", "Preeti", "Ajay",
]
PATIENT_LAST = [
    "Kapoor", "Gupta", "Joshi", "Rao", "Pillai", "Malhotra", "Bhatt",
    "Chopra", "Saxena", "Bansal", "Trivedi", "Mishra", "Pandey", "Dubey",
    "Sinha", "Chandra", "Bakshi", "Kohli", "Anand", "Rawat",
]

SYMPTOM_SAMPLES = [
    "Fever for 2 days, mild headache, no other symptoms.",
    "Persistent dry cough for a week, occasional chest tightness.",
    "Lower back pain after lifting something heavy, worse when bending.",
    "Skin rash on both arms, itchy, started 3 days ago.",
    "Sore throat and mild fever, difficulty swallowing.",
    "Recurring migraines, worse with bright light, 3-4 times this month.",
    "Stomach pain after meals, mild nausea, no vomiting.",
    "Joint pain in knees, especially in the morning.",
    "Anxiety and trouble sleeping for the past two weeks.",
    "Ear pain and slight hearing loss on the right side.",
    "Shortness of breath on mild exertion, started a few days ago.",
    "Blurred vision in one eye, occasional double vision.",
    "Irregular periods, cramping, past two cycles.",
    "Frequent urination and increased thirst over the last month.",
    "Chest discomfort during exercise, resolves with rest.",
    "Persistent acne breakout, tried over-the-counter creams with no relief.",
    "Swelling in ankles by evening, mild fatigue.",
    "Numbness in fingertips of left hand, intermittent.",
]

CLINICAL_NOTES_SAMPLES = [
    "Diagnosed with mild viral fever. Prescribed Paracetamol 500mg every "
    "8 hours for 3 days. Advised rest and fluids. Follow up if fever persists.",
    "Mild seasonal allergy suspected. Prescribed Cetirizine 10mg once daily "
    "for 5 days. Avoid dust exposure. Review in a week if symptoms continue.",
    "Muscular strain, no fracture. Advised rest, hot compress, and "
    "Ibuprofen 400mg twice daily for 3 days if pain persists.",
    "Mild eczema flare-up. Prescribed hydrocortisone cream, apply twice "
    "daily for 7 days. Avoid harsh soaps.",
    "Routine checkup, vitals normal. Advised continuing current lifestyle, "
    "review in 6 months.",
    "Mild anemia on review of symptoms. Prescribed iron supplement 1 tablet "
    "daily for 30 days with vitamin C. Recheck levels in 6 weeks.",
    "Tension headache likely due to screen time and stress. Advised "
    "breaks every hour, hydration, and Paracetamol 500mg as needed.",
]

STATUS_WEIGHTS_PAST = [("completed", 0.82), ("cancelled", 0.18)]
STATUS_WEIGHTS_FUTURE = [("booked", 0.9), ("cancelled", 0.1)]


def weighted_status(weights):
    r = random.random()
    cum = 0
    for status, w in weights:
        cum += w
        if r <= cum:
            return status
    return weights[-1][0]


def unique_names(first_pool, last_pool, count):
    seen = set()
    names = []
    while len(names) < count:
        name = f"{random.choice(first_pool)} {random.choice(last_pool)}"
        if name not in seen:
            seen.add(name)
            names.append(name)
    return names


def seed():
    app = create_app()
    with app.app_context():
        doctor_names = unique_names(DOCTOR_FIRST, DOCTOR_LAST, 35)
        patient_names = unique_names(PATIENT_FIRST, PATIENT_LAST, 70)

        # --- Doctors, ~2-3 per department ---
        created_doctors = 0
        doctor_profiles = []
        for i, name in enumerate(doctor_names):
            dept = DEPARTMENTS[i % len(DEPARTMENTS)]
            email = f"{name.lower().replace(' ', '.')}@clinic.local"
            user = User.query.filter_by(email=email).first()
            if not user:
                user = User(role="doctor", name=name, email=email)
                user.set_password("doctor123")
                db.session.add(user)
                db.session.flush()
                start_hour = random.choice([8, 9, 10])
                end_hour = start_hour + random.choice([6, 7, 8])
                profile = DoctorProfile(
                    user_id=user.id, specialization=dept,
                    working_hours_start=f"{start_hour:02d}:00",
                    working_hours_end=f"{min(end_hour, 20):02d}:00",
                    slot_duration_minutes=random.choice([15, 20, 30]),
                )
                db.session.add(profile)
                db.session.flush()
                created_doctors += 1
            else:
                profile = user.doctor_profile
            doctor_profiles.append(profile)
        db.session.commit()

        # --- Patients ---
        created_patients = 0
        patient_users = []
        for name in patient_names:
            email = f"{name.lower().replace(' ', '.')}@example.com"
            user = User.query.filter_by(email=email).first()
            if not user:
                user = User(role="patient", name=name, email=email)
                user.set_password("patient123")
                db.session.add(user)
                db.session.flush()
                created_patients += 1
            patient_users.append(user)
        db.session.commit()

        # --- A few doctors have an upcoming leave day, with bookings left on
        # it on purpose so the leave-conflict flow is demoable live. We
        # deliberately DON'T create the Leave row yet — bookings need the
        # day to look free first; the leave itself is applied after.
        leave_doctors = random.sample(doctor_profiles, 3)
        leave_plan = {}
        for ld in leave_doctors:
            leave_date = (datetime.utcnow() + timedelta(days=random.randint(4, 9))).date()
            leave_plan[ld.id] = leave_date

        # --- Appointments: past two months + next two weeks ---
        now = datetime.utcnow()
        created_appts = 0
        used_slots = set()

        def make_appointment(patient, doctor, day_offset, status_pool):
            slot_day = (now + timedelta(days=day_offset)).date()
            hour = random.randint(9, 17)
            slot_start = datetime.combine(slot_day, datetime.min.time()).replace(hour=hour)
            key = (doctor.id, slot_start)
            if key in used_slots:
                return None
            used_slots.add(key)

            symptoms = random.choice(SYMPTOM_SAMPLES)
            status = weighted_status(status_pool)
            appt = Appointment(
                patient_id=patient.id, doctor_id=doctor.id,
                slot_start=slot_start,
                slot_end=slot_start + timedelta(minutes=doctor.slot_duration_minutes),
                symptoms_text=symptoms,
                status="cancelled" if status == "cancelled" else (
                    "completed" if day_offset < 0 else "booked"
                ),
            )
            if status == "cancelled":
                appt.cancel_reason = random.choice(
                    ["Cancelled by patient", "Rescheduled", "Doctor on leave"]
                )
                db.session.add(appt)
                return appt

            pre_summary, pre_failed = llm_service.generate_pre_visit_summary(symptoms)
            appt.pre_visit_urgency = pre_summary.get("urgency", "Low")
            appt.pre_visit_summary_json = json.dumps(pre_summary)
            appt.llm_pre_visit_failed = pre_failed

            if day_offset < 0:  # past -> completed, has post-visit summary too
                notes = random.choice(CLINICAL_NOTES_SAMPLES)
                post_summary, post_failed = llm_service.generate_post_visit_summary(notes)
                appt.post_visit_notes = notes
                appt.post_visit_summary_json = json.dumps(post_summary)
                appt.llm_post_visit_failed = post_failed

            db.session.add(appt)
            db.session.flush()

            if day_offset < 0 and random.random() < 0.4:
                db.session.add(MedicationReminder(
                    appointment_id=appt.id,
                    medication_name=random.choice(["Paracetamol 500mg", "Cetirizine 10mg", "Ibuprofen 400mg"]),
                    frequency_hours=random.choice([8, 12, 24]),
                    next_due_at=now + timedelta(hours=8),
                    active=False, times_sent=random.randint(1, 4),
                ))
            return appt

        # Past appointments: spread over the last 60 days
        for _ in range(220):
            patient = random.choice(patient_users)
            doctor = random.choice(doctor_profiles)
            day_offset = -random.randint(1, 60)
            if make_appointment(patient, doctor, day_offset, STATUS_WEIGHTS_PAST):
                created_appts += 1

        # Upcoming appointments: next 14 days
        for _ in range(60):
            patient = random.choice(patient_users)
            doctor = random.choice(doctor_profiles)
            day_offset = random.randint(1, 14)
            if make_appointment(patient, doctor, day_offset, STATUS_WEIGHTS_FUTURE):
                created_appts += 1

        # Guarantee 2 real bookings land on each planned leave day, so the
        # leave-conflict-cancellation flow has something to demonstrate.
        for doctor_id, leave_date in leave_plan.items():
            doctor = next(d for d in doctor_profiles if d.id == doctor_id)
            day_offset = (leave_date - now.date()).days
            for hour in (10, 14):
                slot_start = datetime.combine(leave_date, datetime.min.time()).replace(hour=hour)
                if (doctor.id, slot_start) in used_slots:
                    continue
                used_slots.add((doctor.id, slot_start))
                patient = random.choice(patient_users)
                symptoms = random.choice(SYMPTOM_SAMPLES)
                pre_summary, pre_failed = llm_service.generate_pre_visit_summary(symptoms)
                appt = Appointment(
                    patient_id=patient.id, doctor_id=doctor.id,
                    slot_start=slot_start,
                    slot_end=slot_start + timedelta(minutes=doctor.slot_duration_minutes),
                    symptoms_text=symptoms,
                    pre_visit_urgency=pre_summary.get("urgency", "Low"),
                    pre_visit_summary_json=json.dumps(pre_summary),
                    llm_pre_visit_failed=pre_failed,
                    status="booked",
                )
                db.session.add(appt)
                created_appts += 1
        db.session.commit()

        # Now apply the leave rows themselves (bookings above are already
        # in place, exactly the "existing bookings when leave is marked"
        # scenario the admin can walk through).
        for doctor_id, leave_date in leave_plan.items():
            if not Leave.query.filter_by(doctor_id=doctor_id, date=leave_date).first():
                db.session.add(Leave(doctor_id=doctor_id, date=leave_date, reason=random.choice(
                    ["Conference", "Personal leave", "Training workshop"]
                )))
        db.session.commit()

        leave_summary = [
            (next(d for d in doctor_profiles if d.id == did).user.name, ld)
            for did, ld in leave_plan.items()
        ]
        print(f"Departments: {len(DEPARTMENTS)}")
        print(f"Doctors created: {created_doctors} (total {len(doctor_profiles)})")
        print(f"Patients created: {created_patients} (total {len(patient_users)})")
        print(f"Appointments created: {created_appts}")
        print("Doctors with an upcoming leave day (2 bookings on it, ready to demo the cancel flow):")
        for name, ld in leave_summary:
            print(f"  - Dr. {name} on {ld}")
        print("\nAll seeded accounts use password: doctor123 (doctors) / patient123 (patients)")
        print("Admin login is whatever you set as ADMIN_EMAIL/ADMIN_PASSWORD in .env.")


if __name__ == "__main__":
    seed()
