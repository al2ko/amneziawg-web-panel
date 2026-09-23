# region MODULE_CONTRACT [DOMAIN(10): Testing; CONCEPT(10): PeerLifecycle; TECH(9): pytest]
## @modulecontract
## @purpose Доказать сохранность awg-конфига, script-compatible создание и полный жизненный цикл клиента без системных команд.
## @scope Parser, migration, helper/native create, four artifacts, disable, enable, delete.
## @input Temporary config/database/artifact directory and deterministic runner.
## @output Assertions plus IMP:7-10 trace.
## @invariants Tests import backend directly and never call subprocess.
## @changes LAST_CHANGE: v1.1.0 adds canonical helper and #_Name regression coverage.
## @modulemap FUNC 10[Full lifecycle] => test_peer_lifecycle; FUNC 10[Canonical helper] => test_create_peer_via_canonical_helper
def _module_contract():
    pass
# endregion MODULE_CONTRACT
# GREP_SUMMARY: pytest, AmneziaWG, peer lifecycle, safe command args, config preservation
# STRUCTURE: ▶ tmp config + fake runner → create ⇄ disable/enable → delete → verify config/artifacts/logs

import logging
import time
from dataclasses import replace
from pathlib import Path

from amnezia_panel.artifacts import ArtifactService
from amnezia_panel.awg import AwgService, parse_runtime_dump
from amnezia_panel.config import Settings
from amnezia_panel.repository import PanelRepository

SERVER_CONFIG = """[Interface]
PrivateKey = SERVER_PRIVATE_SECRET
Address = 10.8.1.1/24
ListenPort = 51820
Jc = 4
Jmin = 40
Jmax = 70
S1 = 90
S2 = 100
H1 = 1001
H2 = 1002
H3 = 1003
H4 = 1004

[Peer]
# client: legacy
PublicKey = LEGACY_PUBLIC
AllowedIPs = 10.8.1.2/32
UnknownOption = preserved
"""


class FakeRunner:
    def __init__(self):
        self.calls = []
        self.dump = "private\tserverpub\t51820\toff\nLEGACY_PUBLIC\t(none)\t198.51.100.1:1234\t10.8.1.2/32\t{}\t1024\t2048\t25".format(int(time.time()))

    def run(self, argv, input_text=None):
        self.calls.append((list(argv), input_text))
        if argv[1:] == ["genkey"]:
            return "CLIENT_PRIVATE"
        if argv[1:] == ["pubkey"]:
            return "CLIENT_PUBLIC"
        if argv[1:] == ["genpsk"]:
            return "PRESHARED_SECRET"
        if argv[-2:] == ["awg0", "public-key"]:
            return "SERVER_PUBLIC"
        if argv[-3:] == ["awg0", "dump"] or argv[1:] == ["show", "awg0", "dump"]:
            return self.dump
        if argv[0] == "uptime":
            return "up 2 days"
        return ""


class FakeAddHelperRunner:
    def __init__(self, config_path: Path, clients_dir: Path):
        self.config_path = config_path
        self.clients_dir = clients_dir
        self.calls = []

    def run(self, argv, input_text=None):
        self.calls.append((list(argv), input_text))
        name = argv[-1]
        peer = f"[Peer]\n#_Name = {name}\nPublicKey = SCRIPT_PUBLIC\nPresharedKey = SCRIPT_PSK\nAllowedIPs = 10.8.1.3/32\n"
        self.config_path.write_text(self.config_path.read_text(encoding="utf-8").rstrip() + "\n\n" + peer, encoding="utf-8")
        self.clients_dir.mkdir(parents=True, exist_ok=True)
        (self.clients_dir / f"{name}.conf").write_text("[Interface]\nPrivateKey = SCRIPT_PRIVATE\n", encoding="utf-8")
        (self.clients_dir / f"{name}.png").write_bytes(b"plain-qr")
        (self.clients_dir / f"{name}.vpnuri").write_text("vpn://SCRIPT_PAYLOAD", encoding="utf-8")
        (self.clients_dir / f"{name}.vpnuri.png").write_bytes(b"vpnuri-qr")
        return (
            '{"command":"add","ok":true,"added":1,"failed":0,"applied":true,'
            f'"results":[{{"name":"{name}","status":"created"}}]}}'
        )


class FakeRegenHelperRunner:
    def __init__(self):
        self.calls = []

    def run(self, argv, input_text=None):
        self.calls.append((list(argv), input_text))
        name = argv[-1]
        return (
            '{"command":"regen","ok":true,"regenerated":1,"failed":0,"reset_routes":false,'
            f'"results":[{{"name":"{name}","status":"regenerated"}}]}}'
        )


def build_service(tmp_path: Path):
    config_path = tmp_path / "awg0.conf"
    config_path.write_text(SERVER_CONFIG, encoding="utf-8")
    settings = Settings(
        secret_key="x" * 32, admin_username="admin", password_hash="unused",
        database_path=tmp_path / "panel.db", config_path=config_path,
        clients_dir=tmp_path / "clients", endpoint="vpn.example:51820",
    )
    repository = PanelRepository(settings.database_path)
    repository.initialize()
    runner = FakeRunner()
    return AwgService(settings, repository, runner, ArtifactService(settings.clients_dir)), repository, runner


def print_critical_logs(caplog):
    lines = [record.message for record in caplog.records if any(f"[IMP:{level}]" in record.message for level in range(7, 11))]
    print("\n--- LDD TRAJECTORY (IMP:7-10) ---")
    for line in lines:
        print(line)
    return lines


def test_parse_runtime_dump():
    dump = "private\tpub\t51820\toff\nkey\tpsk\thost:1\t10.0.0.2/32\t123\t44\t55\t25"
    assert parse_runtime_dump(dump)["key"] == {"endpoint": "host:1", "latest_handshake": 123, "received_bytes": 44, "sent_bytes": 55}


def test_dashboard_merge(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    service, repository, _ = build_service(tmp_path)
    dashboard = service.dashboard()
    trace = print_critical_logs(caplog)
    assert dashboard.service_active
    assert dashboard.active_count == 1
    assert dashboard.peers[0].name == "legacy"
    assert dashboard.peers[0].endpoint == "198.51.100.1:1234"
    assert dashboard.system.cpu_count >= 1
    assert dashboard.system.disk_total >= dashboard.system.disk_used
    assert repository.get_client("LEGACY_PUBLIC") is not None
    assert any("[IMP:9][dashboard][SNAPSHOT]" in line for line in trace)


def test_peer_lifecycle_preserves_unknown_config(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    service, repository, runner = build_service(tmp_path)
    service.migrate_existing()
    created = service.create_peer("tablet_1")
    assert created["tunnel_ip"] == "10.8.1.3"
    assert "UnknownOption = preserved" in service.settings.config_path.read_text(encoding="utf-8")
    assert "Jc = 4" in (service.settings.clients_dir / "tablet_1.conf").read_text(encoding="utf-8")
    assert (service.settings.clients_dir / "tablet_1.png").is_file()
    assert all(isinstance(call[0], list) for call in runner.calls)

    (service.settings.clients_dir / "tablet_1.vpnuri").write_text("vpn://ENCRYPTED_PAYLOAD", encoding="utf-8")
    (service.settings.clients_dir / "tablet_1.vpnuri.png").write_bytes(b"encrypted-qr")
    variants = service.artifacts.variants("tablet_1")
    assert [variant["available"] for variant in variants] == [True, True]
    assert variants[1]["text"] == "vpn://ENCRYPTED_PAYLOAD"

    service.rename_peer("CLIENT_PUBLIC", "tablet_new")
    assert (service.settings.clients_dir / "tablet_new.conf").is_file()
    assert (service.settings.clients_dir / "tablet_new.vpnuri").is_file()
    assert (service.settings.clients_dir / "tablet_new.vpnuri.png").is_file()
    service.disable_peer("CLIENT_PUBLIC")
    assert "CLIENT_PUBLIC" not in service.settings.config_path.read_text(encoding="utf-8")
    assert repository.get_client("CLIENT_PUBLIC")["enabled"] == 0
    service.enable_peer("CLIENT_PUBLIC")
    assert "CLIENT_PUBLIC" in service.settings.config_path.read_text(encoding="utf-8")
    service.delete_peer("CLIENT_PUBLIC")
    assert repository.get_client("CLIENT_PUBLIC") is None
    assert not (service.settings.clients_dir / "tablet_new.conf").exists()
    assert not (service.settings.clients_dir / "tablet_new.vpnuri").exists()
    assert not (service.settings.clients_dir / "tablet_new.vpnuri.png").exists()
    trace = print_critical_logs(caplog)
    assert any("[IMP:9][create_peer][SUCCESS]" in line for line in trace)
    assert any("[IMP:9][delete_peer][SUCCESS]" in line for line in trace)


def test_create_peer_via_canonical_helper(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    service, repository, _ = build_service(tmp_path)
    service.settings = replace(service.settings, manage_add_helper="/usr/local/sbin/amnezia-panel-add")
    helper_runner = FakeAddHelperRunner(service.settings.config_path, service.settings.clients_dir)
    service.runner = helper_runner

    created = service.create_peer("script_phone")
    assert created == {"name": "script_phone", "public_key": "SCRIPT_PUBLIC", "tunnel_ip": "10.8.1.3"}
    assert helper_runner.calls == [
        (["sudo", "-n", "/usr/local/sbin/amnezia-panel-add", "script_phone"], None),
    ]
    assert all(path.is_file() for path in service.artifacts.all_paths("script_phone").values())
    assert repository.get_client("SCRIPT_PUBLIC")["name"] == "script_phone"

    service.rename_peer("SCRIPT_PUBLIC", "script_phone_new")
    canonical = service.settings.config_path.read_text(encoding="utf-8")
    assert "#_Name = script_phone_new" in canonical
    assert "#_Name = script_phone\n" not in canonical
    trace = print_critical_logs(caplog)
    assert any("created by canonical script" in line for line in trace)


def test_regenerate_peer_via_canonical_helper(tmp_path):
    service, repository, _ = build_service(tmp_path)
    service.migrate_existing()
    service.settings.clients_dir.mkdir()
    for path in service.artifacts.all_paths("legacy").values():
        path.write_bytes(b"regenerated")
    service.settings = replace(service.settings, manage_regen_helper="/usr/local/sbin/amnezia-panel-regen")
    runner = FakeRegenHelperRunner()
    service.runner = runner

    result = service.regenerate_peer("LEGACY_PUBLIC")

    assert result == {"name": "legacy", "public_key": "LEGACY_PUBLIC"}
    assert runner.calls == [(["sudo", "-n", "/usr/local/sbin/amnezia-panel-regen", "legacy"], None)]
    assert repository.get_client("LEGACY_PUBLIC")["enabled"] == 1


def test_middle_peer_removal_and_existing_artifact_discovery(tmp_path):
    service, repository, _ = build_service(tmp_path)
    service.settings.config_path.write_text(
        SERVER_CONFIG.rstrip() + "\n\n[Peer]\n# client: second\nPublicKey = SECOND_PUBLIC\nAllowedIPs = 10.8.1.3/32\n",
        encoding="utf-8",
    )
    service.settings.clients_dir.mkdir()
    (service.settings.clients_dir / "old_phone.conf").write_text(
        "[Interface]\nPrivateKey = EXISTING_SECRET\nAddress = 10.8.1.2/32\n\n[Peer]\nPublicKey = SERVER_PUBLIC\n",
        encoding="utf-8",
    )
    service.migrate_existing()
    assert repository.get_client("LEGACY_PUBLIC")["name"] == "old_phone"
    assert (service.settings.clients_dir / "old_phone.png").is_file()
    service.disable_peer("LEGACY_PUBLIC")
    remaining = service.settings.config_path.read_text(encoding="utf-8")
    assert "LEGACY_PUBLIC" not in remaining
    assert "SECOND_PUBLIC" in remaining
    assert "UnknownOption = preserved" not in remaining


def test_dashboard_handles_one_hundred_peers_under_two_seconds(tmp_path):
    service, _, runner = build_service(tmp_path)
    blocks = []
    runtime_lines = ["private\tserverpub\t51820\toff"]
    now = int(time.time())
    for index in range(2, 102):
        blocks.append(f"[Peer]\n# client: device-{index}\nPublicKey = KEY_{index}\nAllowedIPs = 10.8.1.{index}/32\n")
        runtime_lines.append(f"KEY_{index}\t(none)\t(none)\t10.8.1.{index}/32\t{now}\t1\t2\t25")
    service.settings.config_path.write_text(SERVER_CONFIG.split("[Peer]", 1)[0].rstrip() + "\n\n" + "\n".join(blocks), encoding="utf-8")
    runner.dump = "\n".join(runtime_lines)
    started = time.perf_counter()
    dashboard = service.dashboard()
    elapsed = time.perf_counter() - started
    assert len(dashboard.peers) == 100
    assert dashboard.active_count == 100
    assert elapsed < 2.0
