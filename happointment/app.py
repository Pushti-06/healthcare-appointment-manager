import os
from flask import Flask, redirect, url_for
from flask_login import current_user
from config import Config
from extensions import db, login_manager


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    os.makedirs(os.path.join(os.path.dirname(__file__), "instance"), exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)

    from models import User

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    from routes.auth import bp as auth_bp
    from routes.patient import bp as patient_bp
    from routes.doctor import bp as doctor_bp
    from routes.admin import bp as admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(patient_bp)
    app.register_blueprint(doctor_bp)
    app.register_blueprint(admin_bp)

    @app.route("/")
    def index():
        if current_user.is_authenticated:
            return redirect(url_for(f"{current_user.role}.dashboard"))
        return redirect(url_for("auth.login"))

    @app.context_processor
    def inject_hospital_stats():
        from models import User, DoctorProfile
        try:
            return {
                "hospital_doctor_count": DoctorProfile.query.count(),
                "hospital_patient_count": User.query.filter_by(role="patient").count(),
                "hospital_department_count": db.session.query(DoctorProfile.specialization)
                    .distinct().count(),
            }
        except Exception:
            return {"hospital_doctor_count": 0, "hospital_patient_count": 0, "hospital_department_count": 0}

    with app.app_context():
        db.create_all()
        _seed_admin(app)
        _maybe_auto_seed(app)

    if os.environ.get("ENABLE_SCHEDULER", "1") == "1":
        from services.scheduler import init_scheduler
        init_scheduler(app)

    return app


def _seed_admin(app):
    """Creates a default admin account on first run if none exists, from
    ADMIN_EMAIL/ADMIN_PASSWORD in .env (or sensible dev defaults)."""
    from models import User

    if User.query.filter_by(role="admin").first():
        return
    email = os.environ.get("ADMIN_EMAIL", "admin@clinic.local")
    password = os.environ.get("ADMIN_PASSWORD", "admin123")
    admin = User(role="admin", name="Clinic Admin", email=email)
    admin.set_password(password)
    db.session.add(admin)
    db.session.commit()
    app.logger.info(f"Seeded default admin: {email} / (see ADMIN_PASSWORD in .env)")


def _maybe_auto_seed(app):
    """Auto-populates hospital-scale demo data on startup when AUTO_SEED=1
    and the database is currently empty of doctors.

    This exists for hosts like Render's free tier that have no persistent
    disk and no shell access: the SQLite file resets to empty on every
    cold start after the service spins down from inactivity. Rather than
    requiring manual `python seed_data.py` access that free tiers don't
    allow, this reseeds automatically and idempotently every time the app
    boots into an empty database — so a demo/hosted URL never shows up
    blank. Safe to leave off (default) for a normal deployment with a
    real persistent database, where you'd seed once yourself and don't
    want it silently re-running on every restart.
    """
    if os.environ.get("AUTO_SEED", "0") != "1":
        return
    from models import DoctorProfile
    if DoctorProfile.query.count() > 0:
        return
    try:
        from seed_data import run_seed
        run_seed()
        app.logger.info("AUTO_SEED=1: database was empty, seeded demo data.")
    except Exception as exc:
        app.logger.warning(f"Auto-seed failed (app still starts fine): {exc}")


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=int(os.environ.get("PORT", 5000)))