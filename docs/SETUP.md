# Настройка окружения «Пилота» (этап 1)

Короткий чек-лист того, что нужно сделать руками на Windows/WSL. Всё, что можно
сделать скриптами, делаю я; здесь — только системные вещи: драйверы, OBS, ключи.

Порядок: **VB-Cable → OBS (источники, дорожки, obs-websocket) → ключи в `.env` →
(по желанию) mirrored networking и автомонтирование дисков**.

---

## 1. VB-Cable — виртуальное аудиоустройство для голоса агента

Зачем: голос локального синтезатора Piper должен попасть в запись отдельной дорожкой, а не смешаться
со звуком системы. Мост играет PCM в `CABLE Input`, OBS слушает `CABLE Output`.

1. Скачать: <https://vb-audio.com/Cable/> → *Download* (VBCABLE_Driver_Pack).
2. Распаковать, запустить **`VBCABLE_Setup_x64.exe` от имени администратора** →
   *Install Driver*.
3. Перезагрузить Windows.
4. Проверить в «Параметры → Система → Звук»:
   - воспроизведение: `CABLE Input (VB-Audio Virtual Cable)`;
   - запись: `CABLE Output (VB-Audio Virtual Cable)`.

**Важно:** не делать `CABLE Input` устройством по умолчанию, иначе звук системы
уйдёт «в кабель» и его не будет слышно. Если Windows сам переключил — вернуть
динамики/наушники устройством по умолчанию.

Мост выбирает устройство по имени из `config.yaml → voice.output_device` («CABLE Input»),
менять устройство по умолчанию не нужно.

---

## 2. OBS: источники и дорожки

Схема дорожек (из ТЗ):

| Дорожка | Что | Источник в OBS |
|---------|-----|----------------|
| 1 | звук системы | «Звук раб. стола» (уже есть) |
| 2 | голос агента | новый «Захват ввода звука» → `CABLE Output` |
| 3 | микрофон пользователя | «Микро» (уже есть) |

Действия:

1. В OBS добавить источник **«Захват ввода звука»** (Audio Input Capture),
   устройство — `CABLE Output (VB-Audio Virtual Cable)`, имя — `Голос Пилота`.
2. **Правка → Расширенные свойства звука** (Edit → Advanced Audio Properties):
   - «Звук раб. стола» — только дорожка **1**;
   - «Голос Пилота» — только дорожка **2**;
   - «Микро» — только дорожка **3**.
   Остальные галочки снять.
3. **Настройки → Вывод → Запись** (Settings → Output → Recording):
   включить аудиодорожки **1, 2 и 3** (сейчас в `basic.ini` включены только 1 и 2,
   `RecTracks=3`; нужно 7).
4. Убедиться, что «Скрыть OBS от захвата экрана» выключено (Настройки → Общие) —
   уже сделано в прошлой сессии.
5. Записать короткий тест (30 секунд), не закрывая OBS. Проверим файл через ffprobe:
   три дорожки, в каждой есть звук.

Конфиги OBS вручную не править при запущенном OBS — только через интерфейс
(или позже через obs-websocket).

---

## 3. obs-websocket — управление записью из кода

1. OBS → **«Сервис» → «Настройки WebSocket-сервера»** (Tools → WebSocket Server Settings).
2. Включить **WebSocket-сервер**, порт `4455`.
3. Включить **аутентификацию** и задать пароль. Пароль нужен только проекту;
   в чат его не присылать.
4. ОК. Перезапуск OBS не требуется.

Проверка из WSL:

```bash
HOST=$(ip route show default | awk '/via/{print $3;exit}')
curl -s -o /dev/null -w '%{http_code}\n' "http://$HOST:4455"
```

Ожидаемо `400`/`426` (сервер ответил, но это не HTTP-запрос), а не `000`.
Если `000` — Windows Firewall блокирует: разрешить OBS в частных сетях.

---

## 4. Ключи API в `.env`

Ключи лежат в `~/pilot/.env` (в git не попадает, права 600). Через чат их не присылать.

```bash
nano ~/pilot/.env
```

Добавить:

```dotenv
DEEPSEEK_API_KEY=sk-...
OBS_WS_PASSWORD=...
```

Голос локальный (Piper), ключ для него не нужен.

Где взять:

- **DeepSeek** — <https://platform.deepseek.com> → API Keys → Create. Модель
  `deepseek-flash`, нужен положительный баланс.
- **Голос (Piper)** — бесплатно и офлайн. Установка и голос:

  ```bash
  cd ~/pilot
  .venv/bin/pip install -e '.[voice]'
  .venv/bin/python -m piper.download_voices ru_RU-irina-medium --download-dir models/piper
  ```

  Другие русские голоса: `ru_RU-denis-medium`, `ru_RU-dmitri-medium`, `ru_RU-ruslan-medium`.
  Проверка синтеза: `.venv/bin/python scripts/verify_voice.py`.

Проверить, что ключи на месте (без вывода значений):

```bash
cd ~/pilot && for v in DEEPSEEK_API_KEY OBS_WS_PASSWORD; do
  grep -q "^$v=..*" .env && echo "$v: ok" || echo "$v: MISSING"
done
```

---

## 5. Mirrored networking (желательно, но можно отложить)

Сейчас WSL ходит на Windows по адресу `172.23.112.1` — мост уже так работает.
Mirrored networking делает `localhost` общим для WSL и Windows: проще с OBS,
CDP и будущими интеграциями.

Отредактировать `C:\Users\hvrlkoPC\.wslconfig` (сохранив `swapFile`):

```ini
[wsl2]
swapFile=D:\\WindowsSysLinux\\wsl-swap.vhdx
networkingMode=mirrored
```

Затем в PowerShell: `wsl --shutdown`.

**Внимание:** это завершит текущую DSH-сессию (она работает в WSL). Делать, когда
сессия не нужна, потом открыть DSH заново. Мост на Windows при этом продолжит работать.

Проверка после перезапуска: `curl http://localhost:8765/health` (с токеном) и
`curl http://localhost:4455` для OBS.

---

## 5.1. GPU-голос: Kokoro-ru на AMD ROCm (Windows)

Piper работает на CPU (~10x realtime), но если нужен голос лучше и на видеокарте —
есть **Kokoro-ru** (82M, 3 русских голоса, OpenRAIL). Проверено на **RX 9060 XT 16 ГБ**:
`device cuda`, тёплый синтез **RTF ≈ 0,12** (8,5 с речи за ~1 с), 24 кГц.

Установка (Windows PowerShell; Python 3.12):

```powershell
# ROCm PyTorch под gfx1200 (RX 9060 XT), ставится один раз, несколько ГБ
C:\Users\hvrlkoPC\AppData\Local\Programs\Python\Python312\python.exe -m venv %LOCALAPPDATA%\pilot-voice
%LOCALAPPDATA%\pilot-voice\Scripts\python.exe -m pip install --index-url https://stable.repo.amd.com/rocm/whl-next/ "torch[device-gfx1200]==2.15.0+rocm10.2.0"

# зависимости Kokoro и русский G2P
%LOCALAPPDATA%\pilot-voice\Scripts\python.exe -m pip install kokoro "misaki[en]" ruaccent numpy onnxruntime-directml huggingface_hub
```

Или одним скриптом из репозитория (создаст venv, поставит всё, скачает ассеты, прогонит бенч):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_kokoro_gpu.ps1
```

Ассеты (модель + голоса + acute-aware espeak) качаются в `%LOCALAPPDATA%\pilot\kokoro`
командой `python scripts/fetch_kokoro_assets.py --asset-dir ...`. Проверка:

```powershell
$env:PYTHONUTF8 = "1"
%LOCALAPPDATA%\pilot-voice\Scripts\python.exe scripts\bench_kokoro.py --asset-dir %LOCALAPPDATA%\pilot\kokoro
```

Ожидаемо: `"device": "cuda"`, `"best_rtf": ~0.12`, `KOKORO: PASS`.

Примечания:
- Первый синтез после запуска долгий (~30 с) — компиляция ядер MIOpen; warmup уже встроен.
- На RDNA4 MIOpen падает на `instance_norm`; бэкенд подменяет его на нативный расчёт.
- Лицензия: код Apache-2.0, веса OpenRAIL; для коммерции проверь условия OpenRAIL.

## 6. Автомонтирование дисков Windows (по желанию)

Сейчас `/etc/wsl.conf` содержит `automount=false`, поэтому после каждого перезапуска
WSL диски нужно монтировать вручную:

```bash
sudo mount -t drvfs C: /mnt/c && sudo mount -t drvfs D: /mnt/d
```

Чтобы не делать это каждый раз — в `/etc/wsl.conf` поставить `enabled = true`
в секции `[automount]` (или добавить строки в `/etc/fstab`), затем `wsl --shutdown`.
Это настройка твоей системы — решай сам; без неё скрипты просто попросят смонтировать.

---

## Что проверю я после «готово»

1. `/status` моста: `audio_available`, устройство `CABLE Input`.
2. Подключение к obs-websocket, версия OBS, старт/стоп записи.
3. Один пробный вызов DeepSeek и локальный синтез Piper (короткая фраза в PCM, `scripts/verify_voice.py`).
4. Тестовая запись 30 секунд: три дорожки, `ffprobe` + `silencedetect` по каждой.
5. Обновлю `PROGRESS.md`, закоммичу и запушу этап 1 веткой `stage-1-recording-voice`.

## Если что-то не получается

- VB-Cable не появился — проверь, что установщик запускался от админа, и перезагрузись.
- OBS не видит `CABLE Output` — перезапусти OBS после установки драйвера.
- `curl` на 4455 даёт `000` — файрвол; разреши OBS в частных сетях.
- Ключ не подхватился — проверь `.env` (без кавычек, без пробелов вокруг `=`).
