# PROGRESS

Обновлено: 23.11.2026.

## Текущий этап

**Этап 2 «Восприятие» — ГОТОВО, проверено запуском.**

```
[PASS] OBS window observed — 932 chars
[PASS] OBS elements are readable
[PASS] Explorer window observed — 1099 chars
[PASS] Explorer elements are readable
[PASS] Discord CDP snapshotted — 1812 chars
[PASS] Discord elements are readable
[PASS] window_open event received — «Без имени — Блокнот»
[PASS] window_close event received
STAGE 2: PASS
```

Артефакты: `runs/stage2-2026-11-23_08-23-54/` (`obs.txt`, `explorer.txt`, `discord.txt`,
`verify.json`).

**Этап 1 «Запись и голос» — ГОТОВО.**

```
[PASS] OBS websocket connected — OBS 33.0.3
[PASS] recording tracks 1+2+3 enabled — RecTracks=7
[PASS] system audio on track 1 / agent voice on track 2 / microphone on track 3
[PASS] bridge plays into VB-Cable — CABLE Input
[PASS] recording started / stopped
[PASS] audio streams >= 2 — 3 audio tracks
[PASS] system track has sound — [1.0, 10.7, 0.0]
[PASS] voice track has sound — 10.7 s
STAGE 1: PASS
```

Файл: `D:\Video\2026-11-23 10-13-30.mkv` (32,6 с, 3 дорожки).

**Этап 0 «WSL и мост» — ГОТОВО.**

```
[PASS] bridge answers /status
[PASS] stop hotkey registered — ctrl+alt+q
[PASS] Notepad window observed / editable element found
[PASS] text typed into Notepad — keyboard (type_text)
[PASS] screenshot captured — 98751 bytes, frame 2400,1279
[PASS] stop hotkey aborts action series — executed 6 of 40
[PASS] actions work again after resume
STAGE 0: PASS
```

Артефакты: `runs/stage0-2026-11-23_06-48-46/`.

## Что сделано

- Репозиторий `~/pilot`, GitHub `OlehHavrilko/project-pilot-` (main ведётся по этапам).
- `TECH_SPEC.md` — уточнённое ТЗ: протокол моста, роли DeepSeek, этапы, проверки.
- Windows-мост `win_bridge/`:
  - FastAPI + токен `X-Pilot-Token`; `health`/`status`/`observe`/`act`/`screenshot`/`play`/`stop`/`resume`;
  - UIA-снимок с номерами, действия `click`/`set_text`/`type_text`/`key`/`focus`/`focus_window`/`wait`, серии;
  - `Ctrl+Alt+Q` обрывает серию; `PILOT_BRIDGE_LOG`; запуск через `wscript.exe` (иначе WSL ждёт процесс);
  - WebSocket `/events`: `window_open` / `window_close` / `focus` (поллинг списка окон, 0,5 с);
  - аудиопоток в `CABLE Input` без разрыва между PCM-чанками, `--audio-dry-run`.
- `perception/`:
  - `bridge_client.py` — клиент моста, поиск адреса, `watch_events`, типизированные ошибки;
  - `render.py` — компактный текст с `[id]` для UIA и CDP AX-дерева;
  - `cdp.py` — снимок accessibility tree по CDP (без Playwright), список целей.
- `recording/obs_client.py` — obs-websocket: старт/стоп, `RecTracks=7`, маршрутизация источников.
- `voice/` — Piper (CPU) и Kokoro-ru (GPU, ROCm Windows), очередь, кеш, поток в мост.
- `models/adapter.py` — DeepSeek: роли, thinking, JSON-схема с одним повтором, бюджет.
- Скрипты проверок: `verify_stage0.py`, `verify_stage1.py`, `verify_stage2.py`, `verify_voice.py`,
  `verify_models.py`; dev-прокси `scripts/cdp_proxy.py` для CDP из WSL.
- В WSL установлены `python3-venv`, `python3-pip`, `ffmpeg`/`ffprobe`; Python-зависимости в `.venv`.

## Окружение (проверено)

| Что | Факт |
|-----|------|
| WSL | Ubuntu 24.04, Python 3.12.3 |
| Windows | Windows 11 Pro, пользователь `hvrlkoPC`, PowerShell 5.1 |
| Windows-Python | 3.12.10; GPU-venv `%LOCALAPPDATA%\pilot-voice` |
| GPU | AMD Radeon RX 9060 XT 16 ГБ (gfx1200), ROCm PyTorch 2.15.0+rocm10.2.0 |
| Мост | `%LOCALAPPDATA%\pilot-bridge`, `172.23.112.1:8765`, `CABLE Input` |
| OBS | 33.0.3, obs-websocket 5.7.6 включён, `RecTracks=7` |
| VB-Cable | установлен |
| Ключи | `OBS_WS_PASSWORD`, `DEEPSEEK_API_KEY` в `.env` (не в git) |
| CDP | Discord на 9223, Helium на 9222, dev-прокси в WSL |

## CDP в dev-режиме

- Chromium/Electron слушает `--remote-debugging-port` только на `127.0.0.1`; WSL в NAT его не видит.
  Для разработки запускается `pythonw scripts/cdp_proxy.py --listen-port 9222 --target-port 9222`
  (для Discord — 9223), который пересылает с адреса vEthernet.
- Discord нужно запускать с `--remote-debugging-port=9223`; сейчас так и запущен.
- На целевой Windows-сборке мозг и мост на одной машине, прокси не нужен.

## Известные проблемы и решения

- `/mnt/c`, `/mnt/d` не монтируются автоматически (`automount=false`); сейчас смонтированы вручную.
- Mirrored networking выключен; работаем через `172.23.112.1` и dev-прокси.
- **Пароль obs-websocket засветился** в скриншоте, который попал в git. Файл удалён, история
  ветки переписана, но пароль нужно сменить в OBS и обновить `.env`.
- **Микрофонная дорожка** в тесте этапа 1 пустая (0 с) — микрофон тихий/выключен; для критерия
  не требуется, вернёмся на этапе 8.
- **OBS может быть свёрнут в трей** без окна; для UIA-наблюдения окно нужно открыть (в тесте
  OBS перезапущен).
- **Фокус окон**: если foreground занят игрой, `SetForegroundWindow` может не сработать;
  `verify_stage0.py` в этом случае использует `WM_SETTEXT`.
- Записи OBS идут в `D:\Video`; тесты — туда же, по ТЗ позже `pilot-tests`.
- Kokoro на RDNA4: MIOpen падает на `instance_norm`, бэкенд подменяет его нативным расчётом;
  первый синтез ~30 с (warmup).

## Требуется от пользователя

1. Сменить пароль obs-websocket в OBS (старый засветился) и обновить `.env`.
2. Решить про постоянное монтирование дисков и mirrored networking (по желанию).
3. Подтвердить единый путь записей OBS (`D:\Video` сейчас; `recordly\pilot-tests` — по ТЗ).

## Следующий шаг

Этап 3 «Исполнитель»: цикл наблюдение → решение → действие, действия через мост, `expect`,
эскалация к планировщику после повторных неудач, лимиты шагов/времени.
