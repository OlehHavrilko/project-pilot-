# PROGRESS

Обновлено: 23.11.2026.

## Текущий этап

**Этап 0 «WSL и мост» — ГОТОВО, проверено запуском.**

```
$ .venv/bin/python scripts/verify_stage0.py
[PASS] bridge answers /status — http://172.23.112.1:8765
[PASS] stop hotkey registered — ctrl+alt+q
[PASS] Notepad window observed
[PASS] editable element found — 86 elements, control_type=Document
[PASS] text typed into Notepad — keyboard (type_text)
[PASS] screenshot captured — 98751 bytes, frame 2400,1279
[PASS] stop hotkey aborts action series — executed 6 of 40
[PASS] aborted before the end — 6
[PASS] bridge reports stopped state
[PASS] actions work again after resume
STAGE 0: PASS
```

Артефакты: `runs/stage0-2026-11-23_06-48-46/` (`notepad.png`, `observe.json`, `verify.json`).
Юнит-тесты: 6 passed. `ruff check .` — чисто.

## Что сделано

- Репозиторий `~/pilot` (git инициализирован, коммитов пока нет).
- `TECH_SPEC.md` — уточнённое ТЗ: протокол моста, роли DeepSeek, этапы, проверки.
- Windows-мост `win_bridge/` (FastAPI + pywinauto UIA + mss + sounddevice + RegisterHotKey):
  - токен `X-Pilot-Token` на каждом запросе, `health`/`status`/`observe`/`act`/`screenshot`/`play`/`stop`/`resume`;
  - UIA-снимок с номерами элементов и стабильными id в пределах снимка;
  - действия: `click`, `set_text`, `type_text`, `key`, `focus`, `focus_window`, `wait`, серии шагов;
  - `Ctrl+Alt+Q` обрывает серию (проверено: 6 из 40 шагов);
  - `PILOT_BRIDGE_LOG` — перенаправление логов в файл.
- WSL-клиент `perception/bridge_client.py`: токен из env/`.env`, поиск адреса
  (`PILOT_BRIDGE_URL` → `127.0.0.1` → шлюз WSL), типизированные ошибки, `BridgeStopped`.
- Деплой `scripts/deploy_bridge.ps1` + обёртка `scripts/bridge.sh`:
  venv на Windows, pip install, запуск через `wscript.exe` (скрыто, вне процесса WSL),
  PID-файл, health-wait, `stop`/`status`/`logs`.
- Верификация `scripts/verify_stage0.py` (Notepad, текст, скриншот, стоп-клавиша).
- В WSL установлены `python3-venv`, `python3-pip`, `ffmpeg`/`ffprobe` (6.1.1).

## Окружение (проверено)

| Что | Факт |
|-----|------|
| WSL | Ubuntu 24.04, Python 3.12.3, WSL2 |
| Windows | Windows 11 Pro, пользователь `hvrlkoPC`, PowerShell 5.1 |
| Windows-Python | 3.12.10 (`%LOCALAPPDATA%\Programs\Python\Python312`) |
| Мост | `%LOCALAPPDATA%\pilot-bridge` (app, venv, logs, token.txt, bridge.pid) |
| Адрес моста | `172.23.112.1:8765` (IP vEthernet WSL, NAT-режим) |
| OBS | 33.0.0, конфиги и бэкап на месте, obs-websocket выключен |
| VB-Cable | не установлен |
| Ключи | `DEEPSEEK_API_KEY`, `ELEVENLABS_API_KEY`, `OBS_WS_PASSWORD` не заданы |

## Известные проблемы и решения

- **Целевая платформа — Windows, WSL только для разработки** (23.11.2026, `PROJECT_PILOT.md` п. 2.8,
  `AGENTS.md` п. 2.0, добавлен этап 11). Код мозга должен оставаться кроссплатформенным.
  `perception/bridge_client.py: windows_host()` вызывает `ip route` (WSL-only). На Windows это
  безопасно падает в `127.0.0.1`, но при выносе в профили конфига его стоит перенести в dev-профиль.

- `/mnt/c` и `/mnt/d` не монтируются автоматически (`/etc/wsl.conf`: `automount=false`).
  Сейчас смонтированы вручную; после перезапуска WSL их нужно монтировать снова либо включить
  automount/fstab. Вопрос пользователю — в `TECH_SPEC.md`, п. 1.2.
- Mirrored networking выключен. Работает fallback: мост слушает `172.23.112.1`, WSL ходит на него.
  Переход на mirrored требует `wsl --shutdown` (убьёт текущую DSH-сессию), делать между сессиями.
- **Фокус окон.** Если foreground занят полноэкранной игрой (в тесте — World of Warcraft),
  `SetForegroundWindow` может не сработать. `verify_stage0.py` в этом случае пишет текст через
  `WM_SETTEXT` и честно указывает способ. Для этапа 2 нужно добавить надёжный подъём окна
  (AttachThreadInput уже используется, но не всегда достаточно).
- **Запуск моста.** Если запускать python напрямую из PowerShell, вызванного из WSL, `wsl.exe`
  не возвращает управление, пока жив потомок. Поэтому используется `wscript.exe` + скрытый VBS.
- Записи OBS фактически лежат в `D:\Video`, а не в `D:\Video\recordly` (там приложение Recordly).
  Уточнить путь в `basic.ini` на этапе 1.
- Тестовые Блокноты, открытые проверкой, закрываются скриптом; чужие файлы не трогались.

## Требуется от пользователя (этап 1+)

1. Решить, включать ли постоянное монтирование `/mnt/c` и `/mnt/d`.
2. В удобный момент включить mirrored networking и перезапустить WSL.
3. Установить VB-Cable и выбрать его устройством вывода для голоса агента.
4. Включить obs-websocket в OBS и задать пароль; добавить `OBS_WS_PASSWORD` в WSL.
5. Добавить `DEEPSEEK_API_KEY` и `ELEVENLABS_API_KEY` (+`ELEVENLABS_VOICE_ID`) в окружение WSL.
6. Подтвердить, куда OBS пишет записи.

## Следующий шаг

Этап 1 «Запись и голос»: obs-websocket (старт/стоп/сцены), ElevenLabs streaming в WSL,
PCM-чанки в мост → VB-Cable, отдельные дорожки, автоматическая проверка MKV через ffprobe
и `silencedetect`. Начать с проверки доступности OBS websocket и установки VB-Cable.
