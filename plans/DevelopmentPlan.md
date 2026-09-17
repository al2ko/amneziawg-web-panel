$START_DEV_PLAN

**PURPOSE:** Реализовать самостоятельную, безопасную Flask-панель для существующего AmneziaWG-интерфейса `awg0` с изолированными слоями, тестами и systemd-развёртыванием.

---

### 1. Draft Code Graph

```xml
<DraftCodeGraph>
  <app_py FILE="app.py" TYPE="FlaskApplication">
    <annotation>Создаёт приложение, подключает маршруты, защиту сессий и обработчики ошибок.</annotation>
    <app_create_app_FUNCTION NAME="create_app" TYPE="APPLICATION_FACTORY">
      <annotation>Собирает зависимости из конфигурации для production и pytest.</annotation>
      <CrossLinks>
        <Link TARGET="services_auth_AuthService_CLASS" TYPE="USES_CLASS" />
        <Link TARGET="services_vpn_VpnService_CLASS" TYPE="USES_CLASS" />
        <Link TARGET="repositories_clients_ClientRepository_CLASS" TYPE="USES_CLASS" />
      </CrossLinks>
    </app_create_app_FUNCTION>
  </app_py>
  <services_auth_py FILE="services/auth.py" TYPE="SecurityService">
    <annotation>Хеширует пароль, управляет сессиями, CSRF, лимитом попыток и аудитом входа.</annotation>
    <services_auth_AuthService_CLASS NAME="AuthService" TYPE="IS_CLASS_OF_MODULE" />
  </services_auth_py>
  <services_vpn_py FILE="services/vpn.py" TYPE="DomainService">
    <annotation>Безопасно читает awg0, строит снимок пиров, меняет конфигурацию и runtime через фиксированные argv.</annotation>
    <services_vpn_VpnService_CLASS NAME="VpnService" TYPE="IS_CLASS_OF_MODULE">
      <services_vpn_VpnService_create_peer_METHOD NAME="create_peer" TYPE="IS_METHOD_OF_CLASS">
        <CrossLinks>
          <Link TARGET="services_artifacts_ArtifactService_CLASS" TYPE="USES_CLASS" />
          <Link TARGET="repositories_clients_ClientRepository_CLASS" TYPE="USES_CLASS" />
        </CrossLinks>
      </services_vpn_VpnService_create_peer_METHOD>
    </services_vpn_VpnService_CLASS>
  </services_vpn_py>
  <services_artifacts_py FILE="services/artifacts.py" TYPE="ArtifactService">
    <annotation>Создаёт конфигурации клиентов и PNG QR-коды вне web-root.</annotation>
    <services_artifacts_ArtifactService_CLASS NAME="ArtifactService" TYPE="IS_CLASS_OF_MODULE" />
  </services_artifacts_py>
  <repositories_clients_py FILE="repositories/clients.py" TYPE="Repository">
    <annotation>Хранит имена, состояние приостановки, пути артефактов и аудит в SQLite.</annotation>
    <repositories_clients_ClientRepository_CLASS NAME="ClientRepository" TYPE="IS_CLASS_OF_MODULE" />
  </repositories_clients_py>
  <templates_dashboard_html FILE="templates/dashboard.html" TYPE="FrontendTemplate">
    <annotation>Русскоязычная адаптивная таблица, поиск, сортировка и модальные действия.</annotation>
  </templates_dashboard_html>
  <static_app_js FILE="static/app.js" TYPE="FrontendController">
    <annotation>Отправляет CSRF-защищённые формы, управляет поиском, сортировкой и подтверждением удаления.</annotation>
  </static_app_js>
  <tests_test_vpn_py FILE="tests/test_vpn.py" TYPE="Pytest">
    <annotation>Проверяет парсинг, создание, изменение и безопасные argv через подменяемый runner.</annotation>
  </tests_test_vpn_py>
  <tests_test_web_py FILE="tests/test_web.py" TYPE="Pytest">
    <annotation>Проверяет вход, CSRF, cookie и защищённые HTTP-маршруты без запуска сервера.</annotation>
  </tests_test_web_py>
</DraftCodeGraph>
```

---

### 2. Step-by-step Data Flow

1. **Вход и защита:** Flask получает логин и пароль, `AuthService` проверяет Argon2-хеш и IP rate limit, создаёт серверную запись сессии в SQLite, выдаёт защищённую cookie и отдельный CSRF-токен. Каждый изменяющий маршрут сверяет сессию, idle timeout и CSRF.
2. **Снимок dashboard:** `VpnService` читает `awg0.conf` и запускает фиксированную команду `awg show awg0 dump`. Парсер сопоставляет публичные ключи и AllowedIPs; репозиторий добавляет имя и состояние; сервис рассчитывает online/offline/never-connected, uptime и счётчики. Шаблон получает уже подготовленные DTO.
3. **Создание клиента:** маршрут валидирует уникальное имя, `VpnService` выбирает свободный IP из сети интерфейса, генерирует ключи только через фиксированные инструменты AmneziaWG, атомарно обновляет конфигурацию, применяет peer командой `awg set` без restart, записывает метаданные и аудит. `ArtifactService` создаёт `.conf` и QR PNG с ограниченными правами, после чего маршрут возвращает карточку клиента.
4. **Изменение жизненного цикла:** переименование обновляет только метаданные и имена файлов. Отключение сохраняет необходимые данные клиента в SQLite и исключает peer из runtime plus конфигурации. Включение восстанавливает peer из сохранённых данных. Удаление проходит POST с CSRF и подтверждением, убирает peer, метаданные и артефакты, затем записывает неизменяемую audit-запись.
5. **Артефакты и бэкап:** маршруты скачивания сверяют права сессии и разрешённое имя, возвращают только путь, построенный сервисом. Экспорт создаёт архив SQLite и разрешённых конфигурационных метаданных вне web-root; аудит не содержит private keys, паролей или токенов.
6. **Операционное управление:** мониторинг вызывает `systemctl is-active` и фиксированно проверяет uptime. Перезапуск `awg0` выполняется только CSRF-защищённым POST с записью в аудит. systemd перезапускает панель при падении.

---

### 3. Implementation Decisions

- **Backend:** Python 3.11+, Flask, stdlib `sqlite3`, `subprocess.run(shell=False)`, Argon2-CFFI, `qrcode[pil]`, Gunicorn. Flask-WTF или собственный компактный CSRF-механизм будет выбран в реализации после проверки совместимых версий; предпочтение Flask-WTF для проверенной защиты форм.
- **Слои:** `services/` не импортируют Flask; `repositories/` не выполняют команды; `templates/` и `static/` не содержат бизнес-логики. Все системные зависимости поступают через конфигурацию и runner, что делает логику тестируемой на временных файлах.
- **Совместимость:** парсер понимает текущие `[Peer]` блоки `awg0.conf` и отдельно ищет существующие конфиги `/root/awg/*.conf`; неизвестные поля AmneziaWG сохраняются при записи. Перед любой мутацией создаётся timestamped backup конфигурации. В первом запуске предусмотрена миграция существующих клиентов в SQLite без изменения awg-конфигурации.
- **Привилегии:** production unit запускается сервисным пользователем с узким `sudoers` allowlist для фиксированных helper-команд. Private keys и клиентские артефакты имеют режим 0600. Не передавать root-доступ напрямую веб-процессу.
- **Observability:** Python logging в rotating file plus journald, структурированная audit-таблица SQLite. LDD-сообщения `IMP:7–10` отражают системные границы и критические решения без секретов.
- **UI:** одна dashboard-страница, модальные формы и detail-страница/диалог; CSS без тяжёлого frontend-фреймворка, desktop and tablet responsive, доступные кнопки .conf/QR.

---

### 4. Implementation Sequence

1. Создать структуру пакета, `requirements.txt` с обоснованием каждой зависимости, `.env.example`, конфигурацию путей, Doxyfile и миграцию SQLite.
2. Реализовать модели DTO, валидаторы, безопасный runner, парсеры awg-конфигурации и runtime dump; покрыть unit-тестами фикстур.
3. Реализовать repository, auth/session/rate limit/CSRF/audit и тесты безопасности.
4. Реализовать сервисы управления пирами, IP allocation, атомарную запись plus backup, конфигурации и QR; покрыть unit and integration tests with temporary filesystem and injected runner.
5. Реализовать Flask factory and protected routes, русскоязычные templates/styles/scripts; добавить headless Flask-client tests.
6. Добавить backup endpoint, system state and restart action, install script, systemd unit, sudoers template, README Russian with deployment and recovery steps.
7. Добавить `tests/conftest.py` с Anti-Loop counter, `tests/test_guide.md`, пройти pytest, просмотреть LDD logs, собрать Doxygen, выполнить QA-проверку.

---

### 5. Acceptance Criteria

- [ ] **Авторизация:** login/logout, hashed password, cookie session timeout, CSRF и login rate-limit проверены тестами.
- [ ] **Совместимость:** существующие `[Peer]` и `/root/awg/*.conf` видны без изменения исходной конфигурации при первичной миграции.
- [ ] **Клиенты:** create, rename, disable, enable, delete и download .conf/PNG работают через защищённые маршруты; имя валидируется и пользовательский ввод не попадает в shell.
- [ ] **Статистика:** dashboard отображает статус сервиса, server/interface uptime, total clients, active clients, handshake, endpoint and RX/TX with search and sorting for 100 peers.
- [ ] **Безопасность:** private keys and passwords never appear in HTML, audit logs or ordinary app logs; every mutation and login attempt goes to audit.
- [ ] **Развёртывание:** documented installer and systemd unit serve HTTP port 8080 and restart on failure, without nginx/apache.
- [ ] **Качество:** pytest passes with LDD IMP:7–10 trace assertions; Doxygen generates docs; `tests/test_guide.md` enables independent QA.

---

### 6. Feature Slice: Configuration Preview

```xml
<DraftCodeGraph>
  <artifacts_py FILE="amnezia_panel/artifacts.py" TYPE="ArtifactResolver">
    <ArtifactService_variants_METHOD NAME="variants" TYPE="IS_METHOD_OF_CLASS">
      <annotation>Разрешает только пары .conf/.png и .vpnuri/.vpnuri.png выбранного клиента.</annotation>
    </ArtifactService_variants_METHOD>
  </artifacts_py>
  <routes_py FILE="amnezia_panel/routes.py" TYPE="ProtectedPreviewAPI">
    <artifact_preview_ROUTE NAME="artifact_preview" TYPE="AUTHENTICATED_JSON_ROUTE" />
  </routes_py>
  <dashboard_html FILE="amnezia_panel/templates/dashboard.html" TYPE="ModalFrontend" />
</DraftCodeGraph>
```

1. Администратор нажимает «QR и конфигурации» у одного клиента.
2. JavaScript запрашивает защищённый JSON только этого клиента.
3. Backend возвращает имеющиеся варианты: обычный `.conf`/`.png` и зашифрованный `.vpnuri`/`.vpnuri.png`.
4. Модальное окно отображает QR и текст каждого варианта, сохраняя отдельные ссылки скачивания.

- [ ] Preview требует действующую серверную сессию и валидное имя клиента.
- [ ] Оба варианта отображаются и скачиваются, если файлы существуют; отсутствующий вариант помечается.
- [ ] Rename/delete охватывают все четыре файла.
- [ ] Текст конфигураций не встраивается в исходную dashboard-страницу.

---

### 7. Feature Slice: Script-compatible Client Creation

```xml
<DraftCodeGraph>
  <awg_py FILE="amnezia_panel/awg.py" TYPE="PeerOrchestrator">
    <AwgService_create_peer_METHOD NAME="create_peer" TYPE="IS_METHOD_OF_CLASS">
      <annotation>Передаёт валидированное имя узкому privileged helper и синхронизирует canonical peer с SQLite.</annotation>
    </AwgService_create_peer_METHOD>
  </awg_py>
  <amnezia_panel_add FILE="deploy/amnezia-panel-add" TYPE="RootHelper">
    <annotation>Запускает только manage_amneziawg.sh --json --yes add для одного безопасного имени.</annotation>
  </amnezia_panel_add>
</DraftCodeGraph>
```

1. Панель валидирует уникальное имя и вызывает фиксированный argv `sudo -n /usr/local/sbin/amnezia-panel-add NAME`.
2. Root-owned helper повторно проверяет имя и вызывает существующий `manage_amneziawg.sh add` в JSON-режиме.
3. Сервис проверяет `ok`, `status=created`, четыре артефакта и находит созданный `#_Name` peer в canonical config.
4. Helper восстанавливает точечные ACL на заменённом `awg0.conf` и четырёх файлах созданного клиента.
5. При повторном использовании удалённого через панель имени helper архивирует только осиротевшие key/expiry-файлы, если canonical marker и все четыре артефакта отсутствуют.
6. Публичный ключ, адрес и peer block записываются в SQLite; секреты не попадают в JSON панели или логи.

- [ ] Новый клиент панели создаётся штатным скриптом и получает `.conf`, `.png`, `.vpnuri`, `.vpnuri.png`.
- [ ] Веб-процессу разрешён sudo только на root-owned helper без произвольных аргументов оболочки.
- [ ] systemd bounding set разрешает helper сменить UID/GID и обслужить root-owned файлы, но ambient capabilities Gunicorn остаются только `CAP_NET_ADMIN`.
- [ ] Имена `#_Name = client` распознаются при импорте и корректно обновляются при переименовании.
- [ ] При пустой настройке helper сохраняется изолированный native fallback для разработки и тестов.

$END_DEV_PLAN
