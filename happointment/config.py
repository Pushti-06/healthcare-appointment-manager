import os
from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, ".env"))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{os.path.join(basedir, 'instance', 'app.db')}"
    )
    # Render/Heroku give postgres:// — SQLAlchemy 1.4+/2.x wants postgresql://
    if SQLALCHEMY_DATABASE_URI.startswith("postgres://"):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace(
            "postgres://", "postgresql://", 1
        )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # --- LLM ---
    # Any OpenAI-compatible endpoint works: OpenAI, Groq (free tier), Together, etc.
    LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
    LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1")
    LLM_MODEL = os.environ.get("LLM_MODEL", "llama-3.1-8b-instant")
    LLM_TIMEOUT_SECONDS = float(os.environ.get("LLM_TIMEOUT_SECONDS", "8"))

    # --- Email ---
    SMTP_HOST = os.environ.get("SMTP_HOST", "")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
    SMTP_USER = os.environ.get("SMTP_USER", "")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
    SMTP_FROM = os.environ.get("SMTP_FROM", "no-reply@clinic.local")
    EMAIL_MAX_RETRIES = int(os.environ.get("EMAIL_MAX_RETRIES", "3"))

    # --- Google Calendar ---
    GOOGLE_CLIENT_SECRETS_FILE = os.environ.get(
        "GOOGLE_CLIENT_SECRETS_FILE", os.path.join(basedir, "client_secret.json")
    )
    GOOGLE_TOKEN_FILE = os.environ.get(
        "GOOGLE_TOKEN_FILE", os.path.join(basedir, "instance", "google_token.json")
    )
    GOOGLE_REDIRECT_URI = os.environ.get(
        "GOOGLE_REDIRECT_URI", "http://localhost:5000/admin/google/callback"
    )

    # --- Scheduler ---
    SCHEDULER_INTERVAL_SECONDS = int(os.environ.get("SCHEDULER_INTERVAL_SECONDS", "60"))

    # --- Timezone ---
    # Appointment slot times are stored as naive local clinic time (no
    # conversion happens anywhere in the app). This tells Google Calendar
    # which zone that naive time is actually in, since its API requires
    # one. Change to your clinic's zone if not India.
    CLINIC_TIMEZONE = os.environ.get("CLINIC_TIMEZONE", "Asia/Kolkata")
