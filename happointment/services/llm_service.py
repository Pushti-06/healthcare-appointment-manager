"""
LLM integration for pre-visit and post-visit summaries.

Design choice (see DESIGN.md): the service talks to any OpenAI-compatible
chat completions endpoint (OpenAI, Groq's free tier, Together, etc.) via
LLM_BASE_URL / LLM_API_KEY / LLM_MODEL in .env. If no key is configured,
or the call fails/times out, it falls back to a deterministic rule-based
summarizer so a demo/grading run never breaks and never blocks on a paid key.
Every failure is logged on the Appointment row (llm_*_failed) rather than
raised, per the "LLM failures must be handled gracefully" requirement.
"""
import json
import re
import requests
from flask import current_app

PRE_VISIT_PROMPT = (
    "Analyse these symptoms and return: urgency level (Low / Medium / High), "
    "chief complaint, and three suggested questions for the doctor. "
    "Symptoms: {symptoms}\n\n"
    "Respond ONLY as JSON with keys: urgency, chief_complaint, questions (list of 3 strings)."
)

POST_VISIT_PROMPT = (
    "Convert these clinical notes into a patient-friendly summary with medication "
    "schedule and follow-up steps: {notes}\n\n"
    "Respond ONLY as JSON with keys: summary, medication_schedule (list of "
    "{{name, frequency_hours, instructions}}), follow_up (list of strings)."
)

URGENT_KEYWORDS = ["chest pain", "difficulty breathing", "severe bleeding", "unconscious",
                    "stroke", "seizure", "high fever", "shortness of breath", "suicidal"]
MEDIUM_KEYWORDS = ["fever", "vomiting", "persistent pain", "infection", "dizziness", "rash"]


def _call_llm(prompt: str) -> dict | None:
    api_key = current_app.config["LLM_API_KEY"]
    if not api_key:
        return None
    try:
        resp = requests.post(
            f"{current_app.config['LLM_BASE_URL']}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": current_app.config["LLM_MODEL"],
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
            },
            timeout=current_app.config["LLM_TIMEOUT_SECONDS"],
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        return json.loads(content)
    except Exception as exc:  # network error, timeout, bad JSON, non-2xx, etc.
        current_app.logger.warning(f"LLM call failed, falling back to mock: {exc}")
        return None


def _mock_pre_visit(symptoms: str) -> dict:
    text = symptoms.lower()
    if any(k in text for k in URGENT_KEYWORDS):
        urgency = "High"
    elif any(k in text for k in MEDIUM_KEYWORDS):
        urgency = "Medium"
    else:
        urgency = "Low"
    chief = symptoms.strip().split(".")[0][:140] or "Not specified"
    return {
        "urgency": urgency,
        "chief_complaint": chief,
        "questions": [
            "How long have you had these symptoms?",
            "Have you taken any medication for this already?",
            "Any relevant past medical history or allergies?",
        ],
    }


def _mock_post_visit(notes: str) -> dict:
    return {
        "summary": (
            "Here's a simple summary of your visit based on the doctor's notes: "
            + notes.strip()[:300]
        ),
        "medication_schedule": [
            {"name": "As prescribed", "frequency_hours": 8, "instructions": "See doctor's notes"}
        ],
        "follow_up": ["Contact the clinic if symptoms worsen or don't improve in a few days."],
    }


def generate_pre_visit_summary(symptoms: str) -> tuple[dict, bool]:
    """Returns (summary_dict, llm_failed_bool)."""
    result = _call_llm(PRE_VISIT_PROMPT.format(symptoms=symptoms))
    if result is None:
        return _mock_pre_visit(symptoms), True
    return result, False


def generate_post_visit_summary(notes: str) -> tuple[dict, bool]:
    result = _call_llm(POST_VISIT_PROMPT.format(notes=notes))
    if result is None:
        return _mock_post_visit(notes), True
    return result, False
