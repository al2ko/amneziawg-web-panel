# region MODULE_CONTRACT [DOMAIN(8): Configuration; CONCEPT(9): SafeDefaults; TECH(8): Dataclass]
## @modulecontract
## @purpose Централизовать все системные пути и параметры безопасности панели.
## @scope Environment parsing and immutable application settings.
## @input AMNEZIA_PANEL_* environment variables.
## @output Settings value object.
## @invariants Production secret cannot silently use a documented default.
## @changes LAST_CHANGE: v1.1.0 adds the narrow privileged add-helper setting.
## @modulemap CLASS 9[Panel configuration] => Settings
def _module_contract():
    pass
# endregion MODULE_CONTRACT
# GREP_SUMMARY: environment, settings, paths, awg0, session timeout
# STRUCTURE: ▶ environment variables → validated typed fields → ⎋ immutable Settings

# BUG_FIX_CONTEXT: Future-import после semantic contract вызывал SyntaxError; минимальная версия Python уже поддерживает union-аннотации.
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    secret_key: str
    admin_username: str
    password_hash: str
    database_path: Path
    config_path: Path
    clients_dir: Path
    awg_binary: str = "awg"
    awg_quick_binary: str = "awg-quick"
    interface: str = "awg0"
    endpoint: str = ""
    dns: str = "1.1.1.1"
    session_timeout: int = 1800
    secure_cookie: bool = False
    log_path: Path | None = None
    # BUG_FIX_CONTEXT: Path rewrites a Linux command path with backslashes in Windows tests; argv commands must stay exact strings.
    manage_add_helper: str | None = None
    manage_regen_helper: str | None = None
    expiry_helper: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        """▶ AMNEZIA_PANEL_* → normalize → Settings."""
        secret = os.environ.get("AMNEZIA_PANEL_SECRET", "")
        if len(secret) < 32:
            raise RuntimeError("AMNEZIA_PANEL_SECRET must contain at least 32 characters")
        return cls(
            secret_key=secret,
            admin_username=os.environ.get("AMNEZIA_PANEL_ADMIN", "admin"),
            password_hash=os.environ.get("AMNEZIA_PANEL_PASSWORD_HASH", ""),
            database_path=Path(os.environ.get("AMNEZIA_PANEL_DB", "/var/lib/amnezia-panel/panel.db")),
            config_path=Path(os.environ.get("AMNEZIA_PANEL_CONFIG", "/etc/amnezia/amneziawg/awg0.conf")),
            clients_dir=Path(os.environ.get("AMNEZIA_PANEL_CLIENTS", "/root/awg")),
            awg_binary=os.environ.get("AMNEZIA_PANEL_AWG", "awg"),
            awg_quick_binary=os.environ.get("AMNEZIA_PANEL_AWG_QUICK", "awg-quick"),
            interface=os.environ.get("AMNEZIA_PANEL_INTERFACE", "awg0"),
            endpoint=os.environ.get("AMNEZIA_PANEL_ENDPOINT", ""),
            dns=os.environ.get("AMNEZIA_PANEL_DNS", "1.1.1.1"),
            session_timeout=int(os.environ.get("AMNEZIA_PANEL_SESSION_TIMEOUT", "1800")),
            secure_cookie=os.environ.get("AMNEZIA_PANEL_SECURE_COOKIE", "false").lower() == "true",
            log_path=Path(os.environ["AMNEZIA_PANEL_LOG"]) if os.environ.get("AMNEZIA_PANEL_LOG") else None,
            manage_add_helper=os.environ.get("AMNEZIA_PANEL_ADD_HELPER", "/usr/local/sbin/amnezia-panel-add"),
            manage_regen_helper=os.environ.get("AMNEZIA_PANEL_REGEN_HELPER", "/usr/local/sbin/amnezia-panel-regen"),
            expiry_helper=os.environ.get("AMNEZIA_PANEL_EXPIRY_HELPER", "/usr/local/sbin/amnezia-panel-expiry"),
        )
