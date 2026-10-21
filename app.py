"""Small Treasury SQL quiz website. Run: flask --app app run."""

import hmac
import json
import os
import secrets
from datetime import timedelta
from functools import wraps
from pathlib import Path
from uuid import UUID

import psycopg
from dotenv import load_dotenv
from flask import Flask, g, jsonify, render_template, request, session

from auth import AuthError, SupabaseAuth
from db import ConfigurationError, QueryRunner, QuizStore
from query_policy import QueryError, prepare_query

ROOT = Path(__file__).resolve().parent


def validate_quiz(data):
    if not isinstance(data, dict):
        raise ValueError("Send a quiz object.")
    title = data.get("title", "")
    questions = data.get("questions")
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 100:
        raise ValueError("Use a quiz title of 1–100 characters.")
    if not isinstance(questions, list) or len(questions) != 5:
        raise ValueError("This quiz must contain five questions.")
    clean = {"title": title.strip(), "questions": []}
    for number, question in enumerate(questions, 1):
        if not isinstance(question, dict):
            raise ValueError("Each question must contain a prompt and reference SQL.")
        prompt = question.get("prompt", "")
        if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 2000:
            raise ValueError("Each question needs a prompt of 1–2,000 characters.")
        if type(question.get("points")) is not int or question["points"] != 4:
            raise ValueError("Use five questions worth four points each (20 total).")
        sql = question.get("reference_sql", "")
        prepare_query(sql)
        clean["questions"].append({
            "id": number, "prompt": prompt.strip(), "points": 4, "reference_sql": sql,
        })
    return clean


def create_app(test_config=None):
    load_dotenv(ROOT / ".env", override=False)
    app = Flask(__name__)
    production = os.getenv("APP_ENV") == "production"
    app.config.update(
        SECRET_KEY=os.getenv("SECRET_KEY") or (None if production else secrets.token_hex(32)),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=production,
        PERMANENT_SESSION_LIFETIME=timedelta(minutes=55),
        MAX_CONTENT_LENGTH=64 * 1024,
        AUTH=SupabaseAuth(os.getenv("SUPABASE_URL", ""), os.getenv("SUPABASE_KEY", "")),
        RUNNER=QueryRunner(os.getenv("QUERY_DATABASE_URL", "")),
        STORE=QuizStore(os.getenv("SAVE_DATABASE_URL", "")),
    )
    if test_config:
        app.config.update(test_config)
    if not app.config["SECRET_KEY"]:
        raise RuntimeError("Set SECRET_KEY before deploying.")

    def require_user(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            token = session.get("access_token")
            if not token:
                return jsonify(error="Sign in to run SQL or save a quiz."), 401
            try:
                g.user = app.config["AUTH"].user(token)
            except AuthError as exc:
                if exc.status == 401:
                    session.pop("access_token", None)
                raise
            return view(*args, **kwargs)
        return wrapped

    @app.before_request
    def csrf_check():
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            expected = session.get("csrf_token", "")
            supplied = request.headers.get("X-CSRF-Token", "")
            if not expected or not hmac.compare_digest(expected, supplied):
                return jsonify(error="Refresh the page and try again."), 403

    @app.after_request
    def response_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
            "base-uri 'self'; form-action 'self'"
        )
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(AuthError)
    def auth_error(exc):
        return jsonify(error=str(exc)), exc.status

    @app.errorhandler(QueryError)
    @app.errorhandler(ValueError)
    def bad_input(exc):
        return jsonify(error=str(exc)), 400

    @app.errorhandler(ConfigurationError)
    def configuration_error(exc):
        return jsonify(error=str(exc)), 503

    @app.errorhandler(psycopg.Error)
    def database_error(exc):
        app.logger.warning("Database operation failed (%s)", type(exc).__name__)
        return jsonify(error="The database operation failed. Check the setup or try again."), 503

    @app.errorhandler(PermissionError)
    def permission_error(exc):
        return jsonify(error=str(exc)), 403

    @app.errorhandler(413)
    def too_large(exc):
        return jsonify(error="This request is too large."), 413

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    @app.get("/api/bootstrap")
    def bootstrap():
        session.setdefault("csrf_token", secrets.token_urlsafe(32))
        return jsonify(
            csrf_token=session["csrf_token"],
            quiz=json.loads((ROOT / "data/quiz.json").read_text()),
            configured=all(os.getenv(k) and "YOUR_PROJECT" not in os.getenv(k, "")
                           for k in ["SUPABASE_URL", "SUPABASE_KEY", "QUERY_DATABASE_URL", "SAVE_DATABASE_URL"]),
        )

    @app.get("/api/me")
    def me():
        token = session.get("access_token")
        if not token:
            return jsonify(user=None)
        try:
            return jsonify(user=app.config["AUTH"].user(token))
        except AuthError as exc:
            if exc.status == 401:
                session.pop("access_token", None)
            raise

    def credentials():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise ValueError("Enter an email and password.")
        email, password = body.get("email"), body.get("password")
        if not isinstance(email, str) or "@" not in email or len(email) > 254:
            raise ValueError("Enter a valid email address.")
        if not isinstance(password, str) or not 1 <= len(password) <= 256:
            raise ValueError("Enter your password.")
        return email.strip(), password

    @app.post("/api/auth/login")
    def login():
        email, password = credentials()
        result = app.config["AUTH"].login(email, password)
        token = result.get("access_token")
        if not token:
            raise AuthError("Check your email confirmation before signing in.")
        user = app.config["AUTH"].user(token)
        csrf = session["csrf_token"]
        session.clear()
        session.update(access_token=token, csrf_token=csrf)
        session.permanent = True
        return jsonify(user=user)

    @app.post("/api/auth/signup")
    def signup():
        email, password = credentials()
        if len(password) < 8:
            raise ValueError("Choose a password with at least eight characters.")
        result = app.config["AUTH"].signup(email, password)
        if result.get("access_token"):
            return jsonify(message="Account created. You can sign in now.")
        return jsonify(message="Check your email to confirm your account, then sign in here.")

    @app.post("/api/auth/logout")
    def logout():
        token = session.get("access_token")
        csrf = session.get("csrf_token")
        session.clear()
        session["csrf_token"] = csrf
        if token:
            try:
                app.config["AUTH"].logout(token)
            except AuthError:
                pass  # Local cookie is still cleared if the provider is unavailable.
        return jsonify(message="Signed out.")

    @app.post("/api/query")
    @require_user
    def query():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise ValueError("Send a SQL query.")
        return jsonify(app.config["RUNNER"].run(body.get("sql")))

    @app.get("/api/quizzes")
    @require_user
    def list_quizzes():
        return jsonify(quizzes=app.config["STORE"].list(g.user["id"]))

    @app.post("/api/quizzes")
    @require_user
    def save_quiz():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise ValueError("Send a quiz to save.")
        quiz = validate_quiz(body.get("quiz"))
        quiz_id = body.get("id")
        if quiz_id is not None:
            try:
                quiz_id = str(UUID(quiz_id))
            except (ValueError, TypeError, AttributeError) as exc:
                raise ValueError("Invalid quiz identifier.") from exc
        # Derive hints from real SQL results, never trust client-supplied answers.
        for question in quiz["questions"]:
            result = app.config["RUNNER"].run(question["reference_sql"])
            if result["truncated"]:
                raise ValueError("A reference answer exceeds 200 rows. Narrow the question.")
            question["expected"] = result
        quiz_id = app.config["STORE"].save(g.user["id"], quiz, quiz_id)
        return jsonify(id=quiz_id, quiz=quiz), 201

    @app.get("/api/quizzes/<uuid:quiz_id>")
    @require_user
    def get_quiz(quiz_id):
        quiz = app.config["STORE"].get(g.user["id"], str(quiz_id))
        if quiz is None:
            return jsonify(error="Quiz not found."), 404
        return jsonify(id=str(quiz_id), quiz=quiz)

    return app


app = create_app()
