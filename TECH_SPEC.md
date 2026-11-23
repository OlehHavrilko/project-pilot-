# «Пилот»: техническое задание на реализацию (v1, 23.11.2026)

Этот документ дополняет `PROJECT_PILOT.md`: там — *что* за проект и *зачем*, здесь — *как именно*
он собирается: границы компонентов, протоколы, форматы данных, принятые решения по библиотекам,
проверенное окружение и пошаговый план этапов. Если документы расходятся, приоритет у `TECH_SPEC.md`
для технических деталей и у `PROJECT_PILOT.md` для целей проекта.

Рабочие правила — в `AGENTS.md`. Статус — в `PROGRESS.md`. Этап 0 реализован и проверен
23.11.2026 (см. `PROGRESS.md`); дальше — этап 1.

---

## 1. Проверенное окружение (23.11.2026)

| Что | Факт | Статус |
|-----|------|--------|
| WSL | Ubuntu 24.04, ядро 6.18.58.1-microsoft-standard-WSL2, пользователь `olehwsl` | ✅ |
| Python в WSL | 3.12.3 системный; `pip`/`python3-venv` не было — установлены `apt` | ✅ |
| ffmpeg/ffprobe в WSL | не было — установлены из apt (6.1.1) | ✅ |
| Диски Windows | `/etc/wsl.conf`: `automount=false`, `appendWindowsPath=false` → `/mnt/c`, `/mnt/d` пустые | ⚠️ монтируются вручную |
| Доступ к дискам | `sudo mount -t drvfs C: /mnt/c` и `D: /mnt/d` работают | ✅ |
| Windows | Windows 11 Pro, пользователь `hvrlkoPC`, PowerShell 5.1 | ✅ |
| Windows-Python | 3.12.10: `C:\Users\hvrlkoPC\AppData\Local\Programs\Python\Python312\python.exe` | ✅ |
| OBS | 33.0.0 установлен, профиль «Безымянный», конфиги и бэкап от 22.11 на месте | ✅ |
| obs-websocket | OBS не запущен, порт 4455 закрыт, пароль не задан | ❌ этап 1 |
| VB-Cable | не установлен (в устройствах только Realtek/AMD/Steam) | ❌ этап 1 |
| Ключи API | `DEEPSEEK_API_KEY`, `ELEVENLABS_API_KEY` и др. в WSL не заданы | ❌ этапы 1, 3+ |
| Сеть | mirrored networking **выключен** (`.wslconfig` без `networkingMode`) | ⚠️ работает fallback |
| Связь WSL→Windows | из WSL доступен `172.23.112.1` (vEthernet WSL); проверено HTTP 200 | ✅ |
| Записи OBS | тестовые `.mkv` лежат в `D:\Video`, а не в `D:\Video\recordly` (там `Recordly.exe`) | ⚠️ уточнить на этапе 1 |

**Вывод:** этап 0 полностью проходим уже сейчас по «запасному» сетевому варианту. Этапы 1+ требуют
действий пользователя (VB-Cable, ключи, obs-websocket).

### 1.1. Сеть: два варианта

1. **Mirrored networking (целевой).** В `%UserProfile%\.wslconfig`: `[wsl2]` / `networkingMode=mirrored`,
   затем `wsl --shutdown` (перезапуск WSL — **это убьёт текущую DSH-сессию**, делать только между
   сессиями). Плюс: `localhost` общий, мост слушает `127.0.0.1`.
2. **Fallback NAT (работает сейчас).** Мост на Windows слушает `172.23.112.1` — IP интерфейса
   «vEthernet (WSL)». Из WSL этот адрес доступен, наружу он не выставлен. Адрес меняется при
   перезапуске WSL, поэтому скрипт развёртывания определяет его сам и передаёт мосту.

Мост по умолчанию слушает `127.0.0.1`; `--host` задаётся при запуске. Слушать `0.0.0.0` запрещено.

### 1.2. Постоянное монтирование дисков

Сейчас `/mnt/c` и `/mnt/d` смонтированы вручную и исчезнут после перезапуска WSL. Варианты:
- вернуть `automount=true` в `/etc/wsl.conf` (проще всего, но пользователь отключал его осознанно?);
- прописать в `/etc/fstab`:
  `C: /mnt/c drvfs defaults 0 0` и `D: /mnt/d drvfs defaults 0 0`.

Решение за пользователем — это его система. До решения скрипты проверяют наличие `powershell.exe`
через `/mnt/c/Windows/System32/WindowsPowerShell/v1.0/` и подсказывают команду монтирования.

---

## 2. Границы: мозг в WSL, руки в Windows

> **Целевая платформа — Windows** (см. `PROJECT_PILOT.md`, п. 2.8). Таблица ниже описывает режим
> разработки: WSL — песочница. В рабочем режиме мозг работает на Windows-Python тем же кодом и ходит
> к мосту на `127.0.0.1`. Код мозга должен оставаться кроссплатформенным (`AGENTS.md`, п. 2.0).

| Компонент | Где | Что делает | Чего не делает |
|-----------|-----|-----------|----------------|
| Оркестратор, модели, навыки, разведчик, компилятор, MCP | WSL | Вся логика и решения | — |
| `win_bridge` | Windows | UIA-наблюдение, действия, скриншоты, вывод PCM в аудиоустройство, глобальная стоп-клавиша | Не ходит в сеть наружу, не хранит ключи моделей, не принимает решений |
| Playwright/CDP | WSL | Браузер и Electron на Windows по CDP | — |
| obs-websocket | WSL | Запись, сцены, дорожки | — |
| ffmpeg | WSL | Проверка записей | — |

Мост «тупой»: он получает уже готовые действия и возвращает сырые данные. Белый список программ,
подтверждения опасных действий и лимиты живут в WSL (`safety/`), но мост дополнительно проверяет
токен и стоп-флаг.

---

## 3. Протокол моста

HTTP/1.1 + JSON, порт **8765**, версия API `1`. Все ответы — JSON, кроме `/screenshot` (PNG).

### 3.1. Аутентификация
- Заголовок `X-Pilot-Token: <PILOT_BRIDGE_TOKEN>` в каждом запросе (и в WebSocket, этап 2).
- Токен сравнивается `hmac.compare_digest`. Нет токена → `401`, неверный → `403`.
- Токен задаётся мосту аргументом `--token` или переменной окружения. В репозиторий не попадает;
  WSL-сторона читает его из `.env`, скрипт развёртывания передаёт его процессу моста.

### 3.2. Эндпоинты этапа 0

`GET /health` → `{"ok": true, "version": "1", "host": "...", "port": 8765}`

`GET /status` → 
```json
{"ok": true, "stopped": false, "hotkey": "ctrl+alt+q", "hotkey_registered": true,
 "uptime_s": 12.3, "audio_device": null, "last_error": null}
```

`POST /observe` → тело `{"window": "Блокнот"?, "max_elements": 200, "depth": 6}`:
```json
{
  "ok": true,
  "snapshot_id": 7,
  "active_window": "Без имени — Блокнот",
  "windows": [{"title": "...", "class_name": "Notepad", "process_id": 1234, "rect": [x,y,w,h]}],
  "elements": [
    {"id": 1, "window": "Без имени — Блокнот", "control_type": "Edit", "name": "",
     "automation_id": "", "class_name": "RichEditD2DPT", "rect": [x,y,w,h],
     "enabled": true, "focused": true, "value": "текст"}
  ]
}
```
- `id` — целое, стабильно **в пределах снимка**; следующая `/act` ссылается на `id` из последнего
  `/observe` этого клиента. Мост хранит последний снимок (один на процесс) и считает ссылку
  протухшей, если элемент больше не валиден.
- Элементы обходятся по дереву UIA depth-first с лимитами `max_elements`/`depth`, чтобы не зависать
  на тяжёлых приложениях. Таймаут на снимок — 20 с.

`POST /act` → тело: либо одно действие, либо серия:
```json
{"action": "click", "id": 4}
{"steps": [{"action": "focus_window", "window": "Блокнот"},
           {"action": "type_text", "text": "Привет"}]}
```
Действия этапа 0: `click(id)`, `set_text(id, text)`, `type_text(text)`, `key(keys)`,
`focus(id)`, `focus_window(window)`, `wait(seconds)`. Ответ:
```json
{"ok": true, "executed": 2, "stopped": false, "results": [{"ok": true}, {"ok": true}]}
```
При стопе: `{"ok": false, "stopped": true, "executed": 1, "error": "stopped by hotkey"}`,
HTTP 409. Между шагами серии мост проверяет стоп-флаг.

`GET /screenshot?window=<подстрока>` → PNG (весь экран, если `window` не задан). Заголовки
`X-Rect` и `X-Snapshot-Id`.

`POST /stop` → ставит стоп-флаг (то же, что клавиша). `POST /resume` → снимает.

`POST /play` → `{"pcm_base64": "...", "sample_rate": 24000, "channels": 1}` — PCM16LE в указанное
устройство (`--audio-device`). Ошибка устройства → `503`, мост продолжает работать.

### 3.3. Ошибки
`{"ok": false, "error": "...", "code": "unauthorized|bad_request|stale_element|window_not_found|stopped|internal"}`.
HTTP: 400/401/403/404/409/500/503. Модели и оркестратору отдаётся `error` как текст.

### 3.4. Фокус и ввод

Перед вводом текста оркестратор обязан убедиться, что целевое окно активно
(`/observe → active_window`). pywinauto `set_focus` + `AttachThreadInput` обычно поднимают окно,
но если foreground занят полноэкранной игрой, Windows может не отдать фокус. В этом случае
`set_text` использует `WM_SETTEXT` для Edit/Document (работает без фокуса), а `type_text`
(реальные нажатия) применяется только при подтверждённом фокусе. Надёжный подъём окон —
задача этапа 2.

### 3.5. Развёртывание и запуск моста

`scripts/deploy_bridge.ps1` копирует `win_bridge` в `%LOCALAPPDATA%\pilot-bridge\app`, создаёт
там venv Windows-Python 3.12, ставит зависимости и запускает мост **через `wscript.exe`**
(скрытый `.vbs`-лаунчер). Это не украшение: если запустить python как потомка PowerShell,
вызванного из WSL, `wsl.exe` не вернёт управление, пока жив мост. Токен читается из
`%LOCALAPPDATA%\pilot-bridge\token.txt` (его пишет `scripts/bridge.sh` из `.env`) и передаётся
мосту через переменную окружения процесса, а не аргументом командной строки. PID пишется в
`bridge.pid`; логи — в `%LOCALAPPDATA%\pilot-bridge\logs\bridge.out.log`.

Обёртка для WSL: `scripts/bridge.sh deploy|start|stop|status|logs`.

### 3.6. Стоп-клавиша
- Глобальная `Ctrl+Alt+Q` (`RegisterHotKey`, без прав администратора) в отдельном потоке моста.
- По нажатию: `stop_event` взводится, сервер отвечает `409 stopped` на новые `/act` и обрывает
  текущую серию после текущего шага. `/observe`, `/screenshot`, `/status`, `/stop`, `/resume`
  продолжают работать.
- Если зарегистрировать клавишу не удалось (занята другим приложением), мост пишет предупреждение
  и в `/status` отдаёт `hotkey_registered: false`; оркестратор обязан это проверить до первого
  запуска цикла (правило из AGENTS.md).

---

## 4. Компоненты и модули

```
pilot/
  win_bridge/            # Windows-Python 3.12, отдельный venv
    server.py            # FastAPI: маршруты, токен, стоп-флаг, серии действий
    uia.py               # Desktop(backend="uia"), снимок дерева, поиск окна, ids
    actions.py           # click/set_text/type_text/key/focus/wait через pywinauto
    screenshot.py        # mss: экран/окно → PNG
    audio.py             # sounddevice: PCM16 → устройство
    hotkey.py            # ctypes RegisterHotKey + поток сообщений
    config.py            # аргументы/env: host, port, token, audio device
    run_bridge.py        # точка входа
    requirements.txt
    tests/               # запускаются на Windows-Python
  perception/
    bridge_client.py     # httpx-клиент моста, поиск адреса, ошибки
    (этап 2: cdp.py, vision.py, merge.py)
  scripts/
    deploy_bridge.ps1    # venv, зависимости, запуск/остановка моста
    verify_stage0.py     # проверка критерия этапа 0
  config.yaml            # роли моделей, лимиты, безопасность, запись
  .env                   # локально, в git не попадает
  tests/unit/            # MockTransport, без внешних систем
  tests/integration/     # с живым мостом, @pytest.mark.integration
  runs/<время>/          # журналы и скриншоты сессий
```

Правила: модуль 100–300 строк, одна задача — один модуль, никаких фреймворков агентов.

---

## 5. Модели

Все роли — DeepSeek, OpenAI-совместимый API `https://api.deepseek.com`.

| Роль | Модель | Режим | Зачем |
|------|--------|-------|-------|
| Исполнитель | `deepseek-flash` (V4.1 Flash) | `thinking: {"type": "disabled"}` | Решение на каждом шаге по текстовому наблюдению |
| Планировщик | `deepseek-flash` | `thinking: {"type": "enabled"}`, `reasoning_effort: "high"` | План, диагностика, проверка итога |
| Компилятор | `deepseek-flash` | то же | Генерация и починка навыков |

Факты из официального каталога (проверены по DSH, 23.11.2026): `deepseek-flash` принимает
**текст и изображения**, контекст 1M, `max_tokens` до 384k, поле `max_tokens`, DeepSeek-формат
мышления — `thinking: {"type": "enabled"|"disabled"}` плюс `reasoning_effort`.
Поэтому `planner_images: true` допустим; по умолчанию — `false` (экономим и не зависим от картинок),
включается одной строкой.

Все вызовы — через `models/adapter.py` (этап 3): одна функция `complete(role, messages, schema)`,
которая:
- подставляет модель/режим из `config.yaml`;
- если задана JSON-схема — просит строгий JSON, проверяет, при ошибке повторяет **один** раз с текстом
  ошибки, затем отдаёт ошибку планировщику;
- логирует роль, модель, токены, время в `runs/<время>/session.jsonl`;
- считает бюджет (запросы/токены) и уважает лимиты.

Без ключа `DEEPSEEK_API_KEY` адаптер не стартует и пишет, что именно нужно добавить.

---

## 6. Навыки (этапы 5–6)

Папка `skills/<app>/<name>/`: `skill.py`, `manifest.json`, `check.py`, `log.jsonl`.
- `manifest.json`: `name`, `description`, `params`, `entry` (`api:obs-websocket`, `uia`, `cdp`,
  `cli_config`, `vision`), `app_version`, `version`, `generated`, `fast`/`visible`.
- `check.py` обязателен: без рабочей проверки навык в библиотеку не попадает.
- `run_fast()` — через API/скрытый вход; `run_visible()` — через видимый интерфейс (режим записи).
- Библиотека индексируется один раз при старте; MCP-сервер (`FastMCP`) публикует навыки как
  инструменты, имя — `app.name`.

---

## 7. Наблюдение (этап 2)

Единый текстовый формат для моделей (после слияния UIA + CDP + vision):

```
[окно] OBS 33.0.0 (focused)
  [1] кнопка "Начать запись"
  [2] кнопка "Настройки"
  [3] микшер "Звук раб. стола" 0.0 dB
[окно] Ошибка: "Устройство не найдено"
  [4] кнопка "OK"
```

- Номера стабильны в пределах шага; координаты пикселей — только для входа `vision`.
- Приоритет источников: UIA → CDP/DOM → vision. Один элемент из разных источников склеивается
  по bounds/name (`perception/merge.py`).
- События UIA (этап 2) — через WebSocket `/events` моста: открылось/закрылось окно, изменилось
  значение, появился диалог. Агент реагирует на событие, а не опрашивает экран в цикле.

---

## 8. Безопасность

1. Стоп-клавиша регистрируется до старта цикла; `/status.hotkey_registered` проверяется оркестратором.
2. Токен моста обязателен; мост слушает только локальный WSL-адрес (или `127.0.0.1` в mirrored).
3. Белый список `config.yaml → safety.allowed_apps` проверяется в WSL **до** вызова моста
   (по заголовку/классу/имени процесса из `/observe`); вне списка — отказ.
4. Опасные действия (`delete`, `send`, `publish`, `pay`, смена системных настроек) — только после
   явного подтверждения пользователя в консоли; проверка в коде, не в промпте.
5. Лимиты на запуск: `max_steps`, `max_seconds`, `max_model_calls`, `max_tokens` — из `config.yaml`,
   по умолчанию консервативные.
6. Тестовые записи — только в `D:\Video\recordly\pilot-tests\`, чужие файлы не трогаем.
7. Конфиги OBS — не править при запущенном OBS; при необходимости бэкап в `backups/<дата>/`.

---

## 9. Тесты

- `tests/unit/` — без внешних систем, всегда. Ответы моделей — записанные фикстуры.
- `tests/integration/` — с живыми OBS/окнами/API, `@pytest.mark.integration`, `skip` с причиной,
  если мост/ключ/программа отсутствуют.
- `win_bridge/tests/` — на Windows-Python (pytest), без поднятого сервера где возможно.
- `scripts/verify_stageN.py` — перезапускаемая проверка критерия этапа; вывод прикладывается
  к отчёту.

---

## 10. Этап 0: детальный план (выполнен 23.11.2026)

**Цель:** из WSL управлять окнами Windows через мост, безопасно и с работающей стоп-клавишей.
Статус: `STAGE 0: PASS`, подробности и артефакты — в `PROGRESS.md`. Раздел оставлен как
справочник по критериям и как шаблон для `verify_stageN.py`.

Шаги:
1. Скелет репозитория, `config.yaml`, `.env`, `.gitignore`, venv.
2. `win_bridge`: сервер, токен, UIA-снимок, действия, скриншот, hotkey, `/play`.
3. `perception/bridge_client.py`: адрес (env → localhost → gateway), токен, ошибки, таймауты.
4. `scripts/deploy_bridge.ps1`: копирование, venv на Windows, pip install, запуск с `--host`/`--token`.
5. `scripts/verify_stage0.py`:
   - `/health` и `/status` (hotkey зарегистрирован);
   - запуск Блокнота;
   - `/observe` → найден Edit;
   - `/act` type_text → текст реально в поле (UIA value или проверка через буфер обмена);
   - `/screenshot` → PNG, проверка размера и размеров кадра через ffprobe;
   - серия `/act` из 40 `wait` → нажатие `Ctrl+Alt+Q` из PowerShell → ответ `409 stopped`,
     `executed < 40`; затем `/resume` и повторная проверка, что действия снова работают.
6. `PROGRESS.md` + отчёт.

**Готово, когда** `python scripts/verify_stage0.py` печатает `STAGE 0: PASS`, а в `runs/` лежат
скриншот и JSON-лог проверки.

Проверено вручную (не автоматизируется): закрыть/открыть окно во время работы, поведение при
занятой стоп-клавише, реальный пользовательский экран.

---

## 11. Уточнения по следующим этапам

- **1. Запись и голос.** OBS через `obsws-python`; дорожки: 1 — система, 2 — голос агента (VB-Cable),
  3 — микрофон. ElevenLabs streaming (`eleven_flash_v2_5`), очередь реплик, кеш частых фраз по хешу
  текста+голоса. `/play` в мосту принимает PCM16 чанки. Проверка файла: `ffprobe` — число дорожек,
  `silencedetect` — звук в каждой. Нужны: VB-Cable, `ELEVENLABS_API_KEY`, obs-websocket + пароль.
- **2. Восприятие.** `/observe` уже отдаёт дерево; добавляем CDP через Playwright (attach к Chrome/
  Electron по `--remote-debugging-port`), слияние и текстовый рендер, WebSocket `/events`.
- **3. Исполнитель.** `agents/executor.py`, строгая JSON-схема шага, `expect` и правила эскалации
  (2 подряд не сбывшихся `expect` или 3 шага без прогресса → планировщик).
- **4. Планировщик.** `agents/planner.py`, OmniParser локально (сначала CPU; ROCm/DirectML — решить
  по факту на этапе 9, записать в PROGRESS).
- **5. Навыки и MCP.** Формат из раздела 6, `FastMCP`, инструменты с именами навыков.
- **6. Разведчик и компилятор.** Журнал разведки JSONL; компилятор генерирует `skill.py`+`check.py`,
  гоняет проверку до зелёного, лимит итераций 5.
- **7. Сайты.** Playwright: headless в WSL («Сделай»), Chrome на Windows по CDP («Покажи»);
  перехват XHR/fetch → навык на внутреннем API; профиль сессии хранится локально.
- **8. «Покажи и запиши».** `run_visible()`, синхронизация «реплика → действие», стоп-проверка
  файла после записи.
- **9. Зрение.** OmniParser/UI-TARS; выбор CPU/ROCm/DirectML фиксируется в PROGRESS.
- **10. Самовосстановление.** Счётчик ошибок в `log.jsonl`; 2 ошибки подряд → переразведка навыка.

---

## 12. Что нужно от пользователя

1. Решить про постоянное монтирование `/mnt/c` и `/mnt/d` (пункт 1.2).
2. Когда будет удобно — включить mirrored networking (`.wslconfig`, затем `wsl --shutdown`);
   это перезапустит WSL и завершит текущие сессии DSH.
3. Установить VB-Cable (системный драйвер) — этап 1.
4. Включить obs-websocket в OBS и задать пароль (`OBS_WS_PASSWORD`).
5. Добавить ключи в переменные окружения WSL: `DEEPSEEK_API_KEY`, `ELEVENLABS_API_KEY`,
   `ELEVENLABS_VOICE_ID`, `OBS_WS_PASSWORD`, `PILOT_BRIDGE_TOKEN` (токен моста генерируется и
   задаётся на этапе 0 автоматически в `.env`).
6. Уточнить, куда OBS реально пишет записи: `D:\Video` или `D:\Video\recordly`.
