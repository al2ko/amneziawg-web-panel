#!/usr/bin/env bash
set -euo pipefail

WORK_DIR="$(mktemp -d /tmp/amnezia-panel-check.XXXXXX)"
cleanup() {
  local resolved
  resolved="$(readlink -f -- "${WORK_DIR}")"
  if [[ "${resolved}" == /tmp/amnezia-panel-check.* ]]; then
    rm -rf -- "${resolved}"
  fi
}
trap cleanup EXIT

curl --fail --silent --show-error --cookie-jar "${WORK_DIR}/cookies" \
  http://127.0.0.1:8080/login --output "${WORK_DIR}/login.html"
CSRF="$(sed -n 's/.*name="csrf_token" value="\([^"]*\)".*/\1/p' "${WORK_DIR}/login.html" | head -n1)"
LOGIN="$(sed -n 's/^LOGIN=//p' /root/amnezia-panel-credentials.txt)"
PASSWORD="$(sed -n 's/^PASSWORD=//p' /root/amnezia-panel-credentials.txt)"
printf 'data-urlencode = "username=%s"\ndata-urlencode = "password=%s"\ndata-urlencode = "csrf_token=%s"\n' \
  "${LOGIN}" "${PASSWORD}" "${CSRF}" > "${WORK_DIR}/post.cfg"
chmod 0600 "${WORK_DIR}/post.cfg"
LOGIN_HTTP="$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
  --cookie "${WORK_DIR}/cookies" --cookie-jar "${WORK_DIR}/cookies" \
  --config "${WORK_DIR}/post.cfg" --request POST http://127.0.0.1:8080/login)"
DASHBOARD_HTTP="$(curl --silent --show-error --output "${WORK_DIR}/dashboard.html" --write-out '%{http_code}' \
  --cookie "${WORK_DIR}/cookies" http://127.0.0.1:8080/)"
grep -q 'Панель управления' "${WORK_DIR}/dashboard.html"
printf 'LOGIN_HTTP=%s DASHBOARD_HTTP=%s\n' "${LOGIN_HTTP}" "${DASHBOARD_HTTP}"

CLIENT_NAME="$(/opt/amnezia-panel/.venv/bin/python -c "import sqlite3; from pathlib import Path; db=sqlite3.connect('/var/lib/amnezia-panel/panel.db'); names=[row[0] for row in db.execute('select name from clients order by name')]; print(next((name for name in names if (Path('/root/awg') / (name + '.vpnuri')).is_file()), names[0]))")"
PREVIEW_HTTP="$(curl --silent --show-error --output "${WORK_DIR}/preview.json" --write-out '%{http_code}' \
  --cookie "${WORK_DIR}/cookies" "http://127.0.0.1:8080/clients/${CLIENT_NAME}/artifacts")"
printf 'PREVIEW_HTTP=%s CLIENT=%s\n' "${PREVIEW_HTTP}" "${CLIENT_NAME}"
/opt/amnezia-panel/.venv/bin/python -c \
  "import json; data=json.load(open('${WORK_DIR}/preview.json', encoding='utf-8')); print('VARIANTS', [(item['id'], item['available'], item['qr_available'], len(item['text'])) for item in data['variants']])"

/opt/amnezia-panel/.venv/bin/python -c \
  "import sqlite3; db=sqlite3.connect('/var/lib/amnezia-panel/panel.db'); print('IMPORTED_CLIENTS', db.execute('select count(*) from clients').fetchone()[0]); print('AUDIT_ROWS', db.execute('select count(*) from audit').fetchone()[0])"
printf 'AWG_PEERS '
awg show awg0 | grep -c '^peer:'
printf 'SERVICE_ACTIVE '
systemctl is-active amnezia-panel.service
printf 'SERVICE_ENABLED '
systemctl is-enabled amnezia-panel.service
ss -ltnp | grep ':8080 '
stat -c 'CREDENTIALS_MODE=%a OWNER=%U:%G' /root/amnezia-panel-credentials.txt
journalctl -u amnezia-panel.service -n 20 --no-pager
