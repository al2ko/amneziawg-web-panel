# region MODULE_CONTRACT [DOMAIN(9): WebPanel; CONCEPT(10): ProtectedRoutes; TECH(9): Flask]
## @modulecontract
## @purpose Предоставить русскоязычные HTTP-операции панели только аутентифицированному администратору.
## @scope Login/logout, dashboard, peer actions, lazy artifact preview/download, audit, backup, interface restart.
## @input HTTP requests with cookie sessions and CSRF tokens.
## @output HTML, downloads and redirects with safe user feedback.
## @invariants Every state-changing request requires POST and CSRF; secret previews require authentication and a validated client name.
## @changes LAST_CHANGE: v1.1.0 adds modal preview API for conf and vpnuri pairs.
## @modulemap FUNC 10[Register protected web surface] => register_routes
def _module_contract():
    pass
# endregion MODULE_CONTRACT
# GREP_SUMMARY: Flask routes, login, CSRF, dashboard, clients, audit, downloads, backup
# STRUCTURE: ▶ request → auth gate → CSRF gate → domain service → audit → response

# BUG_FIX_CONTEXT: Future-import удалён для совместимости с обязательным module contract, типы поддерживаются минимальной версией Python.
import io
import json
import re
import secrets
import sqlite3
import zipfile
from functools import wraps

from flask import Flask, abort, flash, g, jsonify, redirect, render_template, request, send_file, session, url_for

from .artifacts import validate_client_name
from .awg import AwgService, CommandError
from .config import Settings
from .repository import PanelRepository
from .security import AuthService

SESSION_COOKIE = "panel_session"


def register_routes(app: Flask, settings: Settings, repository: PanelRepository, awg: AwgService, auth: AuthService) -> None:
    """▶ dependencies → guarded route closures → Flask URL map."""

    def remote_ip() -> str:
        return request.remote_addr or "unknown"

    def current_auth() -> dict | None:
        if not hasattr(g, "panel_auth"):
            g.panel_auth = auth.authenticate(request.cookies.get(SESSION_COOKIE))
        return g.panel_auth

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_auth():
                return redirect(url_for("login"))
            return view(*args, **kwargs)
        return wrapped

    @app.before_request
    def enforce_csrf():
        if request.method != "POST":
            return None
        submitted = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
        if request.endpoint == "login":
            if not submitted or not secrets.compare_digest(session.get("login_csrf", ""), submitted):
                abort(400, "Недействительный CSRF-токен")
            return None
        if not auth.validate_csrf(current_auth(), submitted):
            abort(400, "Недействительный CSRF-токен")
        return None

    @app.context_processor
    def template_context():
        record = current_auth()
        return {"csrf_token": record["csrf_token"] if record else session.get("login_csrf", "")}

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "GET":
            session["login_csrf"] = secrets.token_urlsafe(32)
            return render_template("login.html")
        result = auth.login(request.form.get("username", ""), request.form.get("password", ""), remote_ip())
        if not result:
            flash("Неверные данные или временная блокировка входа", "error")
            session["login_csrf"] = secrets.token_urlsafe(32)
            return render_template("login.html"), 401
        token, _ = result
        session.pop("login_csrf", None)
        response = redirect(url_for("dashboard"))
        response.set_cookie(
            SESSION_COOKIE, token, max_age=settings.session_timeout, httponly=True,
            secure=settings.secure_cookie, samesite="Strict", path="/",
        )
        return response

    @app.post("/logout")
    @login_required
    def logout():
        auth.logout(request.cookies.get(SESSION_COOKIE), remote_ip())
        response = redirect(url_for("login"))
        response.delete_cookie(SESSION_COOKIE, path="/")
        return response

    @app.get("/")
    @login_required
    def dashboard():
        try:
            snapshot = awg.dashboard()
        except (OSError, ValueError, CommandError) as error:
            app.logger.error("[IMP:10][dashboard_route][FAILED] Unable to build dashboard: %s", type(error).__name__)
            snapshot = None
            flash(f"Не удалось прочитать awg0: {error}", "error")
        return render_template("dashboard.html", dashboard=snapshot)

    def execute_peer_action(action: str, operation, target: str) -> object:
        try:
            operation()
            repository.audit(current_auth()["username"], action, target, remote_ip())
            flash("Операция выполнена", "success")
        except (ValueError, KeyError, FileExistsError, OSError, CommandError, sqlite3.IntegrityError) as error:
            app.logger.warning("[IMP:9][peer_action][REJECTED] %s failed: %s", action, type(error).__name__)
            flash(str(error), "error")
        return redirect(url_for("dashboard"))

    def client_name(public_key: str) -> str:
        record = repository.get_client(public_key)
        return record["name"] if record else public_key

    @app.post("/clients")
    @login_required
    def create_client():
        name = request.form.get("name", "")
        return execute_peer_action("client_create", lambda: awg.create_peer(name), name)

    @app.post("/clients/rename")
    @login_required
    def rename_client():
        key, name = request.form.get("public_key", ""), request.form.get("name", "")
        return execute_peer_action("client_rename", lambda: awg.rename_peer(key, name), name)

    @app.post("/clients/disable")
    @login_required
    def disable_client():
        key = request.form.get("public_key", "")
        return execute_peer_action("client_disable", lambda: awg.disable_peer(key), client_name(key))

    @app.post("/clients/enable")
    @login_required
    def enable_client():
        key = request.form.get("public_key", "")
        return execute_peer_action("client_enable", lambda: awg.enable_peer(key), client_name(key))

    @app.post("/clients/delete")
    @login_required
    def delete_client():
        key = request.form.get("public_key", "")
        if request.form.get("confirm") != "DELETE":
            abort(400, "Требуется подтверждение удаления")
        return execute_peer_action("client_delete", lambda: awg.delete_peer(key), client_name(key))

    @app.post("/clients/details")
    @login_required
    def update_client_details():
        key = request.form.get("public_key", "")

        def save_details() -> None:
            notes = request.form.get("notes", "").strip()
            raw_tags = request.form.get("tags", "")
            if len(notes) > 500 or len(raw_tags) > 250:
                raise ValueError("Заметка или список меток слишком длинный")
            tags = []
            for value in raw_tags.split(","):
                tag = value.strip()
                if not tag:
                    continue
                if len(tag) > 24 or not re.fullmatch(r"[\w -]+", tag):
                    raise ValueError("Метки могут содержать буквы, цифры, пробел, дефис и подчёркивание")
                if tag.casefold() not in {item.casefold() for item in tags}:
                    tags.append(tag)
            if len(tags) > 10:
                raise ValueError("Допускается не более 10 меток")
            repository.update_client_details(key, notes, ", ".join(tags))

        return execute_peer_action("client_details", save_details, client_name(key))

    @app.post("/clients/regenerate")
    @login_required
    def regenerate_client():
        key = request.form.get("public_key", "")
        return execute_peer_action("client_regenerate", lambda: awg.regenerate_peer(key), client_name(key))

    @app.get("/clients/<name>/<kind>")
    @login_required
    def download_artifact(name: str, kind: str):
        try:
            name = validate_client_name(name)
            path = awg.artifacts.get(name, kind)
        except (ValueError, FileNotFoundError):
            abort(404)
        repository.audit(current_auth()["username"], "artifact_download", name, remote_ip(), {"kind": kind})
        inline = request.args.get("inline") == "1" and kind in {"qr", "vpnuri_qr"}
        return send_file(path, as_attachment=not inline, download_name=path.name)

    @app.get("/clients/<name>/artifacts")
    @login_required
    def preview_artifacts(name: str):
        """▶ authenticated client name → bounded variant texts + protected artifact URLs."""
        try:
            name = validate_client_name(name)
            variants = awg.artifacts.variants(name)
        except (ValueError, OSError, UnicodeError):
            abort(404)
        for variant in variants:
            variant["config_url"] = url_for("download_artifact", name=name, kind=variant["config_kind"])
            variant["qr_url"] = url_for("download_artifact", name=name, kind=variant["qr_kind"], inline=1)
            variant["qr_download_url"] = url_for("download_artifact", name=name, kind=variant["qr_kind"])
        repository.audit(current_auth()["username"], "artifact_preview", name, remote_ip())
        app.logger.info("[IMP:8][preview_artifacts][READY] Prepared %d artifact variants for %s", len(variants), name)
        return jsonify({"name": name, "variants": variants})

    @app.post("/interface/restart")
    @login_required
    def restart_interface():
        return execute_peer_action("interface_restart", awg.restart_interface, settings.interface)

    @app.get("/audit")
    @login_required
    def audit_log():
        return render_template("audit.html", entries=repository.recent_audit(100))

    @app.get("/backup")
    @login_required
    def backup():
        """▶ authenticated request → DB/config/snapshot → in-memory ZIP."""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("panel.sql", repository.dump_sql())
            if settings.config_path.is_file():
                archive.write(settings.config_path, "awg0.conf")
            archive.writestr("clients.json", json.dumps(awg.export_snapshot(), ensure_ascii=False, indent=2))
        buffer.seek(0)
        repository.audit(current_auth()["username"], "backup_download", "panel", remote_ip())
        return send_file(buffer, as_attachment=True, download_name="amnezia-panel-backup.zip", mimetype="application/zip")
