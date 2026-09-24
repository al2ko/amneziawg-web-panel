# region MODULE_CONTRACT [DOMAIN(9): VPN; CONCEPT(9): DataTransferObjects; TECH(8): Dataclass]
## @modulecontract
## @purpose Определить типизированные данные клиентов и состояния сервера между слоями.
## @scope Peer metadata, runtime statistics, dashboard snapshot.
## @input Parsed configuration and awg dump values.
## @output Immutable domain records.
## @invariants Private keys never belong to dashboard PeerView.
## @changes LAST_CHANGE: v1.0.0 initial domain records.
## @modulemap CLASS 9[Safe client view] => PeerView; CLASS 8[Dashboard aggregate] => Dashboard
def _module_contract():
    pass
# endregion MODULE_CONTRACT
# GREP_SUMMARY: peer DTO, dashboard, traffic, handshake, VPN status
# STRUCTURE: ▶ config + runtime + metadata → PeerView[] → Dashboard

from dataclasses import dataclass, field


@dataclass(slots=True)
class PeerView:
    name: str
    public_key: str
    tunnel_ip: str
    endpoint: str = ""
    latest_handshake: int = 0
    received_bytes: int = 0
    sent_bytes: int = 0
    status: str = "never"
    enabled: bool = True
    notes: str = ""
    tags: str = ""
    expires_at: int | None = None


@dataclass(slots=True)
class SystemMetrics:
    cpu_count: int = 0
    load_1: float = 0.0
    load_5: float = 0.0
    load_15: float = 0.0
    memory_used: int = 0
    memory_total: int = 0
    disk_used: int = 0
    disk_total: int = 0
    awg_version: str = "недоступно"

    @property
    def memory_percent(self) -> int:
        return round(self.memory_used * 100 / self.memory_total) if self.memory_total else 0

    @property
    def disk_percent(self) -> int:
        return round(self.disk_used * 100 / self.disk_total) if self.disk_total else 0


@dataclass(slots=True)
class Dashboard:
    service_active: bool
    server_uptime: str
    interface_uptime: str
    peers: list[PeerView] = field(default_factory=list)
    system: SystemMetrics = field(default_factory=SystemMetrics)

    @property
    def active_count(self) -> int:
        return sum(peer.status == "active" for peer in self.peers)

    @property
    def received_bytes(self) -> int:
        return sum(peer.received_bytes for peer in self.peers)

    @property
    def sent_bytes(self) -> int:
        return sum(peer.sent_bytes for peer in self.peers)
