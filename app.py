from __future__ import annotations

import os
from datetime import date

from flask import Flask, flash, jsonify, redirect, render_template, request, url_for

from utils import add_session, get_dashboard_data, init_db


app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "study-companion-dev")

init_db()


def _parse_duration_minutes(raw_value: str) -> int:
    try:
        duration = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Duration must be a whole number of minutes.") from exc

    if duration <= 0:
        raise ValueError("Duration must be greater than zero.")
    return duration


@app.get("/")
def index():
    dashboard = get_dashboard_data()
    return render_template("index.html", dashboard=dashboard, today=date.today().isoformat())


@app.post("/sessions")
def create_session():
    subject = request.form.get("subject", "")
    session_date = request.form.get("session_date") or None

    try:
        duration_minutes = _parse_duration_minutes(request.form.get("duration_minutes", ""))
        add_session(subject, duration_minutes, session_date)
    except ValueError as exc:
        flash(str(exc), "error")
    else:
        flash("Study session saved.", "success")

    return redirect(url_for("index"))


@app.post("/api/sessions")
def create_session_api():
    payload = request.get_json(silent=True) or {}
    subject = payload.get("subject", "")
    session_date = payload.get("session_date") or None

    try:
        duration_minutes = _parse_duration_minutes(str(payload.get("duration_minutes", "")))
        add_session(subject, duration_minutes, session_date)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    dashboard = get_dashboard_data()
    return jsonify({"ok": True, "message": "Study session saved.", "dashboard": dashboard})


if __name__ == "__main__":
    app.run(debug=True)
