$START_TEST_GUIDE

**PURPOSE:** Дать независимому QA-исполнителю воспроизводимый способ проверить панель без доступа к реальному VPN.
**SCOPE:** Backend, security, headless web flow, semantic logs and optional VPS smoke test.
**KEYWORDS:** pytest, AmneziaWG, awg0, CSRF, Argon2, LDD, integration.

$START_DOCUMENT_PLAN
### Document Plan

**SECTION_GOALS:**
- GOAL Выполнить изолированные автоматические проверки => QA_AUTOMATED
- GOAL Сопоставить критические логи с ожидаемым data flow => QA_TRACE
- GOAL Проверить production-интеграцию на тестовом VPS => QA_SMOKE

**SECTION_USE_CASES:**
- USE_CASE QA запускает pytest с временной директорией => SCENARIO_TEST
- USE_CASE QA создаёт тестового клиента и сверяет awg show => SCENARIO_VPS
$END_DOCUMENT_PLAN

$START_SECTION_AUTOMATED
### Автоматическая проверка

$START_ARTIFACT_QA_AUTOMATED
#### Pytest

**TYPE:** TOOL
**KEYWORDS:** pytest, tmp_path, fake runner, Flask client.

$START_CONTRACT
**PURPOSE:** Проверить бизнес-логику напрямую без subprocess и реального сетевого интерфейса.
**DESCRIPTION:** Установить `requirements.txt`, затем выполнить `python -m pytest tests -s -v`. В ограниченной Windows-среде использовать `--basetemp=.test-tmp`.
**RATIONALE:** Внедрённый runner и временные пути исключают влияние на VPN хоста.
**ACCEPTANCE_CRITERIA:** Все тесты PASS; `.test_counter.json` содержит `failures: 0`.
$END_CONTRACT

$START_BODY
Проверяются runtime parser, импорт старых файлов по IP, сохранение неизвестных полей, repeated Peer removal, фиксированный helper argv, JSON-контракт создания, четыре артефакта, create/rename/disable/enable/delete, Argon2, session, CSRF, rate limit и Flask routes.
$END_BODY

$START_LINKS
**IMPLEMENTS:** QA_AUTOMATED
**IMPACTS:** QA_TRACE
**REQUIRES:** Python 3.11+, requirements.txt
$END_LINKS
$END_ARTIFACT_QA_AUTOMATED
$END_SECTION_AUTOMATED

$START_SECTION_TRACE
### Проверка LDD-трассы

$START_ARTIFACT_QA_TRACE
#### Ожидаемые маркеры

**TYPE:** KEY_RESULT
**KEYWORDS:** IMP:8, IMP:9, semantic trace.

$START_CONTRACT
**PURPOSE:** Убедиться, что тесты прошли по правильной логической траектории.
**DESCRIPTION:** В выводе должны присутствовать `[IMP:9][migrate_existing][COMPLETE]`, `[IMP:9][dashboard][SNAPSHOT]`, `[IMP:9][create_peer][SUCCESS]`, включая `created by canonical script`, последовательность rename/disable/enable/delete и `[IMP:9][login][SUCCESS]`.
**RATIONALE:** PASS без ожидаемой бизнес-трассы не доказывает корректный путь выполнения.
**ACCEPTANCE_CRITERIA:** Маркеры соответствуют порядку data flow; в логах нет private keys, пароля или session token.
$END_CONTRACT

$START_BODY
`[IMP:10]` допустим только в специально проверяемом отказе. Неожиданный `[IMP:10]` означает дефект даже при зелёном pytest.
$END_BODY

$START_LINKS
**IMPLEMENTS:** QA_TRACE
**IMPACTS:** QA_AUTOMATED
**REQUIRES:** pytest -s
$END_LINKS
$END_ARTIFACT_QA_TRACE
$END_SECTION_TRACE

$START_SECTION_SMOKE
### Smoke test на VPS

$START_ARTIFACT_QA_SMOKE
#### Тестовый клиент

**TYPE:** USE_CASE
**KEYWORDS:** test VPS, awg show, client config, rollback.

$START_CONTRACT
**PURPOSE:** Проверить реальную совместимость с установленной версией AmneziaWG.
**DESCRIPTION:** Перед тестом сделать внешнюю копию `awg0.conf`. Войти, создать уникального клиента `qa_device`, скачать `.conf` и QR, подключить тестовое устройство, сверить handshake/traffic, отключить и включить клиента, затем удалить его. Проверить `awg show awg0` после каждого изменения и работу `manage_amneziawg.sh` после теста.
**RATIONALE:** Локальная машина не содержит Linux netlink, systemd и реальный awg0.
**ACCEPTANCE_CRITERIA:** Подключение успешно, существующие пиры не прерываются, удалённый ключ отсутствует в `awg show`, systemd поднимает панель после reboot.
$END_CONTRACT

$START_BODY
SQL-проверка аудита: `sqlite3 /var/lib/amnezia-panel/panel.db "select action,target from audit order by id desc limit 20;"`. Ожидаются login_success, client_create, client_disable, client_enable, client_delete и artifact_download.
$END_BODY

$START_LINKS
**IMPLEMENTS:** QA_SMOKE
**IMPACTS:** Production acceptance
**REQUIRES:** Isolated test device, trusted UFW IP, external backup
$END_LINKS
$END_ARTIFACT_QA_SMOKE
$END_SECTION_SMOKE

$END_TEST_GUIDE
