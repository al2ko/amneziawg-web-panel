# region MODULE_CONTRACT [DOMAIN(10): DeploymentSecurity; CONCEPT(10): PrivilegeBoundary; TECH(9): systemd, sudoers]
## @modulecontract
## @purpose Не допустить повторного разрыва между systemd sandbox и узким privileged helper создания клиента.
## @scope Static production unit, sudoers and helper invariants.
## @input Version-controlled deployment files.
## @output Assertions and an IMP:9 semantic trace.
## @invariants Gunicorn receives only CAP_NET_ADMIN ambient; root transition capabilities remain bounded; helper validates one name.
## @changes LAST_CHANGE: v1.2.0 verifies ACL restoration and recoverable stale-key handling for same-name re-add.
## @modulemap FUNC 10[Privilege boundary regression] => test_add_helper_privilege_boundary
def _module_contract():
    pass
# endregion MODULE_CONTRACT
# GREP_SUMMARY: systemd, CapabilityBoundingSet, AmbientCapabilities, sudo, root helper, deployment security
# STRUCTURE: ▶ service unit ⊕ sudoers ⊕ helper → privilege invariants → IMP:9 verified boundary

from pathlib import Path


# region FUNC_test_add_helper_privilege_boundary [DOMAIN(10): DeploymentSecurity; CONCEPT(10): Regression; TECH(9): pytest]
## @purpose Проверить минимально необходимую возможность sudo-перехода без ambient-выдачи root capabilities веб-процессу.
## @io Repository deployment files -> assertions
## @complexity 4
def test_add_helper_privilege_boundary():
    root = Path(__file__).resolve().parents[1]
    unit = (root / "deploy" / "amnezia-panel.service").read_text(encoding="utf-8")
    sudoers = (root / "deploy" / "amnezia-panel.sudoers").read_text(encoding="utf-8")
    helper = (root / "deploy" / "amnezia-panel-add").read_text(encoding="utf-8")
    regen_helper = (root / "deploy" / "amnezia-panel-regen").read_text(encoding="utf-8")

    assert "AmbientCapabilities=CAP_NET_ADMIN\n" in unit
    assert "Environment=TZ=Europe/Moscow\n" in unit
    bounding_line = next(line for line in unit.splitlines() if line.startswith("CapabilityBoundingSet="))
    required = {"CAP_NET_ADMIN", "CAP_SETUID", "CAP_SETGID", "CAP_DAC_OVERRIDE", "CAP_FOWNER"}
    assert set(bounding_line.split("=", 1)[1].split()) == required
    assert "NOPASSWD: /usr/local/sbin/amnezia-panel-add" in sudoers
    assert "NOPASSWD: /usr/local/sbin/amnezia-panel-regen" in sudoers
    assert '"$#" -ne 1' in helper
    assert "^[A-Za-z0-9_-]{1,63}$" in helper
    assert "/usr/bin/env -i" in helper
    assert "setfacl -m u:amnezia-panel:rw -- /etc/amnezia/amneziawg/awg0.conf" in helper
    assert "for suffix in .conf .png .vpnuri .vpnuri.png" in helper
    assert 'grep -qxF -- "#_Name = ${client_name}"' in helper
    assert "/root/awg/backups/panel-stale" in helper
    assert "/usr/bin/mktemp -d" in helper
    assert "/usr/bin/mv --" in helper
    assert '"$#" -ne 1' in regen_helper
    assert "^[A-Za-z0-9_-]{1,63}$" in regen_helper
    assert "/usr/bin/env -i" in regen_helper
    assert '--json --yes regen "$client_name"' in regen_helper
    assert "for suffix in .conf .png .vpnuri .vpnuri.png" in regen_helper
    print("[IMP:9][test_add_helper_privilege_boundary][VERIFIED] Minimal sudo transition boundary is internally consistent")
# endregion FUNC_test_add_helper_privilege_boundary
