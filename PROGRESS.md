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
- Локальный голос: `voice/` (Piper + очередь + кеш), `scripts/verify_voice.py`; мост держит
  аудиопоток открытым и умеет dry-run (`--audio-dry-run`, `PILOT_AUDIO_DRY_RUN`).
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
| Ключи | `DEEPSEEK_API_KEY`, `OBS_WS_PASSWORD` не заданы; голос локальный (Piper), ключ не нужен |

## Известные проблемы и решения

- **Голос: ElevenLabs заменён на локальный Piper** (23.11.2026). Бесплатно, офлайн, без ключей и
  лимитов. Реализовано: `voice/piper_backend.py`, `voice/speaker.py` (очередь + кеш), мост держит
  аудиопоток открытым; проверено `scripts/verify_voice.py`: 6,6 с речи синтезируются за 0,59 с
  (RTF 0,09), 22,05 кГц моно, 3 чанка. Поток в мост проверен в dry-run (мост без VB-Cable):
  все байты дошли. Осталось проиграть в реальный VB-Cable после его установки.
- **GPU-голос проверен на RX 9060 XT (16 ГБ, gfx1200).** ROCm PyTorch 2.15.0+rocm10.2.0
  на Windows Python 3.12: `torch.cuda.is_available() = True`. Kokoro-ru (82M, голос sveta)
  на GPU: тёплый синтез 8,5 с речи за ~1,0 с, **RTF ≈ 0,12**, 24 кГц; первый запуск ~32 с
  (компиляция MIOpen, закрывается warmup). Обход бага MIOpen: нативная замена
  `instance_norm` (RDNA4). Ассеты и venv — в `%LOCALAPPDATA%\pilot\kokoro` и
  `%LOCALAPPDATA%\pilot-voice`.

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
- **Путь записей OBS расходится.** Вчерашние логи (`logs/2026-11-22 23-27-15.txt`) пишут
  `D:/Video/recordly/2026-11-22 23-27-15.mkv`, сейчас в `basic.ini` стоит `RecFilePath=D:/Video`,
  а сами тестовые `.mkv` лежат в `D:\Video`. Папка `D:\Video\recordly` занята приложением Recordly.
  На этапе 1 привести путь к одному значению (настройки/obs-websocket) и писать тесты в `pilot-tests`.
- Тестовые Блокноты, открытые проверкой, закрываются скриптом; чужие файлы не трогались.

## Требуется от пользователя (этап 1+)

1. Решить, включать ли постоянное монтирование `/mnt/c` и `/mnt/d`.
2. В удобный момент включить mirrored networking и перезапустить WSL.
3. Сменить пароль obs-websocket в OBS (старый засветился в скриншоте) и обновить `.env`.
4. Добавить `DEEPSEEK_API_KEY` в окружение WSL. Ключ для голоса не нужен.
5. Подтвердить единый путь записей OBS (`D:\Video` сейчас; `recordly\pilot-tests` — по ТЗ).

## Следующий шаг

Этап 2 «Восприятие»: единое наблюдение UIA + CDP, текстовый формат с номерами элементов,
подписка на события Windows. Для OBS, Discord и Проводника — понятный список элементов.
