$START_BUSINESS_REQUIREMENTS

**PURPOSE:** Зафиксировать границы, безопасность и пользовательские результаты самостоятельной веб-панели управления одним сервером AmneziaWG.
**SCOPE:** Администратор, клиенты awg0, статистика, конфигурации, аудит, резервное копирование и развёртывание.
**KEYWORDS:** AmneziaWG, awg0, Flask, SQLite, CSRF, systemd, VPN, SSH, audit.

$START_DOCUMENT_PLAN
### Document Plan

**SECTION_GOALS:**
- GOAL Управлять существующим awg0 из браузера без ручного редактирования конфигурации => GOAL_CONTROL
- GOAL Не допустить неаутентифицированного или небезопасного изменения VPN => GOAL_SECURITY
- GOAL Развернуть панель как автономный сервис на VPS => GOAL_OPERATIONS

**SECTION_USE_CASES:**
- USE_CASE Администратор входит и просматривает состояние сервера => SCENARIO_DASHBOARD
- USE_CASE Администратор создаёт и получает конфигурацию клиента => SCENARIO_CREATE_CLIENT
- USE_CASE Администратор меняет жизненный цикл существующего клиента => SCENARIO_MANAGE_CLIENT
$END_DOCUMENT_PLAN

$START_SECTION_GOALS
### Цели и ограничения

$START_ARTIFACT_GOAL_CONTROL
#### Управление awg0

**TYPE:** GOAL
**KEYWORDS:** peers, client configuration, QR code, runtime statistics.

$START_CONTRACT
**PURPOSE:** Дать единственному администратору русскоязычный интерфейс для просмотра и безопасного управления пирами awg0.
**DESCRIPTION:** AAG: Администратор → авторизуется → видит объединённый список пиров из `/etc/amnezia/amneziawg/awg0.conf`, состояния `awg show awg0 dump` и каталога `/root/awg/` → создаёт, переименовывает, приостанавливает, включает или удаляет клиента → получает `.conf`, `.png`, `.vpnuri` и `.vpnuri.png`.
**RATIONALE:** Сервер уже настроен, а существующий скрипт обязан оставаться совместимым; панель выступает дополнительным управляющим интерфейсом, а не установщиком VPN.
**ACCEPTANCE_CRITERIA:** До 100 клиентов отображаются с поиском, сортировкой, статусом, трафиком и актуальным handshake; изменения применяются без перезапуска работающих пиров.
$END_CONTRACT

$START_BODY
Поддерживается только интерфейс `awg0`. Источником истины для активных пиров является конфигурация AmneziaWG; SQLite хранит метаданные панели, состояние отключения и аудит.
$END_BODY

$START_LINKS
**IMPLEMENTS:** GOAL_CONTROL
**IMPACTS:** SCENARIO_DASHBOARD, SCENARIO_CREATE_CLIENT, SCENARIO_MANAGE_CLIENT
**REQUIRES:** GOAL_SECURITY
$END_LINKS

$END_ARTIFACT_GOAL_CONTROL

$START_ARTIFACT_GOAL_SECURITY
#### Защищённое локальное администрирование

**TYPE:** PRINCIPLE
**KEYWORDS:** password hash, session cookie, CSRF, rate limit, validation, command injection.

$START_CONTRACT
**PURPOSE:** Ограничить доступ одним администратором и исключить выполнение пользовательского ввода как системной команды.
**DESCRIPTION:** Логин сверяется с хешем пароля Argon2; серверная сессия имеет HttpOnly, SameSite=Strict cookie, таймаут бездействия и ротацию при входе. Все изменяющие запросы требуют CSRF-токен. Имя клиента проходит регулярное выражение `^[A-Za-z0-9_-]{1,64}$`; команды вызываются только списками аргументов с фиксированными исполняемыми файлами. Ошибки входа ограничиваются по IP и пишутся в аудит.
**RATIONALE:** Панель получает root-доступ к сетевой конфигурации, поэтому защита должна компенсировать HTTP-доступ внутри доверенного UFW-периметра.
**ACCEPTANCE_CRITERIA:** Пароль не хранится открыто; запрос на изменение без сессии или CSRF отклоняется; некорректное имя не доходит до системного вызова; повторные неудачные входы временно блокируются.
$END_CONTRACT

$START_BODY
Секреты и рабочая база размещаются с правами, доступными сервисному пользователю панели; не включаются в резервные копии или логи в открытом виде.
$END_BODY

$START_LINKS
**IMPLEMENTS:** GOAL_SECURITY
**IMPACTS:** GOAL_CONTROL, GOAL_OPERATIONS
**REQUIRES:** UFW trusted IP restriction
$END_LINKS

$END_ARTIFACT_GOAL_SECURITY

$START_ARTIFACT_GOAL_OPERATIONS
#### Автономное развёртывание

**TYPE:** NFR
**KEYWORDS:** Ubuntu, Debian, port 8080, systemd, backup, logging.

$START_CONTRACT
**PURPOSE:** Позволить установить и поддерживать панель на VPS без nginx или Apache.
**DESCRIPTION:** AAG: Оператор → запускает install-скрипт от root → устанавливаются Python-зависимости и сервис → systemd запускает Gunicorn на `0.0.0.0:8080` с автоматическим перезапуском → оператор открывает панель с разрешённого UFW IP.
**RATIONALE:** Условие ТЗ требует самостоятельный HTTP-сервис, запуск после перезагрузки и предсказуемое обслуживание.
**ACCEPTANCE_CRITERIA:** Поставляются шаблон systemd-unit, install-скрипт, конфигурация окружения, документация восстановления и экспорт резервной копии SQLite плюс конфигурационных артефактов.
$END_CONTRACT

$START_BODY
Для исполнения команд потребуется явно документированная настройка sudoers либо запуск процесса с минимально необходимыми root-правами; решение выбирается в плане как отдельный контролируемый шаг.
$END_BODY

$START_LINKS
**IMPLEMENTS:** GOAL_OPERATIONS
**IMPACTS:** GOAL_CONTROL
**REQUIRES:** Ubuntu or Debian, installed AmneziaWG, configured UFW
$END_LINKS

$END_ARTIFACT_GOAL_OPERATIONS
$END_SECTION_GOALS

$START_SECTION_USE_CASES
### Пользовательские сценарии

$START_ARTIFACT_SCENARIOS
#### Основные сценарии

**TYPE:** USE_CASE
**KEYWORDS:** dashboard, add peer, disable peer, download configuration.

$START_CONTRACT
**PURPOSE:** Определить проверяемый пользовательский поток для интерфейса и API.
**DESCRIPTION:** SCENARIO_DASHBOARD: Администратор → входит → видит сервис, uptime, счётчики, суммарный трафик и таблицу клиентов. SCENARIO_CREATE_CLIENT: Администратор → вводит валидное уникальное имя → штатный `manage_amneziawg.sh` через ограниченный helper создаёт пир и полный комплект обычных/vpnuri-артефактов. SCENARIO_MANAGE_CLIENT: Администратор → выбирает клиента → скачивает артефакты либо переименовывает, отключает, включает или окончательно удаляет его после подтверждения.
**RATIONALE:** Эти сценарии покрывают обязательный функционал ТЗ и задают границы первого релиза.
**ACCEPTANCE_CRITERIA:** Каждый сценарий имеет прямые backend-тесты, интеграционный тест с временными файлами и ручную проверку интерфейса.
$END_CONTRACT

$START_BODY
Переименование меняет только безопасные метаданные и имена клиентских файлов, не публичный ключ. Отключение удаляет пир из runtime/config и сохраняет его конфигурацию защищённо для последующего включения. Удаление требует подтверждения, удаляет runtime/config/артефакты и оставляет аудит.
$END_BODY

$START_LINKS
**IMPLEMENTS:** SCENARIO_DASHBOARD, SCENARIO_CREATE_CLIENT, SCENARIO_MANAGE_CLIENT
**IMPACTS:** GOAL_CONTROL
**REQUIRES:** GOAL_SECURITY
$END_LINKS

$END_ARTIFACT_SCENARIOS

$START_ARTIFACT_CONFIGURATION_PREVIEW
#### Предпросмотр конфигураций

**TYPE:** USE_CASE
**KEYWORDS:** modal, QR preview, conf, vpnuri, encrypted configuration.

$START_CONTRACT
**PURPOSE:** Позволить просмотреть QR и текст обычной и зашифрованной конфигурации без обязательного скачивания.
**DESCRIPTION:** Администратор → открывает модальное окно клиента → видит `.conf` с `.png` и `.vpnuri` с `.vpnuri.png` → при необходимости скачивает любой из четырёх файлов.
**RATIONALE:** Мобильное подключение удобнее выполнять сканированием с экрана, а текст нужен для проверки и ручного копирования.
**ACCEPTANCE_CRITERIA:** Секретные тексты загружаются только после действия авторизованного администратора; произвольные пути и имена отклоняются.
$END_CONTRACT

$START_BODY
Обычный вариант называется «Без шифрования», `.vpnuri` — «С шифрованием». Если пара отсутствует, интерфейс показывает понятное состояние вместо битой ссылки.
$END_BODY

$START_LINKS
**IMPLEMENTS:** SCENARIO_MANAGE_CLIENT
**IMPACTS:** GOAL_CONTROL, GOAL_SECURITY
**REQUIRES:** Authenticated session, artifact filename validation
$END_LINKS

$END_ARTIFACT_CONFIGURATION_PREVIEW
$END_SECTION_USE_CASES

$END_BUSINESS_REQUIREMENTS
