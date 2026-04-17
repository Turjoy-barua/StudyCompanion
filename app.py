from __future__ import annotations

import os
from datetime import date
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for

from supabase_client import create_authenticated_supabase_client, create_supabase_client
from utils import SUPABASE_ENABLED, add_academic_item, add_session, get_dashboard_data, init_db


load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "study-companion-dev")

init_db()


def _clear_auth_session() -> None:
    for key in (
        "supabase_access_token",
        "supabase_refresh_token",
        "current_user_id",
        "current_user_email",
    ):
        session.pop(key, None)


def _get_current_user() -> dict[str, str] | None:
    user_id = session.get("current_user_id")
    email = session.get("current_user_email")
    if not user_id or not email:
        return None
    display_name = email.split("@", 1)[0].replace(".", " ").replace("_", " ").strip().title()
    return {
        "id": user_id,
        "email": email,
        "display_name": display_name or "Student",
        "provider": "Email",
    }


def _require_user_id() -> str | None:
    current_user = _get_current_user()
    return current_user["id"] if current_user else None


def _get_authenticated_supabase():
    if not SUPABASE_ENABLED:
        return None

    access_token = session.get("supabase_access_token")
    refresh_token = session.get("supabase_refresh_token")
    if not access_token or not refresh_token:
        return None

    try:
        client = create_authenticated_supabase_client(access_token, refresh_token)
        response = client.auth.set_session(access_token, refresh_token)
        if response.session is not None and response.user is not None:
            session["supabase_access_token"] = response.session.access_token
            session["supabase_refresh_token"] = response.session.refresh_token
            session["current_user_id"] = response.user.id
            session["current_user_email"] = response.user.email or ""
        else:
            _clear_auth_session()
            return None
        return client
    except Exception:
        _clear_auth_session()
        return None


def _login_required(handler):
    @wraps(handler)
    def wrapped(*args, **kwargs):
        if SUPABASE_ENABLED:
            if _get_authenticated_supabase() is None:
                flash("Login is required for that action.", "error")
                return redirect(url_for("index"))
        elif not _get_current_user():
            flash("Login is required for that action.", "error")
            return redirect(url_for("index"))
        return handler(*args, **kwargs)

    return wrapped


def _parse_duration_minutes(raw_value: str) -> int:
    try:
        duration = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Duration must be a whole number of minutes.") from exc

    if duration <= 0:
        raise ValueError("Duration must be greater than zero.")
    return duration


def _parse_confidence(raw_value: str) -> int:
    try:
        confidence = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Confidence must be a whole number.") from exc

    if not 0 <= confidence <= 100:
        raise ValueError("Confidence must be between 0 and 100.")
    return confidence


@app.get("/")
def index():
    authenticated_supabase = _get_authenticated_supabase()
    current_user = _get_current_user()
    dashboard = get_dashboard_data(supabase=authenticated_supabase)
    return render_template(
        "index.html",
        dashboard=dashboard,
        today=date.today().isoformat(),
        current_user=current_user,
        auth_enabled=SUPABASE_ENABLED,
    )


@app.post("/auth/login")
def login():
    if not SUPABASE_ENABLED:
        flash("Supabase authentication is not configured.", "error")
        return redirect(url_for("index"))

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    if not email or not password:
        flash("Email and password are required.", "error")
        return redirect(url_for("index"))

    _clear_auth_session()

    try:
        client = create_supabase_client()
        response = client.auth.sign_in_with_password({"email": email, "password": password})
    except Exception as exc:
        error_text = str(exc).strip() or "Login failed."
        if "Invalid login credentials" in error_text:
            error_text = (
                "Login failed. If you only added the email in Supabase, make sure that user also has a password "
                "and is confirmed."
            )
        flash(error_text, "error")
        return redirect(url_for("index"))

    if response.session is None or response.user is None:
        flash("Login failed. No active session was created.", "error")
        return redirect(url_for("index"))

    session["supabase_access_token"] = response.session.access_token
    session["supabase_refresh_token"] = response.session.refresh_token
    session["current_user_id"] = response.user.id
    session["current_user_email"] = response.user.email or email
    flash("Logged in successfully.", "success")
    return redirect(url_for("index"))


@app.post("/auth/logout")
def logout():
    client = _get_authenticated_supabase()
    if client is not None:
        try:
            client.auth.sign_out()
        except Exception:
            pass
    _clear_auth_session()
    flash("Logged out.", "success")
    return redirect(url_for("index"))


@app.post("/sessions")
@_login_required
def create_session():
    subject = request.form.get("subject", "")
    session_date = request.form.get("session_date") or None

    try:
        duration_minutes = _parse_duration_minutes(request.form.get("duration_minutes", ""))
        add_session(
            subject,
            duration_minutes,
            session_date,
            supabase=_get_authenticated_supabase(),
            user_id=_require_user_id(),
        )
    except ValueError as exc:
        flash(str(exc), "error")
    else:
        flash("Study session saved.", "success")

    return redirect(url_for("index"))


@app.post("/academic-items")
@_login_required
def create_academic_item():
    try:
        add_academic_item(
            request.form.get("title", ""),
            request.form.get("item_kind", ""),
            request.form.get("exam_type", ""),
            request.form.get("chapters", ""),
            request.form.get("importance", ""),
            _parse_confidence(request.form.get("confidence_percent", "")),
            request.form.get("due_date", ""),
            supabase=_get_authenticated_supabase(),
            user_id=_require_user_id(),
        )
    except ValueError as exc:
        flash(str(exc), "error")
    else:
        flash("Upcoming item saved.", "success")

    return redirect(url_for("index"))


@app.post("/api/sessions")
def create_session_api():
    if not _get_current_user():
        return jsonify({"ok": False, "error": "Login is required before saving a session."}), 401

    payload = request.get_json(silent=True) or {}
    subject = payload.get("subject", "")
    session_date = payload.get("session_date") or None

    try:
        duration_minutes = _parse_duration_minutes(str(payload.get("duration_minutes", "")))
        add_session(
            subject,
            duration_minutes,
            session_date,
            supabase=_get_authenticated_supabase(),
            user_id=_require_user_id(),
        )
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    dashboard = get_dashboard_data(supabase=_get_authenticated_supabase())
    return jsonify({"ok": True, "message": "Study session saved.", "dashboard": dashboard})


if __name__ == "__main__":
    app.run(debug=True)
