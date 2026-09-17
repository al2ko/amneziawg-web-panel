#!/usr/bin/env bash
set +e
id amnezia-panel
namei -l /etc/amnezia/amneziawg/awg0.conf
namei -l /root/awg
getfacl -p /root /root/awg /etc/amnezia/amneziawg /etc/amnezia/amneziawg/awg0.conf | sed -n '1,180p'
sudo -u amnezia-panel test -r /etc/amnezia/amneziawg/awg0.conf
printf 'CONFIG_READ=%s\n' "$?"
sudo -u amnezia-panel test -w /etc/amnezia/amneziawg/awg0.conf
printf 'CONFIG_WRITE=%s\n' "$?"
sudo -u amnezia-panel test -x /root
printf 'ROOT_TRAVERSE=%s\n' "$?"
sudo -u amnezia-panel test -r /root/awg
printf 'CLIENT_DIR_READ=%s\n' "$?"
sudo -u amnezia-panel test -w /root/awg
printf 'CLIENT_DIR_WRITE=%s\n' "$?"
sudo -u amnezia-panel /opt/amnezia-panel/.venv/bin/python -c \
  "from pathlib import Path; print('CONFIG_KIND', Path('/etc/amnezia/amneziawg/awg0.conf').is_file()); print('CLIENT_DIR_KIND', Path('/root/awg').is_dir())"
