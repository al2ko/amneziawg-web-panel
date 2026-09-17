# region MODULE_CONTRACT [DOMAIN(9): VPN; CONCEPT(9): ClientArtifacts; TECH(8): QRCode]
## @modulecontract
## @purpose Создавать и выдавать закрытые клиентские конфигурации и мобильные QR-коды вне web-root.
## @scope Atomic configuration storage, QR rendering, plain/encrypted preview, safe rename/delete/path lookup.
## @input Validated client name and complete configuration text.
## @output Mode-0600 .conf/.png and discovered .vpnuri/.vpnuri.png artifacts.
## @invariants Artifact names and kinds pass fixed allowlists before path construction; previews are size limited.
## @changes LAST_CHANGE: v1.1.0 adds plain and encrypted artifact variants.
## @modulemap CLASS 9[Secure artifact lifecycle] => ArtifactService
def _module_contract():
    pass
# endregion MODULE_CONTRACT
# GREP_SUMMARY: client config, QR PNG, vpnuri, encrypted config, preview, secure file, atomic write, download
# STRUCTURE: ▶ validated name → fixed suffix map {.conf,.png,.vpnuri,.vpnuri.png} → preview/download/rename/delete

# BUG_FIX_CONTEXT: Future-import не может следовать за contract-функцией; поддерживаемая версия Python делает его избыточным.
import os
import re
import tempfile
from pathlib import Path

import qrcode

NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def validate_client_name(name: str) -> str:
    """▶ raw name → full regex match → safe filename segment."""
    name = name.strip()
    if not NAME_PATTERN.fullmatch(name):
        raise ValueError("Имя: 1–64 символа, только буквы, цифры, дефис и подчёркивание")
    return name


class ArtifactService:
    MAX_PREVIEW_BYTES = 512 * 1024
    KIND_SUFFIXES = {"conf": ".conf", "qr": ".png", "vpnuri": ".vpnuri", "vpnuri_qr": ".vpnuri.png"}

    def __init__(self, clients_dir: Path):
        self.clients_dir = Path(clients_dir)

    def create(self, name: str, configuration: str) -> tuple[Path, Path]:
        """▶ config text → atomic 0600 .conf + QR → paths."""
        name = validate_client_name(name)
        self.clients_dir.mkdir(parents=True, exist_ok=True)
        conf_path, qr_path = self.paths(name)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{name}.", dir=self.clients_dir, text=True)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(configuration)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, conf_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        image = qrcode.make(configuration)
        image.save(qr_path)
        os.chmod(qr_path, 0o600)
        return conf_path, qr_path

    def paths(self, name: str) -> tuple[Path, Path]:
        name = validate_client_name(name)
        return self.clients_dir / f"{name}.conf", self.clients_dir / f"{name}.png"

    def all_paths(self, name: str) -> dict[str, Path]:
        """▶ validated name × fixed suffix allowlist → four canonical artifact paths."""
        name = validate_client_name(name)
        return {kind: self.clients_dir / f"{name}{suffix}" for kind, suffix in self.KIND_SUFFIXES.items()}

    def get(self, name: str, kind: str) -> Path:
        path = self.all_paths(name).get(kind)
        if path is None or not path.is_file():
            raise FileNotFoundError(name)
        return path

    def variants(self, name: str) -> list[dict]:
        """▶ client → plain/encrypted pairs → bounded text preview metadata."""
        paths = self.all_paths(name)
        specifications = (("plain", "Без шифрования", "conf", "qr"), ("encrypted", "С шифрованием", "vpnuri", "vpnuri_qr"))
        result: list[dict] = []
        for variant_id, label, config_kind, qr_kind in specifications:
            config_path, qr_path = paths[config_kind], paths[qr_kind]
            available = config_path.is_file()
            if available and config_path.stat().st_size > self.MAX_PREVIEW_BYTES:
                raise ValueError("Файл конфигурации слишком большой для предпросмотра")
            result.append({
                "id": variant_id, "label": label, "available": available,
                "text": config_path.read_text(encoding="utf-8") if available else "",
                "config_kind": config_kind, "qr_kind": qr_kind, "qr_available": qr_path.is_file(),
            })
        return result

    def ensure_qr(self, name: str) -> Path:
        """▶ existing .conf → missing QR only; original configuration remains byte-identical."""
        conf_path, qr_path = self.paths(name)
        if not conf_path.is_file():
            raise FileNotFoundError(name)
        if not qr_path.is_file():
            image = qrcode.make(conf_path.read_text(encoding="utf-8"))
            image.save(qr_path)
            os.chmod(qr_path, 0o600)
        return qr_path

    def rename(self, old_name: str, new_name: str) -> None:
        old_paths, new_paths = self.all_paths(old_name), self.all_paths(new_name)
        if any(path.exists() for path in new_paths.values()):
            raise FileExistsError(new_name)
        for kind, old_path in old_paths.items():
            new_path = new_paths[kind]
            if old_path.exists():
                old_path.replace(new_path)

    def delete(self, name: str) -> None:
        for path in self.all_paths(name).values():
            try:
                path.unlink()
            except FileNotFoundError:
                continue
