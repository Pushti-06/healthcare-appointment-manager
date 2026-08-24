from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user
from extensions import db
from models import User, DoctorProfile

bp = Blueprint("auth", __name__)


@bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        role = request.form["role"]
        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        if role not in ("patient", "doctor"):
            flash("Invalid role.", "error")
            return redirect(url_for("auth.register"))
        if User.query.filter_by(email=email).first():
            flash("An account with that email already exists.", "error")
            return redirect(url_for("auth.register"))

        user = User(role=role, name=name, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.flush()

        if role == "doctor":
            profile = DoctorProfile(
                user_id=user.id,
                specialization=request.form.get("specialization", "General Physician"),
            )
            db.session.add(profile)

        db.session.commit()
        login_user(user)
        flash("Account created!", "success")
        return redirect(url_for(f"{role}.dashboard"))

    return render_template("register.html")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for(f"{user.role}.dashboard"))
        flash("Invalid email or password.", "error")
    return render_template("login.html")


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
