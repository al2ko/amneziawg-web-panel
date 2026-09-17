# region MODULE_CONTRACT [DOMAIN(10): Security; CONCEPT(10): AuthenticationSessionCSRF; TECH(9): Argon2]
## @modulecontract
## @purpose Защитить все административные действия паролем, серверной сессией, CSRF и rate limiting.
## @scope Password verification, opaque sessions, inactivity timeout, request tokens.
## @input Credentials, client IP, cookies and CSRF values.
## @output Auth decisions and opaque tokens.
## @invariants Raw session tokens are never persisted; password hashes are never logged.
## @rationale Root-adjacent VPN management requires defense in depth even behind UFW.
## @changes LAST_CHANGE: v1.0.0 initial security service.
## @modulemap CLASS 10[Authentication boundary] => AuthService
def _module_contract():
    pass
# endregion MODULE_CONTRACT
# GREP_SUMMARY: Argon2, login, server session, CSRF, rate limit, timeout
# STRUCTURE: ▶ credentials/IP → rate gate → Argon2 → opaque session ⇄ CSRF validation

# BUG_FIX_CONTEXT: Future-import удалён из-за обязательного semantic header; runtime Python 3.11+ полностью поддерживает аннотации модуля.
import hashlib
import hmac
import logging
import secrets
import time

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from .config import Settings
from .repository import PanelRepository

logger = logging.getLogger(__name__)


class AuthService:
    MAX_FAILURES = 5
    WINDOW_SECONDS = 900

    def __init__(self, settings: Settings, repository: PanelRepository):
        self.settings = settings
        self.repository = repository
        self.hasher = PasswordHasher()

    @staticmethod
    def hash_password(password: str) -> str:
        """▶ password → Argon2id → encoded hash."""
        if len(password) < 12:
            raise ValueError("Пароль должен содержать не менее 12 символов")
        return PasswordHasher().hash(password)

    @staticmethod
    def _digest(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def login(self, username: str, password: str, ip: str) -> tuple[str, str] | None:
        """▶ rate gate → constant verification → session+CSRF or denial."""
        now = int(time.time())
        if self.repository.failed_login_count(ip, now - self.WINDOW_SECONDS) >= self.MAX_FAILURES:
            self.repository.audit(username or "anonymous", "login_blocked", "panel", ip)
            logger.warning("[IMP:9][login][RATE_LIMIT] Login temporarily blocked for source IP")
            return None
        username_valid = hmac.compare_digest(username, self.settings.admin_username)
        try:
            password_valid = self.hasher.verify(self.settings.password_hash, password)
        except (VerifyMismatchError, InvalidHashError):
            password_valid = False
        # BUG_FIX_CONTEXT: Short-circuit проверки имени раскрывал существование логина по времени; Argon2 теперь выполняется для любого username.
        valid = username_valid and password_valid
        self.repository.record_login(ip, valid)
        if not valid:
            self.repository.audit(username or "anonymous", "login_failed", "panel", ip)
            logger.warning("[IMP:9][login][DENIED] Invalid administrator credentials")
            return None
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        self.repository.create_session(self._digest(token), username, csrf, now + self.settings.session_timeout)
        self.repository.audit(username, "login_success", "panel", ip)
        logger.info("[IMP:9][login][SUCCESS] Administrator session created")
        return token, csrf

    def authenticate(self, token: str | None) -> dict | None:
        """▶ opaque cookie → hash lookup → idle timeout → sliding session."""
        if not token:
            return None
        digest = self._digest(token)
        record = self.repository.get_session(digest)
        now = int(time.time())
        if not record or record["expires_at"] < now or now - record["last_seen"] > self.settings.session_timeout:
            if record:
                self.repository.delete_session(digest)
            return None
        self.repository.touch_session(digest, now, now + self.settings.session_timeout)
        return record

    def validate_csrf(self, session_record: dict | None, submitted: str | None) -> bool:
        return bool(session_record and submitted and hmac.compare_digest(session_record["csrf_token"], submitted))

    def logout(self, token: str | None, ip: str) -> None:
        record = self.authenticate(token)
        if token:
            self.repository.delete_session(self._digest(token))
        if record:
            self.repository.audit(record["username"], "logout", "panel", ip)
