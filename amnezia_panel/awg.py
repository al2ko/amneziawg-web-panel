# region MODULE_CONTRACT [DOMAIN(10): AmneziaWG; CONCEPT(10): PeerLifecycle; TECH(9): SafeSubprocess]
## @modulecontract
## @purpose Объединить существующую конфигурацию awg0, runtime-статистику и безопасные операции жизненного цикла пиров.
## @scope Config parsing/preservation, migration, keys, IP allocation, runtime apply, backups.
## @input awg0.conf, /root/awg artifacts, fixed executable paths, validated client names, optional add helper.
## @output Dashboard snapshots and durable peer mutations.
## @links CALLS(CommandRunner); READS_DATA_FROM(awg0.conf, awg show dump)
## @invariants shell=False always; unknown interface/peer fields survive; production creation delegates to the canonical script.
## @rationale A narrow root helper reuses manage_amneziawg.sh so config markers and all four client artifacts remain compatible.
## @changes LAST_CHANGE: v1.1.0 delegates production creation to a JSON add helper and recognizes #_Name markers.
## @modulemap CLASS 10[System command boundary] => CommandRunner; CLASS 10[Peer orchestration] => AwgService
def _module_contract():
    pass
# endregion MODULE_CONTRACT
# GREP_SUMMARY: AmneziaWG, awg0.conf, manage helper, JSON, vpnuri, peer parser, create disable enable delete
# STRUCTURE: ▶ config ⊕ runtime ⊕ SQLite → dashboard; create → sudo helper → manage script → four artifacts → metadata

# BUG_FIX_CONTEXT: Future-import после semantic contract ломал collection всех тестов; Python 3.11+ позволяет безопасно удалить его.
import ipaddress
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

from .artifacts import ArtifactService, validate_client_name
from .config import Settings
from .models import Dashboard, PeerView, SystemMetrics
from .repository import PanelRepository

logger = logging.getLogger(__name__)


class CommandError(RuntimeError):
    pass


class CommandRunner:
    ALLOWED_BASENAMES = {"awg", "awg-quick", "systemctl", "uptime", "sudo"}

    def run(self, argv: Sequence[str], input_text: str | None = None) -> str:
        """▶ fixed argv → allowlist → shell-free process → stdout or sanitized error."""
        if not argv or Path(argv[0]).name not in self.ALLOWED_BASENAMES:
            raise CommandError("Executable is not allowed")
        try:
            result = subprocess.run(
                list(argv), input=input_text, text=True, capture_output=True,
                check=True, timeout=15, shell=False,
            )
        except (subprocess.SubprocessError, OSError) as error:
            logger.error("[IMP:10][CommandRunner.run][FAILED] System command failed: %s", Path(argv[0]).name)
            raise CommandError(f"Command failed: {Path(argv[0]).name}") from error
        return result.stdout.strip()


def _section_blocks(text: str, section: str) -> list[str]:
    """▶ INI-like text → exact repeated section spans → blocks."""
    pattern = re.compile(rf"(?ms)^\[{re.escape(section)}\][ \t]*\r?\n.*?(?=^\[[^\]]+\][ \t]*\r?\n|\Z)")
    # BUG_FIX_CONTEXT: Нормализация завершающих переводов строк мешала удалить не последний repeated [Peer] точным replace.
    return [match.group(0) for match in pattern.finditer(text)]


def _value(block: str, key: str) -> str:
    match = re.search(rf"(?mi)^\s*{re.escape(key)}\s*=\s*(.*?)\s*$", block)
    return match.group(1) if match else ""


def _peer_name(block: str, fallback: str) -> str:
    # BUG_FIX_CONTEXT: manage_amneziawg.sh uses '#_Name = value'; the old parser only understood panel-specific comments.
    match = re.search(r"(?mi)^\s*(?:#\s*(?:client|name)\s*:\s*|#_Name\s*=\s*)([A-Za-z0-9_-]{1,64})\s*$", block)
    return match.group(1) if match else fallback


def _replace_peer_name(block: str, new_name: str) -> str:
    """▶ legacy/script marker + new name → same marker style with replaced value."""
    return re.sub(
        r"(?mi)^(\s*(?:#\s*(?:client|name)\s*:\s*|#_Name\s*=\s*))[A-Za-z0-9_-]{1,64}\s*$",
        rf"\g<1>{new_name}", block, count=1,
    )


def parse_runtime_dump(text: str) -> dict[str, dict]:
    """▶ awg show dump TSV → public-key keyed runtime fields."""
    runtime: dict[str, dict] = {}
    lines = [line for line in text.splitlines() if line.strip()]
    for line in lines[1:]:
        fields = line.split("\t")
        if len(fields) < 8:
            continue
        try:
            runtime[fields[0]] = {
                "endpoint": fields[2] if fields[2] != "(none)" else "",
                "latest_handshake": int(fields[4]),
                "received_bytes": int(fields[5]),
                "sent_bytes": int(fields[6]),
            }
        except ValueError:
            continue
    return runtime


class AwgService:
    ACTIVE_WINDOW = 180

    def __init__(self, settings: Settings, repository: PanelRepository, runner: CommandRunner, artifacts: ArtifactService):
        self.settings = settings
        self.repository = repository
        self.runner = runner
        self.artifacts = artifacts

    def _read_config(self) -> str:
        return self.settings.config_path.read_text(encoding="utf-8")

    def _write_config(self, content: str) -> Path:
        """▶ content → timestamp backup → fsync temporary → atomic replace."""
        path = self.settings.config_path
        backup = path.with_name(f"{path.name}.bak-{int(time.time() * 1000)}")
        shutil.copy2(path, backup)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(content.rstrip() + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, path.stat().st_mode & 0o777)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return backup

    def _remove_peer(self, content: str, public_key: str) -> tuple[str, str]:
        for block in _section_blocks(content, "Peer"):
            if _value(block, "PublicKey") == public_key:
                return content.replace(block, "", 1).rstrip() + "\n", block
        raise KeyError("Клиент не найден в конфигурации")

    def _apply_peer(self, public_key: str, allowed_ip: str, preshared_key: str = "") -> None:
        argv = [self.settings.awg_binary, "set", self.settings.interface, "peer", public_key]
        temporary = None
        try:
            if preshared_key:
                descriptor, temporary = tempfile.mkstemp(prefix="amnezia-psk-")
                with os.fdopen(descriptor, "w", encoding="ascii") as stream:
                    stream.write(preshared_key + "\n")
                os.chmod(temporary, 0o600)
                argv.extend(["preshared-key", temporary])
            argv.extend(["allowed-ips", allowed_ip])
            self.runner.run(argv)
        finally:
            if temporary:
                Path(temporary).unlink(missing_ok=True)

    def migrate_existing(self) -> None:
        """▶ canonical peers + existing client files by IP → non-destructive metadata/QR import."""
        content = self._read_config()
        known = self.repository.get_clients()
        artifacts_by_ip: dict[str, str] = {}
        if self.settings.clients_dir.is_dir():
            for path in self.settings.clients_dir.glob("*.conf"):
                try:
                    name = validate_client_name(path.stem)
                    client_text = path.read_text(encoding="utf-8")
                    interface = _section_blocks(client_text, "Interface")
                    client_ip = _value(interface[0], "Address").split(",", 1)[0].split("/", 1)[0].strip() if interface else ""
                    if client_ip:
                        artifacts_by_ip[client_ip] = name
                except (OSError, UnicodeError, ValueError):
                    logger.warning("[IMP:8][migrate_existing][SKIP_ARTIFACT] Unreadable or unsafe client artifact ignored")
        for index, block in enumerate(_section_blocks(content, "Peer"), start=1):
            public_key = _value(block, "PublicKey")
            tunnel_ip = _value(block, "AllowedIPs").split(",", 1)[0].strip().split("/", 1)[0]
            if public_key and public_key not in known:
                name = artifacts_by_ip.get(tunnel_ip) or _peer_name(block, f"client-{index}")
                self.repository.upsert_client(public_key, name, tunnel_ip, True, block)
                if tunnel_ip in artifacts_by_ip:
                    self.artifacts.ensure_qr(name)
        logger.info("[IMP:9][migrate_existing][COMPLETE] Canonical peer metadata synchronized")

    def dashboard(self) -> Dashboard:
        """▶ config + runtime + metadata → status-classified dashboard."""
        self.migrate_existing()
        content = self._read_config()
        metadata = self.repository.get_clients()
        try:
            runtime = parse_runtime_dump(self.runner.run([self.settings.awg_binary, "show", self.settings.interface, "dump"]))
            service_active = True
        except CommandError:
            runtime, service_active = {}, False
        now = int(time.time())
        peers: list[PeerView] = []
        active_keys: set[str] = set()
        for index, block in enumerate(_section_blocks(content, "Peer"), start=1):
            public_key = _value(block, "PublicKey")
            if not public_key:
                continue
            active_keys.add(public_key)
            record = metadata.get(public_key, {})
            stats = runtime.get(public_key, {})
            handshake = int(stats.get("latest_handshake", 0))
            status = "active" if handshake and now - handshake <= self.ACTIVE_WINDOW else "offline" if handshake else "never"
            peers.append(PeerView(
                name=record.get("name") or _peer_name(block, f"client-{index}"), public_key=public_key,
                tunnel_ip=record.get("tunnel_ip") or _value(block, "AllowedIPs").split("/", 1)[0],
                endpoint=stats.get("endpoint", ""), latest_handshake=handshake,
                received_bytes=int(stats.get("received_bytes", 0)), sent_bytes=int(stats.get("sent_bytes", 0)),
                status=status, enabled=True, notes=record.get("notes", ""), tags=record.get("tags", ""),
            ))
        for public_key, record in metadata.items():
            if public_key not in active_keys and not record["enabled"]:
                peers.append(PeerView(
                    record["name"], public_key, record["tunnel_ip"], status="disabled", enabled=False,
                    notes=record.get("notes", ""), tags=record.get("tags", ""),
                ))
        try:
            server_uptime = self.runner.run(["uptime", "-p"])
        except CommandError:
            server_uptime = "недоступно"
        try:
            interface_uptime = self.runner.run([
                "systemctl", "show", f"awg-quick@{self.settings.interface}.service",
                "--property=ActiveEnterTimestamp", "--value",
            ]) or "активен"
        except CommandError:
            interface_uptime = "недоступно"
        logger.info("[IMP:9][dashboard][SNAPSHOT] Built snapshot with %d peers", len(peers))
        return Dashboard(
            service_active, server_uptime, interface_uptime if service_active else "остановлен",
            peers, self._system_metrics(),
        )

    def _system_metrics(self) -> SystemMetrics:
        """▶ Linux host state + awg version → display-safe system snapshot."""
        metrics = SystemMetrics(cpu_count=os.cpu_count() or 0)
        try:
            metrics.load_1, metrics.load_5, metrics.load_15 = os.getloadavg()
        except (AttributeError, OSError):
            pass
        try:
            memory = {}
            for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
                key, value = line.split(":", 1)
                memory[key] = int(value.strip().split()[0]) * 1024
            metrics.memory_total = memory.get("MemTotal", 0)
            metrics.memory_used = max(0, metrics.memory_total - memory.get("MemAvailable", 0))
        except (OSError, ValueError, IndexError):
            pass
        try:
            disk = shutil.disk_usage("/")
            metrics.disk_used, metrics.disk_total = disk.used, disk.total
        except OSError:
            pass
        try:
            metrics.awg_version = self.runner.run([self.settings.awg_binary, "--version"]) or "недоступно"
        except CommandError:
            pass
        return metrics

    def _allocate_ip(self, content: str) -> str:
        interface_blocks = _section_blocks(content, "Interface")
        address = _value(interface_blocks[0], "Address").split(",", 1)[0].strip() if interface_blocks else ""
        if not address:
            raise ValueError("В [Interface] отсутствует Address")
        network = ipaddress.ip_interface(address).network
        used = {ipaddress.ip_address(_value(block, "AllowedIPs").split(",", 1)[0].split("/", 1)[0].strip()) for block in _section_blocks(content, "Peer")}
        server_ip = ipaddress.ip_interface(address).ip
        for candidate in network.hosts():
            if candidate != server_ip and candidate not in used:
                return str(candidate)
        raise RuntimeError("В адресном пространстве нет свободных IP")

    def create_peer(self, name: str) -> dict:
        """▶ valid unique name → canonical helper or native dev fallback → artifacts+metadata."""
        name = validate_client_name(name)
        if self.repository.find_by_name(name) or any(path.exists() for path in self.artifacts.all_paths(name).values()):
            raise ValueError("Клиент с таким именем уже существует")
        if self.settings.manage_add_helper is not None:
            return self._create_peer_via_helper(name)
        return self._create_peer_native(name)

    def _create_peer_via_helper(self, name: str) -> dict:
        """▶ validated name → fixed sudo helper argv → verified JSON/config/artifacts → metadata."""
        if len(name) > 63:
            raise ValueError("Скрипт AmneziaWG поддерживает имя длиной не более 63 символов")
        helper = str(self.settings.manage_add_helper)
        output = self.runner.run(["sudo", "-n", helper, name])
        try:
            payload = json.loads(output)
        except (json.JSONDecodeError, TypeError) as error:
            logger.error("[IMP:10][_create_peer_via_helper][INVALID_JSON] Add helper returned an invalid response")
            raise CommandError("Add helper returned invalid JSON") from error
        results = payload.get("results") if isinstance(payload, dict) else None
        matching = next(
            (item for item in results if isinstance(item, dict) and item.get("name") == name),
            None,
        ) if isinstance(results, list) else None
        if not isinstance(payload, dict) or payload.get("ok") is not True or not matching or matching.get("status") != "created":
            logger.error("[IMP:10][_create_peer_via_helper][REJECTED] Canonical script did not confirm client creation")
            raise CommandError("Canonical client creation was not confirmed")

        content = self._read_config()
        peer_block = next((block for block in _section_blocks(content, "Peer") if _peer_name(block, "") == name), "")
        public_key = _value(peer_block, "PublicKey")
        tunnel_ip = _value(peer_block, "AllowedIPs").split(",", 1)[0].split("/", 1)[0].strip()
        missing = [kind for kind, path in self.artifacts.all_paths(name).items() if not path.is_file()]
        if not peer_block or not public_key or not tunnel_ip or missing:
            # BUG_FIX_CONTEXT: A successful script exit alone does not guarantee best-effort QR/vpnuri files exist.
            logger.error(
                "[IMP:10][_create_peer_via_helper][INCOMPLETE] Canonical result is incomplete; missing artifact count=%d",
                len(missing),
            )
            raise CommandError("Canonical client creation produced an incomplete result")
        self.repository.upsert_client(public_key, name, tunnel_ip, True, peer_block)
        logger.info("[IMP:9][create_peer][SUCCESS] Client %s created by canonical script at %s", name, tunnel_ip)
        return {"name": name, "public_key": public_key, "tunnel_ip": tunnel_ip}

    def _create_peer_native(self, name: str) -> dict:
        """▶ development fallback → keys+IP → backup/config/runtime → plain artifacts+metadata."""
        if not self.settings.endpoint:
            raise ValueError("Не настроен AMNEZIA_PANEL_ENDPOINT")
        content = self._read_config()
        tunnel_ip = self._allocate_ip(content)
        private_key = self.runner.run([self.settings.awg_binary, "genkey"])
        public_key = self.runner.run([self.settings.awg_binary, "pubkey"], private_key + "\n")
        preshared_key = self.runner.run([self.settings.awg_binary, "genpsk"])
        server_public_key = self.runner.run([self.settings.awg_binary, "show", self.settings.interface, "public-key"])
        peer_block = f"[Peer]\n# client: {name}\nPublicKey = {public_key}\nPresharedKey = {preshared_key}\nAllowedIPs = {tunnel_ip}/32\n"
        new_content = content.rstrip() + "\n\n" + peer_block
        backup = self._write_config(new_content)
        try:
            self._apply_peer(public_key, f"{tunnel_ip}/32", preshared_key)
            client_config = self._client_config(content, private_key, tunnel_ip, server_public_key, preshared_key)
            self.artifacts.create(name, client_config)
            self.repository.upsert_client(public_key, name, tunnel_ip, True, peer_block)
        except Exception:
            shutil.copy2(backup, self.settings.config_path)
            try:
                self.runner.run([self.settings.awg_binary, "set", self.settings.interface, "peer", public_key, "remove"])
            except CommandError:
                pass
            raise
        logger.info("[IMP:9][create_peer][SUCCESS] Client %s created at %s", name, tunnel_ip)
        return {"name": name, "public_key": public_key, "tunnel_ip": tunnel_ip}

    def _client_config(self, server_config: str, private_key: str, tunnel_ip: str, server_key: str, psk: str) -> str:
        interface = _section_blocks(server_config, "Interface")[0]
        awg_keys = ("Jc", "Jmin", "Jmax", "S1", "S2", "H1", "H2", "H3", "H4")
        extra = "".join(f"{key} = {_value(interface, key)}\n" for key in awg_keys if _value(interface, key))
        return (
            f"[Interface]\nPrivateKey = {private_key}\nAddress = {tunnel_ip}/32\nDNS = {self.settings.dns}\n{extra}\n"
            f"[Peer]\nPublicKey = {server_key}\nPresharedKey = {psk}\nAllowedIPs = 0.0.0.0/0, ::/0\n"
            f"Endpoint = {self.settings.endpoint}\nPersistentKeepalive = 25\n"
        )

    def rename_peer(self, public_key: str, new_name: str) -> None:
        new_name = validate_client_name(new_name)
        record = self.repository.get_client(public_key)
        if not record:
            raise KeyError("Клиент не найден")
        existing = self.repository.find_by_name(new_name)
        if existing and existing["public_key"] != public_key:
            raise ValueError("Имя уже используется")
        block = record["peer_block"]
        renamed_block = _replace_peer_name(block, new_name)
        if renamed_block == block:
            renamed_block = block.replace("[Peer]", f"[Peer]\n#_Name = {new_name}", 1)
        self.artifacts.rename(record["name"], new_name)
        try:
            if record["enabled"]:
                content = self._read_config()
                live_content, live_block = self._remove_peer(content, public_key)
                renamed_live = live_block.replace(block.strip(), renamed_block.strip()) if block.strip() in live_block else _replace_peer_name(live_block, new_name)
                if renamed_live == live_block:
                    renamed_live = live_block.replace("[Peer]", f"[Peer]\n#_Name = {new_name}", 1)
                self._write_config(live_content.rstrip() + "\n\n" + renamed_live.lstrip())
                renamed_block = renamed_live
            self.repository.rename_client(public_key, new_name, renamed_block)
        except Exception:
            self.artifacts.rename(new_name, record["name"])
            raise
        logger.info("[IMP:9][rename_peer][SUCCESS] Client metadata renamed to %s", new_name)

    def disable_peer(self, public_key: str) -> None:
        content = self._read_config()
        new_content, block = self._remove_peer(content, public_key)
        backup = self._write_config(new_content)
        try:
            self.runner.run([self.settings.awg_binary, "set", self.settings.interface, "peer", public_key, "remove"])
        except Exception:
            shutil.copy2(backup, self.settings.config_path)
            raise
        self.repository.set_enabled(public_key, False, block)
        logger.info("[IMP:9][disable_peer][SUCCESS] Client access suspended")

    def enable_peer(self, public_key: str) -> None:
        record = self.repository.get_client(public_key)
        if not record or record["enabled"] or not record["peer_block"]:
            raise ValueError("Отключённый клиент не найден")
        content = self._read_config()
        if any(_value(block, "PublicKey") == public_key for block in _section_blocks(content, "Peer")):
            raise ValueError("Клиент уже присутствует в конфигурации")
        backup = self._write_config(content.rstrip() + "\n\n" + record["peer_block"].rstrip() + "\n")
        psk = _value(record["peer_block"], "PresharedKey")
        allowed = _value(record["peer_block"], "AllowedIPs")
        try:
            self._apply_peer(public_key, allowed, psk)
        except Exception:
            shutil.copy2(backup, self.settings.config_path)
            raise
        self.repository.set_enabled(public_key, True)
        logger.info("[IMP:9][enable_peer][SUCCESS] Client access restored")

    def delete_peer(self, public_key: str) -> None:
        record = self.repository.get_client(public_key)
        if not record:
            raise KeyError("Клиент не найден")
        content = self._read_config()
        if record["enabled"]:
            content, _ = self._remove_peer(content, public_key)
            backup = self._write_config(content)
            try:
                self.runner.run([self.settings.awg_binary, "set", self.settings.interface, "peer", public_key, "remove"])
            except Exception:
                shutil.copy2(backup, self.settings.config_path)
                raise
        self.artifacts.delete(record["name"])
        self.repository.delete_client(public_key)
        logger.info("[IMP:9][delete_peer][SUCCESS] Client removed")

    def restart_interface(self) -> None:
        self.runner.run(["sudo", "-n", "systemctl", "restart", f"awg-quick@{self.settings.interface}.service"])
        logger.warning("[IMP:9][restart_interface][SUCCESS] Interface service restarted")

    def export_snapshot(self) -> list[dict]:
        """▶ dashboard → secret-free serializable peer records."""
        return [asdict(peer) for peer in self.dashboard().peers]
