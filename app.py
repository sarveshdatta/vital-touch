"""Vital Touch backend.

Receives readings from the ESP32 wearable, stores them in SQLite, evaluates
alert rules and serves the monitoring dashboard.

Run:  python app.py        (configuration via environment / .env, see README)
"""

import hmac
import os
import random
import threading
import time
from functools import wraps
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory, session

import db
from alerts import evaluate, validate_reading

try:  # optional: load backend/.env if python-dotenv is installed
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR.parent / "frontend"


def create_app(overrides=None):
    app = Flask(__name__, static_folder=None)
    app.config.update(
        DATABASE=os.environ.get("VT_DATABASE", str(BASE_DIR / "vital_touch.db")),
        DEVICE_API_KEY=os.environ.get("VT_DEVICE_API_KEY", ""),
        ADMIN_USERNAME=os.environ.get("VT_ADMIN_USERNAME", "admin"),
        ADMIN_PASSWORD=os.environ.get("VT_ADMIN_PASSWORD", ""),
        ADMIN_NAME=os.environ.get("VT_ADMIN_NAME", "Administrator"),
        SECRET_KEY=os.environ.get("VT_SECRET_KEY") or os.urandom(32).hex(),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    if overrides:
        app.config.update(overrides)

    db.init_db(app.config["DATABASE"])

    def login_required(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if "user" not in session:
                return jsonify(error="login required"), 401
            return view(*args, **kwargs)

        return wrapper

    # ---------- dashboard ----------
    @app.get("/")
    def index():
        return send_from_directory(FRONTEND_DIR, "index.html")

    @app.get("/api/health")
    def health():
        return jsonify(status="ok")

    # ---------- auth ----------
    @app.post("/api/login")
    def login():
        if not app.config["ADMIN_PASSWORD"]:
            return jsonify(error="Dashboard password not configured (set VT_ADMIN_PASSWORD)"), 503
        body = request.get_json(silent=True) or {}
        username = str(body.get("username", ""))
        password = str(body.get("password", ""))
        ok_user = hmac.compare_digest(username, app.config["ADMIN_USERNAME"])
        ok_pass = hmac.compare_digest(password, app.config["ADMIN_PASSWORD"])
        if not (ok_user and ok_pass):
            return jsonify(error="Invalid credentials."), 401
        session.clear()
        session["user"] = username
        return jsonify(_current_user(app))

    @app.post("/api/logout")
    def logout():
        session.clear()
        return jsonify(status="logged out")

    @app.get("/api/me")
    @login_required
    def me():
        return jsonify(_current_user(app))

    # ---------- device ingest ----------
    @app.post("/api/readings")
    def create_reading():
        expected = app.config["DEVICE_API_KEY"]
        if not expected:
            return jsonify(error="Device API key not configured (set VT_DEVICE_API_KEY)"), 503
        supplied = request.headers.get("X-API-Key", "")
        if not hmac.compare_digest(supplied, expected):
            return jsonify(error="invalid API key"), 401

        clean, errors = validate_reading(request.get_json(silent=True))
        if errors:
            return jsonify(error="invalid reading", details=errors), 400

        status, issues = evaluate(clean["heart_rate"], clean["spo2"], clean["temperature"])
        saved = db.insert_reading(app.config["DATABASE"], clean, status, issues, source="device")
        return jsonify(saved), 201

    # ---------- dashboard data ----------
    @app.get("/api/readings")
    @login_required
    def list_readings():
        after_id = request.args.get("after_id", default=0, type=int)
        limit = max(1, min(request.args.get("limit", default=50, type=int), 500))
        return jsonify(readings=db.list_readings(app.config["DATABASE"], after_id, limit))

    @app.get("/api/readings/latest")
    @login_required
    def latest():
        return jsonify(reading=db.latest_reading(app.config["DATABASE"]))

    @app.post("/api/sos")
    @login_required
    def sos():
        body = request.get_json(silent=True) or {}
        message = str(body.get("message") or "SOS raised from dashboard")[:200]
        event = db.insert_event(app.config["DATABASE"], "sos", message, session["user"])
        return jsonify(event), 201

    @app.get("/api/events")
    @login_required
    def events():
        return jsonify(events=db.list_events(app.config["DATABASE"]))

    return app


def _current_user(app):
    return {"username": session["user"], "name": app.config["ADMIN_NAME"], "role": "Administrator"}


def start_simulator(app, interval_s=3.0):
    """Demo mode: insert synthetic readings, clearly tagged source='simulator'.

    Used only when no hardware is connected. The dashboard labels these as
    simulated data.
    """

    def run():
        while True:
            hr, spo2, temp = random.randint(68, 92), random.randint(96, 99), round(random.uniform(36.4, 37.1), 1)
            roll = random.random()
            if roll < 0.05:
                spo2 = random.randint(86, 89)          # critical desaturation
            elif roll < 0.12:
                hr = random.randint(104, 125)          # tachycardia
            elif roll < 0.16:
                temp = round(random.uniform(37.6, 38.4), 1)  # fever
            reading = {"device_id": "SIMULATOR", "heart_rate": hr, "spo2": spo2, "temperature": temp}
            status, issues = evaluate(hr, spo2, temp)
            db.insert_reading(app.config["DATABASE"], reading, status, issues, source="simulator")
            time.sleep(interval_s)

    threading.Thread(target=run, daemon=True).start()


if __name__ == "__main__":
    application = create_app()
    if os.environ.get("VT_SIMULATE", "0") == "1":
        print("[Vital Touch] Simulator ON: synthetic readings will be generated (tagged 'simulator').")
        start_simulator(application)
    # debug=False: the debug reloader would start the simulator twice
    application.run(host=os.environ.get("VT_HOST", "0.0.0.0"), port=int(os.environ.get("VT_PORT", "5000")), debug=False)
