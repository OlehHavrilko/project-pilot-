# «Пилот»

Агент, который управляет компьютером под Windows из WSL, накапливает библиотеку навыков
и записывает видео с живой озвучкой (локальный TTS: Piper на CPU, Kokoro-ru на GPU). Полное описание — `PROJECT_PILOT.md`, технический
проект — `TECH_SPEC.md`, статус — `PROGRESS.md`, правила работы — `AGENTS.md`.

## Требования

- WSL2 Ubuntu 24.04, Python 3.12, `ffmpeg`/`ffprobe` из apt.
- Windows 11, Python 3.12 на Windows-стороне.
- Смонтированные диски Windows: `sudo mount -t drvfs C: /mnt/c && sudo mount -t drvfs D: /mnt/d`
  (в `/etc/wsl.conf` сейчас `automount=false`).
- `PILOT_BRIDGE_TOKEN` в `.env` (уже сгенерирован локально), там же ключи `DEEPSEEK_API_KEY`
  и `OBS_WS_PASSWORD` (по мере надобности). Внешний TTS-ключ не нужен.

## Быстрый старт

```bash
cd ~/pilot
python3 -m venv .venv
.venv/bin/pip install -e '.[dev,voice]'
.venv/bin/python -m piper.download_voices ru_RU-irina-medium --download-dir models/piper

./scripts/bridge.sh deploy        # развернуть и запустить Windows-мост
./scripts/bridge.sh status        # состояние и health
.venv/bin/python scripts/verify_stage0.py   # проверка этапа 0
.venv/bin/python scripts/verify_voice.py    # локальный голос: синтез + WAV
.venv/bin/python scripts/verify_stage1.py   # запись 30 с через OBS + проверка дорожек
.venv/bin/python scripts/verify_models.py   # DeepSeek: executor + planner
```

GPU-голос на Windows (AMD ROCm, Kokoro-ru, ~8x realtime): см. `docs/SETUP.md`, раздел
«GPU-голос». Коротко: `scripts/setup_kokoro_gpu.ps1`.

Проверка этапа 0 должна закончиться `STAGE 0: PASS`, артефакты — в `runs/stage0-*`
(`notepad.png`, `observe.json`, `verify.json`).

## Структура

```
win_bridge/        Windows-мост (Windows-Python): UIA, действия, скриншоты, звук, стоп-клавиша
perception/        клиент моста из WSL (позже: CDP, vision, слияние наблюдений)
voice/             локальный TTS: Piper (CPU) / Kokoro-ru (GPU), очередь, кеш
scripts/           deploy_bridge.ps1, bridge.sh, verify_stageN.py
tests/             unit (без внешних систем) и integration
config.yaml        роли моделей, лимиты, безопасность, запись
models/            адаптер DeepSeek (роли, thinking, JSON-схемы, бюджет)
runs/              журналы и скриншоты проверок (в git не попадает)
```

## Как это работает

- WSL думает: модели, навыки, оркестратор.
- `win_bridge` — тонкий сервис на Windows: HTTP/JSON на `127.0.0.1:8765` (или на адрес
  WSL-vEthernet в NAT-режиме), токен в заголовке `X-Pilot-Token`. Внутри — только UIA,
  ввод, скриншоты, воспроизведение PCM и глобальная стоп-клавиша `Ctrl+Alt+Q`.
- Мост запускается скриптом `scripts/bridge.sh deploy` через `wscript.exe` в скрытом режиме:
  иначе `wsl.exe` ждёт процесс-потомок и деплой «висит».
- Голос синтезирует `voice/piper_backend.py` (Piper, ONNX, CPU), `voice/speaker.py` держит очередь и
  кеш и отправляет PCM-чанки в `/play` моста; мост выводит их в VB-Cable, не закрывая поток.

## Безопасность

- Стоп-клавиша `Ctrl+Alt+Q` регистрируется до первого действия; её статус отдаёт `/status`.
- Токен обязателен для всех запросов; мост не слушает внешние адреса.
- `config.yaml → safety.allowed_apps` — белый список программ; опасные действия требуют
  подтверждения пользователя (проверка в коде, не в промпте).
- Ключи API — только в переменных окружения; `.env` в `.gitignore`. Голос локальный, ключей не требует.

## Тесты

```bash
.venv/bin/python -m pytest          # unit-тесты
.venv/bin/ruff check .              # линт
```