from __future__ import annotations

import os
import re
from datetime import date
from email.utils import parseaddr
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for

from supabase_client import create_authenticated_supabase_client, create_supabase_client
from utils import (
    SUPABASE_ENABLED,
    add_academic_item,
    add_session,
    add_study_subject,
    delete_academic_item,
    delete_session,
    get_dashboard_data,
    init_db,
    update_academic_item,
    update_chapter_confidence,
    update_session,
)


load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "study-companion-dev")

init_db()


EMAIL_PATTERN = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.IGNORECASE)


def _clear_auth_session() -> None:
    for key in (
        "supabase_access_token",
        "supabase_refresh_token",
        "current_user_id",
        "current_user_email",
        "current_user_display_name",
    ):
        session.pop(key, None)


def _get_current_user() -> dict[str, str] | None:
    user_id = session.get("current_user_id")
    email = session.get("current_user_email")
    if not user_id or not email:
        return None
    display_name = session.get("current_user_display_name") or email.split("@", 1)[0].replace(".", " ").replace("_", " ").strip().title()
    return {
        "id": user_id,
        "email": email,
        "display_name": display_name or "Student",
        "provider": "Email",
    }


def _require_user_id() -> str | None:
    current_user = _get_current_user()
    return current_user["id"] if current_user else None


def _is_valid_email(email: str) -> bool:
    parsed_name, parsed_email = parseaddr(email)
    if parsed_name or parsed_email != email:
        return False
    if len(email) > 254 or ".." in email or not EMAIL_PATTERN.fullmatch(email):
        return False
    local_part, domain = email.rsplit("@", 1)
    domain_labels = domain.split(".")
    return (
        bool(local_part)
        and len(local_part) <= 64
        and all(label and not label.startswith("-") and not label.endswith("-") for label in domain_labels)
    )


def _auth_redirect_url(endpoint: str) -> str:
    configured_url = os.environ.get("APP_BASE_URL", "").rstrip("/")
    if configured_url:
        return f"{configured_url}{url_for(endpoint)}"
    return url_for(endpoint, _external=True)


def _store_auth_session(auth_response, fallback_email: str = "") -> bool:
    if auth_response.session is None or auth_response.user is None:
        return False

    metadata = getattr(auth_response.user, "user_metadata", None) or {}
    display_name = (
        metadata.get("full_name")
        or metadata.get("name")
        or metadata.get("display_name")
        or ""
    )

    session["supabase_access_token"] = auth_response.session.access_token
    session["supabase_refresh_token"] = auth_response.session.refresh_token
    session["current_user_id"] = auth_response.user.id
    session["current_user_email"] = auth_response.user.email or fallback_email
    session["current_user_display_name"] = display_name
    return True


def _ensure_user_profile(client, user) -> None:
    if client is None or user is None:
        return

    email = user.email or ""
    metadata = getattr(user, "user_metadata", None) or {}
    display_name = (
        metadata.get("full_name")
        or metadata.get("name")
        or metadata.get("display_name")
        or (email.split("@", 1)[0] if email else "Student")
    )

    try:
        client.table("profiles").upsert(
            {
                "id": user.id,
                "email": email,
                "display_name": display_name,
            },
            on_conflict="id",
        ).execute()
    except Exception:
        # The profile trigger/schema may not be installed yet. Auth still works,
        # and supabase_schema.sql contains the required table and policies.
        pass


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
            _ensure_user_profile(client, response.user)
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


def _parse_nonnegative_minutes(raw_value: str) -> int:
    try:
        minutes = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Weekly goal must be a whole number of minutes.") from exc

    if minutes < 0:
        raise ValueError("Weekly goal cannot be negative.")
    return minutes


@app.get("/")
def index():
    authenticated_supabase = _get_authenticated_supabase()
    current_user = _get_current_user()
    dashboard = get_dashboard_data(
        supabase=authenticated_supabase,
        user_id=current_user["id"] if current_user else None,
    )
    return render_template(
        "index.html",
        dashboard=dashboard,
        today=date.today().isoformat(),
        current_user=current_user,
        auth_enabled=SUPABASE_ENABLED,
    )


@app.get("/demo/two-week-plan")
def two_week_plan_demo():
    dashboard = get_dashboard_data(demo=True)
    return render_template(
        "index.html",
        dashboard=dashboard,
        today=date.today().isoformat(),
        current_user=None,
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
    if not _is_valid_email(email):
        flash("Enter a valid email address.", "error")
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

    _store_auth_session(response, fallback_email=email)
    _ensure_user_profile(client, response.user)
    flash("Logged in successfully.", "success")
    return redirect(url_for("index"))


@app.post("/auth/signup")
def signup():
    if not SUPABASE_ENABLED:
        flash("Supabase authentication is not configured.", "error")
        return redirect(url_for("index"))

    email = request.form.get("email", "").strip().lower()
    display_name = " ".join(request.form.get("display_name", "").split()).strip()
    password = request.form.get("password", "")
    confirm_password = request.form.get("confirm_password", "")

    if not email or not password:
        flash("Email and password are required.", "error")
        return redirect(url_for("index"))
    if not _is_valid_email(email):
        flash("Enter a valid email address.", "error")
        return redirect(url_for("index"))
    if not display_name or len(display_name) > 80:
        flash("Display name is required and must be 80 characters or fewer.", "error")
        return redirect(url_for("index"))
    if len(password) < 6:
        flash("Password must be at least 6 characters.", "error")
        return redirect(url_for("index"))
    if password != confirm_password:
        flash("Passwords do not match.", "error")
        return redirect(url_for("index"))

    _clear_auth_session()

    try:
        client = create_supabase_client()
        response = client.auth.sign_up(
            {
                "email": email,
                "password": password,
                "options": {
                    "email_redirect_to": _auth_redirect_url("auth_callback"),
                    "data": {"full_name": display_name},
                },
            }
        )
    except Exception as exc:
        flash(str(exc).strip() or "Signup failed.", "error")
        return redirect(url_for("index"))

    if response.session is not None and response.user is not None:
        _store_auth_session(response, fallback_email=email)
        _ensure_user_profile(client, response.user)
        flash("Account created and logged in.", "success")
    else:
        flash("Account created. Check your email to confirm it, then log in.", "success")

    return redirect(url_for("index"))


@app.get("/auth/google")
def google_login():
    if not SUPABASE_ENABLED:
        flash("Supabase authentication is not configured.", "error")
        return redirect(url_for("index"))

    try:
        client = create_supabase_client()
        response = client.auth.sign_in_with_oauth(
            {
                "provider": "google",
                "options": {"redirect_to": _auth_redirect_url("auth_callback")},
            }
        )
    except Exception as exc:
        flash(str(exc).strip() or "Could not start Google login.", "error")
        return redirect(url_for("index"))

    return redirect(response.url)


@app.get("/auth/callback")
def auth_callback():
    if not SUPABASE_ENABLED:
        flash("Supabase authentication is not configured.", "error")
        return redirect(url_for("index"))

    code = request.args.get("code")
    if code:
        try:
            client = create_supabase_client()
            response = client.auth.exchange_code_for_session({"auth_code": code})
            if _store_auth_session(response):
                _ensure_user_profile(client, response.user)
                flash("Account connected successfully.", "success")
            else:
                flash("Could not finish account connection.", "error")
        except Exception as exc:
            flash(str(exc).strip() or "Could not finish account connection.", "error")
        return redirect(url_for("index"))

    return render_template("auth_callback.html")


@app.post("/auth/session")
def set_auth_session():
    if not SUPABASE_ENABLED:
        return jsonify({"ok": False, "error": "Supabase authentication is not configured."}), 400

    payload = request.get_json(silent=True) or {}
    access_token = payload.get("access_token", "")
    refresh_token = payload.get("refresh_token", "")
    if not access_token or not refresh_token:
        return jsonify({"ok": False, "error": "Missing Supabase auth tokens."}), 400

    try:
        client = create_authenticated_supabase_client(access_token, refresh_token)
        response = client.auth.set_session(access_token, refresh_token)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc).strip() or "Could not set session."}), 400

    if not _store_auth_session(response):
        return jsonify({"ok": False, "error": "Could not set session."}), 400

    _ensure_user_profile(client, response.user)
    return jsonify({"ok": True})


@app.post("/auth/forgot-password")
def forgot_password():
    if not SUPABASE_ENABLED:
        flash("Supabase authentication is not configured.", "error")
        return redirect(url_for("index"))

    email = request.form.get("email", "").strip().lower()
    if not email:
        flash("Email is required.", "error")
        return redirect(url_for("index"))
    if not _is_valid_email(email):
        flash("Enter a valid email address.", "error")
        return redirect(url_for("index"))

    try:
        client = create_supabase_client()
        client.auth.reset_password_email(email, {"redirect_to": _auth_redirect_url("reset_password")})
    except Exception as exc:
        flash(str(exc).strip() or "Could not send reset email.", "error")
        return redirect(url_for("index"))

    flash("Password reset email sent. Check your inbox.", "success")
    return redirect(url_for("index"))


@app.get("/auth/reset-password")
def reset_password():
    if not SUPABASE_ENABLED:
        flash("Supabase authentication is not configured.", "error")
        return redirect(url_for("index"))

    code = request.args.get("code")
    if code:
        try:
            client = create_supabase_client()
            response = client.auth.exchange_code_for_session({"auth_code": code})
            if not _store_auth_session(response):
                flash("Could not open the password reset session.", "error")
        except Exception as exc:
            flash(str(exc).strip() or "Could not open the password reset session.", "error")

    return render_template("auth_reset.html")


@app.post("/auth/update-password")
def update_password():
    if not SUPABASE_ENABLED:
        flash("Supabase authentication is not configured.", "error")
        return redirect(url_for("index"))

    password = request.form.get("password", "")
    confirm_password = request.form.get("confirm_password", "")
    if len(password) < 6:
        flash("Password must be at least 6 characters.", "error")
        return redirect(url_for("reset_password"))
    if password != confirm_password:
        flash("Passwords do not match.", "error")
        return redirect(url_for("reset_password"))

    client = _get_authenticated_supabase()
    if client is None:
        flash("Open the reset link from your email before creating a new password.", "error")
        return redirect(url_for("index"))

    try:
        client.auth.update_user({"password": password})
    except Exception as exc:
        flash(str(exc).strip() or "Could not update password.", "error")
        return redirect(url_for("reset_password"))

    flash("Password updated. You can now use your new password.", "success")
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
            request.form.get("subject_name", ""),
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


@app.post("/sessions/<int:session_id>/edit")
@_login_required
def edit_session(session_id: int):
    try:
        update_session(
            session_id,
            request.form.get("subject", ""),
            _parse_duration_minutes(request.form.get("duration_minutes", "")),
            request.form.get("session_date", ""),
            supabase=_get_authenticated_supabase(),
            user_id=_require_user_id(),
        )
    except ValueError as exc:
        flash(str(exc), "error")
    else:
        flash("Study session updated.", "success")

    return redirect(url_for("index"))


@app.post("/sessions/<int:session_id>/delete")
@_login_required
def remove_session(session_id: int):
    try:
        delete_session(
            session_id,
            supabase=_get_authenticated_supabase(),
            user_id=_require_user_id(),
        )
    except ValueError as exc:
        flash(str(exc), "error")
    else:
        flash("Study session deleted.", "success")

    return redirect(url_for("index"))


@app.post("/academic-items/<int:item_id>/edit")
@_login_required
def edit_academic_item(item_id: int):
    try:
        update_academic_item(
            item_id,
            request.form.get("title", ""),
            request.form.get("subject_name", ""),
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
        flash("Upcoming item updated.", "success")

    return redirect(url_for("index"))


@app.post("/academic-items/<int:item_id>/delete")
@_login_required
def remove_academic_item(item_id: int):
    try:
        delete_academic_item(
            item_id,
            supabase=_get_authenticated_supabase(),
            user_id=_require_user_id(),
        )
    except ValueError as exc:
        flash(str(exc), "error")
    else:
        flash("Upcoming item deleted.", "success")

    return redirect(url_for("index"))


@app.post("/chapters/confidence")
@_login_required
def change_chapter_confidence():
    try:
        update_chapter_confidence(
            request.form.get("chapter_id", ""),
            int(request.form.get("confidence_level", "")),
        )
    except (TypeError, ValueError) as exc:
        flash(str(exc), "error")
    else:
        flash("Chapter confidence updated.", "success")

    return redirect(url_for("index"))


@app.post("/subjects")
@_login_required
def create_study_subject():
    try:
        add_study_subject(
            request.form.get("name", ""),
            request.form.get("priority", ""),
            _parse_confidence(request.form.get("confidence_percent", "")),
            _parse_nonnegative_minutes(request.form.get("weekly_goal_minutes", "0")),
            request.form.get("notes", ""),
            supabase=_get_authenticated_supabase(),
            user_id=_require_user_id(),
        )
    except ValueError as exc:
        flash(str(exc), "error")
    else:
        flash("Subject saved.", "success")

    return redirect(url_for("index"))


@app.post("/api/sessions")
def create_session_api():
    if SUPABASE_ENABLED and not _get_current_user():
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

    dashboard = get_dashboard_data(
        supabase=_get_authenticated_supabase(),
        user_id=_require_user_id(),
    )
    return jsonify({"ok": True, "message": "Study session saved.", "dashboard": dashboard})


if __name__ == "__main__":
    app.run(debug=True)
