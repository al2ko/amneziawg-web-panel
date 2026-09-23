#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Запустите установщик от root" >&2
  exit 1
fi

SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="/opt/amnezia-panel"
STATE_DIR="/var/lib/amnezia-panel"
LOG_DIR="/var/log/amnezia-panel"
CONFIG_FILE="/etc/amnezia-panel.env"
CREDENTIALS_FILE="/root/amnezia-panel-credentials.txt"

test -f /etc/amnezia/amneziawg/awg0.conf || { echo "Не найден awg0.conf" >&2; exit 1; }
command -v awg >/dev/null || { echo "Не найдена команда awg" >&2; exit 1; }

apt-get update
apt-get install -y python3 python3-venv acl
id amnezia-panel >/dev/null 2>&1 || useradd --system --home-dir "${STATE_DIR}" --shell /usr/sbin/nologin amnezia-panel
install -d -o amnezia-panel -g amnezia-panel -m 0750 "${INSTALL_DIR}" "${STATE_DIR}" "${STATE_DIR}/clients" "${LOG_DIR}"
cp -a "${SOURCE_DIR}/amnezia_panel" "${SOURCE_DIR}/tools" "${SOURCE_DIR}/requirements.txt" "${INSTALL_DIR}/"
chown -R amnezia-panel:amnezia-panel "${INSTALL_DIR}" "${STATE_DIR}" "${LOG_DIR}"
python3 -m venv "${INSTALL_DIR}/.venv"
"${INSTALL_DIR}/.venv/bin/pip" install --requirement "${INSTALL_DIR}/requirements.txt"

# Только traversal к точному каталогу клиентов; содержимое /root нельзя перечислять или читать.
setfacl -m u:amnezia-panel:--x /root
# Панель управляет файлами непосредственно в /root/awg, но не получает рекурсивный доступ к подкаталогам.
setfacl -m u:amnezia-panel:rwx,d:u:amnezia-panel:rwX /root/awg
find /root/awg -maxdepth 1 -type f \( -name '*.conf' -o -name '*.png' -o -name '*.vpnuri' \) -exec setfacl -m u:amnezia-panel:rw -- {} +
# Закрытый родитель требует только traversal; его содержимое остаётся недоступно для чтения.
setfacl -m u:amnezia-panel:--x /etc/amnezia
setfacl -m u:amnezia-panel:rwx /etc/amnezia/amneziawg
setfacl -m u:amnezia-panel:rw /etc/amnezia/amneziawg/awg0.conf

if [[ ! -f "${CONFIG_FILE}" ]]; then
  SECRET="$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')"
  if [[ -t 0 ]]; then
    HASH="$(cd "${INSTALL_DIR}" && "${INSTALL_DIR}/.venv/bin/python" -m tools.hash_password)"
  else
    GENERATED_PASSWORD="$(od -An -N24 -tx1 /dev/urandom | tr -d ' \n')"
    # BUG_FIX_CONTEXT: Запуск tools/*.py напрямую помещал только tools/ в sys.path; module mode сохраняет корень приложения для импорта amnezia_panel.
    HASH="$(printf '%s\n' "${GENERATED_PASSWORD}" | (cd "${INSTALL_DIR}" && "${INSTALL_DIR}/.venv/bin/python" -m tools.hash_password_stdin))"
  fi
  ENDPOINT="${AMNEZIA_INSTALL_ENDPOINT:-}"
  if [[ -z "${ENDPOINT}" ]]; then
    if [[ -t 0 ]]; then
      read -r -p "Публичный Endpoint сервера (IP:PORT): " ENDPOINT
    else
      echo "Для неинтерактивной установки задайте AMNEZIA_INSTALL_ENDPOINT" >&2
      exit 1
    fi
  fi
  install -m 0600 /dev/null "${CONFIG_FILE}"
  {
    printf 'AMNEZIA_PANEL_SECRET=%s\n' "${SECRET}"
    printf 'AMNEZIA_PANEL_ADMIN=admin\n'
    printf 'AMNEZIA_PANEL_PASSWORD_HASH=%s\n' "${HASH}"
    printf 'AMNEZIA_PANEL_DB=%s/panel.db\n' "${STATE_DIR}"
    printf 'AMNEZIA_PANEL_CONFIG=/etc/amnezia/amneziawg/awg0.conf\n'
    printf 'AMNEZIA_PANEL_CLIENTS=/root/awg\n'
    printf 'AMNEZIA_PANEL_INTERFACE=awg0\n'
    printf 'AMNEZIA_PANEL_LOG=%s/panel.log\n' "${LOG_DIR}"
    printf 'AMNEZIA_PANEL_ENDPOINT=%s\n' "${ENDPOINT}"
    printf 'AMNEZIA_PANEL_REGEN_HELPER=/usr/local/sbin/amnezia-panel-regen\n'
  } >> "${CONFIG_FILE}"
  if [[ -n "${GENERATED_PASSWORD:-}" ]]; then
    install -m 0600 /dev/null "${CREDENTIALS_FILE}"
    {
      printf 'URL=http://%s:8080\n' "${ENDPOINT%%:*}"
      printf 'LOGIN=admin\n'
      printf 'PASSWORD=%s\n' "${GENERATED_PASSWORD}"
    } > "${CREDENTIALS_FILE}"
    unset GENERATED_PASSWORD
    echo "Учётные данные сохранены в ${CREDENTIALS_FILE}"
  fi
fi

install -o root -g root -m 0644 "${SOURCE_DIR}/deploy/amnezia-panel.service" /etc/systemd/system/amnezia-panel.service
install -o root -g root -m 0755 "${SOURCE_DIR}/deploy/amnezia-panel-add" /usr/local/sbin/amnezia-panel-add
install -o root -g root -m 0755 "${SOURCE_DIR}/deploy/amnezia-panel-regen" /usr/local/sbin/amnezia-panel-regen
install -o root -g root -m 0440 "${SOURCE_DIR}/deploy/amnezia-panel.sudoers" /etc/sudoers.d/amnezia-panel
visudo -cf /etc/sudoers.d/amnezia-panel
systemctl daemon-reload
systemctl enable --now amnezia-panel.service
systemctl --no-pager status amnezia-panel.service
