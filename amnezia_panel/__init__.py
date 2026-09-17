# region MODULE_CONTRACT [DOMAIN(9): VPNAdministration; CONCEPT(9): ApplicationFactory; TECH(9): Flask]
## @modulecontract
## @purpose Собирать самостоятельное защищённое приложение панели из заменяемых сервисов.
## @scope Flask factory, dependency injection, logging, database initialization.
## @input Environment-backed Settings or explicit test Settings.
## @output Configured Flask application.
## @links USES_API(Flask); USES_CLASS(PanelRepository, AwgService, AuthService)
## @invariants Приложение не выполняет VPN-команды во время импорта.
## @rationale Фабрика приложения позволяет тестировать маршруты без запуска HTTP-сервера.
## @changes LAST_CHANGE: v1.0.0 initial application factory.
## @modulemap FUNC 10[Build application] => create_app
def _module_contract():
    pass
# endregion MODULE_CONTRACT
# GREP_SUMMARY: Flask factory, dependency injection, repository, authentication, awg0 panel
# STRUCTURE: ▶ Settings → SQLite repository → security + AWG services → routes → ⎋ Flask app

# BUG_FIX_CONTEXT: Future-import после обязательного MODULE_CONTRACT нарушал синтаксис Python; Python 3.11+ поддерживает используемые аннотации напрямую.
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Flask

from .artifacts import ArtifactService
from .awg import AwgService, CommandRunner
from .config import Settings
from .repository import PanelRepository
from .routes import register_routes
from .security import AuthService

MOSCOW_TIMEZONE = timezone(timedelta(hours=3))


# region FUNC_create_app [DOMAIN(9): VPNAdministration; CONCEPT(9): DependencyInjection; TECH(9): Flask]
## @purpose Создать панель с production-настройками либо полностью изолированными тестовыми зависимостями.
## @uses Settings, PanelRepository, AuthService, AwgService, ArtifactService
## @io Settings|None, dict|None -> Flask
## @complexity 7
def create_app(settings: Settings | None = None, overrides: dict | None = None) -> Flask:
    """▶ config → services → route registration → ready app."""
    settings = settings or Settings.from_env()
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.update(
        SECRET_KEY=settings.secret_key,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_SECURE=settings.secure_cookie,
        MAX_CONTENT_LENGTH=64 * 1024,
    )
    if overrides:
        app.config.update(overrides)

    repository = PanelRepository(settings.database_path)
    repository.initialize()
    runner = app.config.get("COMMAND_RUNNER") or CommandRunner()
    artifacts = ArtifactService(settings.clients_dir)
    awg_service = app.config.get("AWG_SERVICE") or AwgService(settings, repository, runner, artifacts)
    auth_service = AuthService(settings, repository)
    app.extensions["panel_repository"] = repository
    app.extensions["awg_service"] = awg_service
    app.extensions["auth_service"] = auth_service
    app.add_template_filter(_format_size, "filesize")
    app.add_template_filter(_format_datetime, "datetime")
    app.add_template_filter(_format_moscow_date, "moscow_date")
    register_routes(app, settings, repository, awg_service, auth_service)
    _configure_logging(app, settings)
    app.logger.info("[IMP:9][create_app][READY] Panel services initialized for interface %s", settings.interface)
    return app
# endregion FUNC_create_app


def _format_size(value: int) -> str:
    """▶ byte count → compact binary unit."""
    amount = float(value)
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if amount < 1024 or unit == "ТБ":
            return f"{amount:.0f} {unit}" if unit == "Б" else f"{amount:.1f} {unit}"
        amount /= 1024
    return "0 Б"


def _format_datetime(timestamp: int) -> str:
    """▶ Unix timestamp → concise Moscow datetime."""
    value = datetime.fromtimestamp(timestamp, MOSCOW_TIMEZONE)
    return value.strftime("%d.%m.%Y %H:%M") + " МСК"


def _format_moscow_date(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, MOSCOW_TIMEZONE).strftime("%Y-%m-%d")


def _configure_logging(app: Flask, settings: Settings) -> None:
    """◇ writable log path ? rotating file : stderr only."""
    app.logger.setLevel(logging.INFO)
    if settings.log_path:
        try:
            Path(settings.log_path).parent.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(settings.log_path, maxBytes=2_000_000, backupCount=5, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            app.logger.addHandler(handler)
        except OSError:
            app.logger.warning("[IMP:8][_configure_logging][FILE_UNAVAILABLE] Using stderr logging")
