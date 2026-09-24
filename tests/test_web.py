# region MODULE_CONTRACT [DOMAIN(10): Testing; CONCEPT(10): HeadlessWebFlow; TECH(9): FlaskClient]
## @modulecontract
## @purpose Проверить защищённые маршруты панели без запуска HTTP-сервера или браузера.
## @scope Login CSRF, cookie auth, dashboard, lazy artifact preview, mutations and logout.
## @input Temporary Settings and injected fake AWG service.
## @output HTTP behavior assertions.
## @invariants State changes without CSRF are rejected.
## @changes LAST_CHANGE: v1.1.0 verifies plain and encrypted modal preview API.
## @modulemap FUNC 10[Integrated web scenario] => test_full_web_flow
def _module_contract():
    pass
# endregion MODULE_CONTRACT
# GREP_SUMMARY: Flask test client, login, CSRF, cookie, dashboard, protected routes
# STRUCTURE: ▶ GET login → signed CSRF → POST credentials → server cookie → dashboard/action/logout

import re
from pathlib import Path

from amnezia_panel import _format_datetime, create_app
from amnezia_panel.config import Settings
from amnezia_panel.models import Dashboard, PeerView
from amnezia_panel.security import AuthService


class FakeArtifacts:
    def get(self, name, kind):
        raise FileNotFoundError(name)

    def variants(self, name):
        return [
            {"id": "plain", "label": "Без шифрования", "available": True, "text": "[Interface]\nAddress = 10.8.1.2/32", "config_kind": "conf", "qr_kind": "qr", "qr_available": True},
            {"id": "encrypted", "label": "С шифрованием", "available": True, "text": "vpn://ENCRYPTED", "config_kind": "vpnuri", "qr_kind": "vpnuri_qr", "qr_available": True},
        ]


class FakeAwg:
    def __init__(self):
        self.artifacts = FakeArtifacts()
        self.created = []
        self.durations = []
        self.regenerated = []

    def dashboard(self):
        return Dashboard(True, "up 1 hour", "активен", [PeerView(
            "phone", "PUBLIC", "10.8.1.2", latest_handshake=1, status="active", notes="Личный телефон", tags="личный, телефон", expires_at=2000000000,
        )])

    def create_peer(self, name, duration=""):
        self.created.append(name)
        self.durations.append(duration)

    def rename_peer(self, public_key, name):
        return None

    def regenerate_peer(self, public_key):
        self.regenerated.append(public_key)

    def disable_peer(self, public_key):
        return None

    def enable_peer(self, public_key):
        return None

    def delete_peer(self, public_key):
        return None

    def restart_interface(self):
        return None

    def export_snapshot(self):
        return []


def extract_csrf(response):
    match = re.search(rb'name="csrf_token" value="([^"]+)"', response.data)
    assert match
    return match.group(1).decode()


def test_datetime_is_displayed_in_moscow_time():
    assert _format_datetime(0) == "01.01.1970 03:00 МСК"


def test_full_web_flow(tmp_path):
    password = "correct horse battery staple"
    settings = Settings(
        secret_key="w" * 32, admin_username="admin", password_hash=AuthService.hash_password(password),
        database_path=tmp_path / "web.db", config_path=tmp_path / "awg0.conf", clients_dir=tmp_path / "clients",
    )
    fake_awg = FakeAwg()
    app = create_app(settings, {"TESTING": True, "AWG_SERVICE": fake_awg})
    repository = app.extensions["panel_repository"]
    repository.upsert_client("PUBLIC", "phone", "10.8.1.2")
    client = app.test_client()
    assert client.get("/").status_code == 302
    login_page = client.get("/login")
    login_csrf = extract_csrf(login_page)
    response = client.post("/login", data={"username": "admin", "password": password, "csrf_token": login_csrf})
    assert response.status_code == 302
    dashboard = client.get("/")
    assert dashboard.status_code == 200
    assert "phone" in dashboard.get_data(as_text=True)
    assert "QR и conf" in dashboard.get_data(as_text=True)
    assert "↓ conf" not in dashboard.get_data(as_text=True)
    assert 'data-auto-refresh="60000"' in dashboard.get_data(as_text=True)
    assert 'data-refresh' in dashboard.get_data(as_text=True)
    assert "Обновить" in dashboard.get_data(as_text=True)
    assert "Система" in dashboard.get_data(as_text=True)
    assert '<details class="panel system-panel">' in dashboard.get_data(as_text=True)
    assert dashboard.get_data(as_text=True).index('id="peer-table"') < dashboard.get_data(as_text=True).index('<details class="panel system-panel">')
    assert 'id="peer-status"' in dashboard.get_data(as_text=True)
    assert 'id="compact-mode"' not in dashboard.get_data(as_text=True)
    assert 'id="peer-table" class="compact"' in dashboard.get_data(as_text=True)
    assert 'data-relative-time data-timestamp="1"' in dashboard.get_data(as_text=True)
    assert "Перегенерировать конфиг" in dashboard.get_data(as_text=True)
    assert "Временный" in dashboard.get_data(as_text=True)
    assert 'name="duration"' in dashboard.get_data(as_text=True)
    assert 'data-expiry="2000000000"' in dashboard.get_data(as_text=True)
    assert "Личный телефон" in dashboard.get_data(as_text=True)
    csrf = extract_csrf(dashboard)
    preview = client.get("/clients/phone/artifacts")
    assert preview.status_code == 200
    preview_payload = preview.get_json()
    assert [variant["id"] for variant in preview_payload["variants"]] == ["plain", "encrypted"]
    assert preview_payload["variants"][1]["text"] == "vpn://ENCRYPTED"
    assert client.get("/clients/unsafe%20name/artifacts").status_code == 404
    assert client.post("/clients", data={"name": "unsafe name"}).status_code == 400
    response = client.post("/clients", data={"name": "tablet_1", "duration": "7d", "csrf_token": csrf}, follow_redirects=True)
    assert response.status_code == 200
    assert fake_awg.created == ["tablet_1"]
    assert fake_awg.durations == ["7d"]
    regenerated = client.post(
        "/clients/regenerate", data={"public_key": "PUBLIC", "csrf_token": csrf}, follow_redirects=True,
    )
    assert regenerated.status_code == 200
    assert fake_awg.regenerated == ["PUBLIC"]
    details = client.post(
        "/clients/details",
        data={"public_key": "PUBLIC", "notes": "Основной телефон", "tags": "личный, Москва, личный", "csrf_token": csrf},
        follow_redirects=True,
    )
    assert details.status_code == 200
    assert repository.get_client("PUBLIC")["notes"] == "Основной телефон"
    assert repository.get_client("PUBLIC")["tags"] == "личный, Москва"
    invalid_details = client.post(
        "/clients/details",
        data={"public_key": "PUBLIC", "notes": "Не сохранять", "tags": "<script>", "csrf_token": csrf},
        follow_redirects=True,
    )
    assert invalid_details.status_code == 200
    assert "Метки могут содержать" in invalid_details.get_data(as_text=True)
    assert repository.get_client("PUBLIC")["notes"] == "Основной телефон"
    backup = client.get("/backup")
    assert backup.status_code == 200
    assert backup.mimetype == "application/zip"
    audit = client.get("/audit")
    assert audit.status_code == 200
    assert "Время (МСК)" in audit.get_data(as_text=True)
    assert " МСК" in audit.get_data(as_text=True)
    assert "Изменение описания" in audit.get_data(as_text=True)
    assert "Перегенерация конфигурации" in audit.get_data(as_text=True)
    assert 'id="audit-action"' in audit.get_data(as_text=True)
    logout = client.post("/logout", data={"csrf_token": csrf})
    assert logout.status_code == 302
    assert client.get("/").status_code == 302
