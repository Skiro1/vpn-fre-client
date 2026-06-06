# VPN Client v2.0.0

Десктоп-приложение для Windows с графическим интерфейсом, объединяющее четыре независимых движка обхода блокировок в одном окне:

| Движок | Тип | Назначение |
|---|---|---|
| **Opera Proxy** | HTTP-прокси (127.0.0.1:18080) | Бесплатный прокси-выход с выбором региона |
| **Hola Proxy** | HTTP-прокси (127.0.0.1:24080) | Альтернативный прокси без регистрации |
| **Cloudflare WARP** | L3-туннель (AmneziaWG) | Замена IP на адрес Cloudflare |
| **Zapret DPI bypass** | Пакетный фильтр (WinDivert) | Обход DPI без смены IP |

Движки комбинируются: WARP и Zapret работают одновременно с любым прокси.

![Screenshot](IMG/IMG.png)

---

## Скачивание

Готовые сборки публикуются в [GitHub Releases](../../releases) — single-file `VPN-Client.exe` (~45 МБ), все зависимости внутри.

Версия соответствует тегу в `vpn_client.py:APP_VERSION`. Контрольные суммы — в файле `SHA256SUMS.txt` рядом с архивом.

## Системные требования

| Компонент | Минимум | Рекомендуется |
|---|---|---|
| ОС | Windows 10 (1809) | Windows 10 22H2 / Windows 11 |
| Архитектура | x64 | x64 |
| Свободное место | 100 МБ | 200 МБ (для логов) |
| Права | Администратор | Администратор |
| **WebView2 Runtime** | Предустановлен на Win10 1809+ | Evergreen (авто-обновляется) |
| **Visual C++ Runtime** | vcruntime140.dll | vcredist 2015+ x64 |

### Известные ограничения

- **Windows 11 + Secure Boot ON** — Zapret не сможет загрузить драйвер WinDivert64.sys (сертификат Sectigo истёк 2023-05-26). Варианты:
  1. Отключить Secure Boot в UEFI/BIOS (самый простой путь).
  2. Перейти на Windows 10, где Secure Boot не блокирует загрузку.
  3. Использовать WARP / Hola / Opera — они работают без драйвера.
- **Антивирус** — некоторые продукты (Kaspersky, ESET, Avast) блокируют WinDivert или opera-proxy. Добавьте `VPN-Client.exe` в исключения.

---

## Быстрый старт (для пользователя)

1. Скачайте `VPN-Client.exe` из [Releases](../../releases).
2. Запустите — появится UAC-запрос, нажмите «Да».
3. В окне выберите движок (например, **Hola Proxy**), нажмите **Подключиться**.
4. Через 2–3 секунды в строке статуса появится «подключено». Системный прокси настроен автоматически.
5. Для **Zapret**: выберите «Авто-подбор» и нажмите **Подключиться**. Приложение протестирует стратегии на 55 сайтах и запомнит лучшую.

## Быстрый старт (для разработчика)

```cmd
git clone <repo>
cd VPN2
tools\setup.bat                :: скачивает бинарники + генерирует 261 .bat-стратегию
.venv\Scripts\activate
python vpn_client.py --debug   :: запуск с выводом лога в консоль
```

Сборка `.exe`:

```cmd
build_release.bat              :: single-file, без консоли, ~45 МБ
build_debug.bat                :: single-file, с консолью
```

Готовый файл: `dist\VPN-Client.exe`.

---

## Возможности по движкам

### Opera Proxy

HTTP-прокси на базе [Alexey71/opera-proxy](https://github.com/Alexey71/opera-proxy). При запуске получает свежий список серверов, пингует их через TCP (обходит файрволы в отличие от ICMP), выбирает лучший. Регионы: **EU / Asia / America**. Порт настраивается (по умолчанию 18080). Системный прокси Windows переключается автоматически, после отключения — сбрасывается.

### Hola Proxy

Альтернативный HTTP-прокси на базе [snawoot-proxies-forks/hola-proxy](https://github.com/snawoot-proxies-forks/hola-proxy). Список стран задаётся в настройках, по умолчанию подставляется автоматически. Порт 24080.

### Cloudflare WARP (AmneziaWG)

1. `warp-awg-gen` генерирует AmneziaWG-конфиг на лету (без регистрации аккаунта WARP).
2. Проверяется наличие `amneziawg.exe` в стандартных путях:
   - `C:\Program Files\AmneziaWG\`
   - `C:\Program Files (x86)\AmneziaWG\`
   - `%LOCALAPPDATA%\AmneziaWG\`
   - реестр (`HKLM\SOFTWARE\AmneziaWG`)
   - `where.exe amneziawg.exe`
3. **Если не найден** — автоматически скачивает MSI с GitHub Releases, ставит через `msiexec /quiet /i`, регистрирует manager-сервис.
4. Создаёт Windows-службу `AmneziaWGTunnel$<conf_name>`.

Туннель L3 — **меняет IP** на адрес из пула Cloudflare.

### Zapret DPI bypass

Пакетный фильтр, перехватывающий TCP/UDP «по дороге» к целевому серверу и применяющий фрагментацию/модификацию заголовков, чтобы DPI не распознал SNI. Работает **без смены IP**.

Поддерживаются два движка:

| Версия | Бинарник | Источник | Стратегий |
|---|---|---|---|
| v1 | `winws.exe` v72.2 | [youtubediscord/zapret](https://github.com/youtubediscord/zapret) | 159 |
| v2 | `winws2.exe` v0.9.3 | то же | 102 |

**261 стратегия** из 5 источников:

- `youtubediscord/zapret` — `general`, `general_alt`, `general_russia`
- `Flowseal/zapret-discord-youtube` — `general` (дополненные)
- `pumPCin/AntiZapret` — 11 `antizapret-*` стратегий (target Россия)
- плюс варианты с `--wssize`, `--dpi-desync-attacks`, multi-strat

#### Auto-pick

При выборе «Авто-подбор» приложение ищет лучшую стратегию по **55 тестовым URL**:

- YouTube, Discord, Instagram, Facebook, Twitter/X, Reddit, Twitch
- Cloudflare (1.1.1.1, api.cloudflareclient.com — WARP reg endpoint)
- GitHub, OpenAI, Google
- Telegram, Signal, WhatsApp, Snapchat, LinkedIn, Netflix, Spotify, TikTok
- RuTracker, NordVPN, Mullvad, Proton
- BBC, Rumble, Odysee, Nintendo, Chess.com
- и др. — полный список в `vpn_client.py:ZAPRET_TEST_URLS`

Тестирование **двухуровневое** (15–30 минут вместо 2–8 часов):

1. **Tier 1 (smoke)**: 5 URL параллельно, 2 с на стратегию — отсеивает явно плохие.
2. **Tier 2 (detailed)**: 55 URL параллельно, 3 с — запускается только если smoke ≥ 3/5.

**Time budget по умолчанию: 900 секунд (15 минут)**. Конфигурируется через `_auto_pick_strategy(time_budget=...)`.

После успешного подбора **конкретная стратегия сохраняется** в `settings.json` — при следующем запуске запустится она напрямую, без повторного auto-pick. Если файл стратегии будет удалён/переименован, приложение автоматически переключится на auto.

Режимы (`zapret_auto_mode`):

| Режим | Поведение |
|---|---|
| `both` (default) | Сначала v1, потом v2 — round-robin по списку |
| `v1` | Только v1 (winws) |
| `v2` | Только v2 (winws2) |

#### WinDivert

Используется `WinDivert.dll` (47616 байт) из **Flowseal/zapret-discord-youtube** — не из ZaperSetup (45568 байт, не работает на Win11 + Secure Boot). `WinDivert64.sys` одинаковый в обоих источниках (SHA-256 `8DA08533...`).

Перед каждым подключением приложение перерегистрирует kernel-сервис `windivert` на свой путь к `.sys` (`sc create windivert binPath= "\??\...\WinDivert64.sys" type= kernel start= demand`). Это лечит ошибку `windivert: error opening filter: The system cannot find the file specified.`, если раньше был установлен другой zapret.

---

## Сборка из исходников

> **Что происходит за один шаг `build_release.bat`:** на машине разработчика запускается `tools\setup.bat` (или `update.bat` при повторной сборке), который **скачивает** необходимые файлы из 5 GitHub-репозиториев в `zapret/`, `zapret/zapret2/`, плюс `opera-proxy.exe` / `warp-awg-gen.exe` / `hola-proxy.exe` в корень. Затем PyInstaller упаковывает всё в single-file `dist\VPN-Client.exe`. **После успешной сборки папку проекта целиком можно закрыть/архивировать/удалить** — собранный `.exe` самодостаточен и для запуска не требует ни исходников, ни скачанных бинарников, ни `tools/`, ни `tests/`, ни `.venv/`. Конечному пользователю передаётся только `dist\VPN-Client.exe`.

### 1. Подготовка окружения

```cmd
tools\setup.bat
```

Скачивает и подготавливает всё необходимое (~30 секунд при первом запуске, идемпотентно):

| Источник | Что |
|---|---|
| [youtubediscord/zapret](https://github.com/youtubediscord/zapret) | winws.exe v1, winws2.exe v0.9.3, 195 .bin, 89 .txt, 230 .bat |
| [Flowseal/zapret-discord-youtube](https://github.com/Flowseal/zapret-discord-youtube) | WinDivert.dll (47616 байт) |
| [pumPCin/AntiZapret](https://github.com/pumPCin/AntiZapret) | 11 `antizapret-*` стратегий |
| [bol-van/zapret](https://github.com/bol-van/zapret) + [bol-van/zapret-win-bundle](https://github.com/bol-van/zapret-win-bundle) | Lua-скрипты |
| [youtubediscord/zapret/ZaperSetup](https://github.com/youtubediscord/zapret) | Inno Setup silent install для .bin-ассетов |

После этого `zapret/` (v1) и `zapret/zapret2/` (v2) готовы.

### 2. Сборка

```cmd
build_release.bat     :: --onefile --windowed --uac-admin, ~45 МБ
build_debug.bat       :: --onefile, с консолью
```

PyInstaller собирает в один `.exe`:

```
--add-binary "opera-proxy.exe;."
--add-binary "warp-awg-gen.exe;."
--add-binary "hola-proxy.exe;."
--add-data "zapret;zapret"
--add-data "zapret\zapret2;zapret\zapret2"
--add-data "IMG;IMG"
--icon "IMG\icon.ico"
--uac-admin
```

### 3. Обновление бинарников

```cmd
update.bat            :: т.е. tools\update.bat — перекачивает свежие .exe + .bin
```

### Зависимости

| Файл | Что внутри | Когда ставится |
|---|---|---|
| `requirements.txt` | `pywebview`, `pystray`, `pillow` | `tools\setup.bat` ставит автоматически |
| `requirements-dev.txt` | + `pyinstaller` | `build_release.bat` / `build_debug.bat` ставят автоматически |

Если хотите поставить вручную (например, для IDE-автодополнения):

```cmd
.venv\Scripts\activate
pip install -r requirements.txt        :: только runtime
pip install -r requirements-dev.txt    :: runtime + pyinstaller (для сборки)
```

## Структура проекта

```
VPN2/
├── vpn_client.py                  # основной код (~3000 строк)
├── build_release.bat              # сборка release (ставит dev-deps + PyInstaller)
├── build_debug.bat                # сборка debug (с консолью)
├── update.bat                     # обновление бинарников
├── requirements.txt               # runtime: pywebview, pystray, pillow
├── requirements-dev.txt           # build:    + pyinstaller
├── LICENSE                        # MIT
│
├── tools/                         # утилиты сборки/загрузки
│   ├── setup.bat                  # оркестратор первоначальной настройки
│   ├── update.bat                 # обновление бинарников
│   ├── fetch_zapret_setup.py      # Inno Setup silent + WinDivert.dll (Flowseal)
│   ├── fetch_zapret_presets.py    # 230 .bat из youtubediscord
│   ├── fetch_flowseal_presets.py  # доп. .bat из Flowseal
│   ├── fetch_antizapret_presets.py# 11 antizapret-* стратегий
│   ├── rename_legacy_strategies.py# переименование в формат "z1 - <name>"
│   ├── run_elevated.py            # запуск .py с UAC
│   ├── download_proxies.ps1       # opera/hola/warp-awg-gen releases
│   └── download_zapret.ps1        # zapret releases
│
├── tests/                         # изолированные, детерминированные тесты
│   ├── _preflight.py              # общий check_setup() + auto-restore
│   ├── test_zapret_selection.py   # 123 проверки
│   ├── test_all_tools.py          # 69 проверок (meta-test tools/*)
│   ├── test_fetchers_isolated.py  # 48 проверок (mock network)
│   ├── test_downloads.py          # 16 проверок (URL репозиториев, opt-in online)
│   └── test_strategies_launch.py  # runtime запуск 261 winws, требует admin
│
├── IMG/                           # icon.ico + IMG.png (скриншот для README)
├── zapret/                        # генерируется setup.bat, .gitignore'd
│   ├── bin/                       # winws.exe, WinDivert.dll, WinDivert64.sys, .bin
│   ├── lists/                     # .txt списки доменов/IP
│   └── *.bat                      # 159 v1 стратегий (z1 - ...)
│   └── zapret2/                   # 102 v2 стратегии (z2 - ...)
│
└── dist/                          # результат сборки PyInstaller
    └── VPN-Client.exe             # ~45 МБ, single-file
```

## Тестирование

```cmd
python tests\test_zapret_selection.py     :: 123 проверки (parsing + selection)
python tests\test_all_tools.py            :: 69 проверок (meta-test tools/*)
python tests\test_fetchers_isolated.py    :: 48 проверок (mock network)
python tests\test_downloads.py            :: 16 проверок (URL репозиториев)
python tests\test_strategies_launch.py    :: runtime 261 winws (нужен admin, ~8 мин)
```

Все тесты по умолчанию работают **без сети** (кроме `test_downloads.py` с `VPNCLIENT_RUN_NETWORK=1`).

### Переменные окружения

| Var | Где | Поведение |
|---|---|---|
| `VPNCLIENT_AUTO_SETUP=1` | `python tests\*` | Если `zapret/` отсутствует — автоматически вызывает `tools\setup.bat`. Полезно для CI. |
| `VPNCLIENT_RUN_NETWORK=1` | `python tests\test_downloads.py` | Включает online-проверки (GitHub Releases API, SHA-256 бинарников). |

Без `VPNCLIENT_AUTO_SETUP` тесты **не падают** при отсутствии `zapret/`, а выдают понятный `WARN` с инструкцией.

### Покрытие

- `test_zapret_selection.py` — TEST 1–20: парсинг, dedup, bucket distribution, ENV smoke URLs, data_check, имена.
- `test_all_tools.py` — TEST 1–5: наличие .py/.ps1/.bat, корректные subprocess-аргументы, PS1 references.
- `test_fetchers_isolated.py` — TEST 1–8: HTTP fetchers, ZIP extraction, SHA-256 проверки (с mock).
- `test_downloads.py` — TEST 1–7: GitHub URLs, размеры .bin/.dll/.exe, известные хэши.
- `test_strategies_launch.py` — runtime прогон 261 стратегии с проверкой ENV ошибок (Secure Boot, admin, etc).

---

## Troubleshooting

### «vcruntime140.dll не найден»

Visual C++ Runtime не установлен. Скачайте [vcredist_x64.exe](https://aka.ms/vs/17/release/vc_redist.x64.exe) с сайта Microsoft.

### «WebView2 Runtime не найден»

На Windows 10 до версии 1809 WebView2 не предустановлен. Скачайте [Evergreen WebView2](https://developer.microsoft.com/microsoft-edge/webview2/).

### Zapret: «windivert: error opening filter: The system cannot find the file specified.»

См. `vpn_client.py:_register_windivert` — приложение перерегистрирует kernel-сервис автоматически. Если ошибка остаётся:

1. **Secure Boot ON + Win11** — основная причина. Отключите Secure Boot в UEFI/BIOS.
2. Запустите от администратора (обязательно для `sc create windivert`).
3. Переустановите Visual C++ Runtime (см. выше).

### Zapret: «windivert: failed to load» / STATUS_INVALID_IMAGE_HASH

Подпись WinDivert64.sys истекла (2023-05-26). Secure Boot блокирует загрузку неподписанных/просроченных драйверов. Решение — отключить Secure Boot.

### WARP: «AmneziaWG не найден» (но он установлен)

Приложение ищет в 6 стандартных путях + реестре. Если у вас нестандартная установка — добавьте `%PATH%\amneziawg.exe` или переустановите через GUI (приложение само скачает и поставит актуальную версию).

### Антивирус блокирует opera-proxy / winws

Добавьте в исключения:
- `VPN-Client.exe`
- `%TEMP%\_MEI*` (распакованный PyInstaller)
- `opera-proxy.exe`, `winws.exe`, `amneziawg.exe`

### Auto-pick работает слишком долго

`_auto_pick_strategy(time_budget=900)` — бюджет 15 минут. При 261 стратегии × 5 smoke URL (Tier 1) + × 55 detailed URL (Tier 2) — реальное время 15–30 минут. Чтобы ускорить:
- Ограничить `zapret_auto_mode` режимом `v1` или `v2` (вдвое меньше стратегий).
- Ручной выбор стратегии без auto-pick.

### Логи

`%TEMP%\vpn_client_debug.log` — основной лог приложения.
`%TEMP%\winws_out.log` — вывод `winws.exe` (для диагностики стратегий).
`%TEMP%\amneziawg_install.log` — установка AmneziaWG.

---

## Архитектура

```
┌──────────────────────────────────────────────────────┐
│ HTML/JS frontend (webview/Edge WebView2)             │
│  - статус, выбор региона/стратегии, лог, кнопки      │
└────────────┬─────────────────────────────────────────┘
             │ pywebview bridge
┌────────────▼─────────────────────────────────────────┐
│ vpn_client.py: Api class (Python)                    │
│  - get_settings / save_settings (atomic JSON write)  │
│  - start_connect_opera / hola / warp / dpi           │
│  - list_zapret_strategies / _auto_pick_strategy      │
│  - force_kill_all / shutdown (atexit + signal)       │
└────────────┬─────────────────────────────────────────┘
             │
       ┌─────┼──────────┬─────────────┐
       ▼     ▼          ▼             ▼
   opera  hola    warp-awg-gen    winws/winws2
   -proxy -proxy  + amneziawg     + WinDivert64
   (HTTP) (HTTP)  (L3 tunnel)     (kernel driver)
```

- **Frontend**: чистый HTML/CSS/JS в `vpn_client.py:HTML` (без React/Vue).
- **API**: `window.pywebview.api` → методы Api, экспортированные через `window.expose`.
- **Concurrency**: `threading.Lock` для settings / process handle / DPI state.
- **Settings**: `os.path.join(APPDATA, "VPNClient", "settings.json")`, atomic write (tmp + `os.replace`).
- **Cleanup**: `atexit.register(_safe_shutdown)` + `signal.SIGTERM/SIGBREAK` handlers, идемпотентный.

## Безопасность

- `--uac-admin` обязателен для `sc create windivert`, `amneziawg.exe /installtunnelservice`, `winws.exe`.
- Системный прокси сбрасывается на старте (защита от зависшего прокси) и при shutdown.
- WARP-конфиги генерируются локально, аккаунт не регистрируется.
- Никаких телеметрий, аналитик, обращений к сторонним серверам кроме явно задокументированных (GitHub Releases для бинарников, Cloudflare для WARP).
- Пароли / ключи **не логируются**.

## Переменные окружения (полный список)

| Var | Значение | Поведение |
|---|---|---|
| `VPNCLIENT_AUTO_SETUP` | `1` | В тестах: авто-запуск `tools\setup.bat` при отсутствии `zapret/` |
| `VPNCLIENT_RUN_NETWORK` | `1` | В `test_downloads.py`: online-проверки |
| `APPDATA` | path | Override пути к settings.json |
| `TEMP` / `TMP` | path | Override пути к логам и WinDivert-сервису |

## Благодарности

- [youtubediscord/zapret](https://github.com/youtubediscord/zapret) — winws.exe, winws2.exe, стратегии, ZaperSetup
- [Flowseal/zapret-discord-youtube](https://github.com/Flowseal/zapret-discord-youtube) — WinDivert.dll (47616 байт) — единственная версия, работающая на Win11 + Secure Boot
- [pumPCin/AntiZapret](https://github.com/pumPCin/AntiZapret) — antizapret-* стратегии
- [bol-van/zapret](https://github.com/bol-van/zapret) — оригинальный zapret, Lua-скрипты
- [amnezia-vpn/amneziawg-windows-client](https://github.com/amnezia-vpn/amneziawg-windows-client) — AmneziaWG-клиент
- [Skiro1/warp-awg-gen](https://github.com/Skiro1/warp-awg-gen) — генератор AmneziaWG-конфигов для WARP
- [Alexey71/opera-proxy](https://github.com/Alexey71/opera-proxy) — Opera VPN прокси
- [snawoot-proxies-forks/hola-proxy](https://github.com/snawoot-proxies-forks/hola-proxy) — Hola VPN прокси
- [ValdikSS/GoodbyeDPI](https://github.com/ValdikSS/GoodbyeDPI) — оригинальная идея DPI bypass
- [basil00/WinDivert](https://github.com/basil00/WinDivert) — Windows-пакетный фильтр

## Лицензия

Проект распространяется под **лицензией MIT** — полный текст см. в файле [LICENSE](LICENSE).

Кратко: разрешено использовать, копировать, изменять, распространять (в т.ч. коммерчески) при сохранении уведомления об авторских правах. Поставляется «как есть», без каких-либо гарантий.

Сторонние компоненты в `zapret/`, `zapret/zapret2/` и bundled `.exe` подчиняются **своим** лицензиям (см. ссылки в «Благодарности»).

```
MIT License

Copyright (c) 2024-2026 VPN-Client contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

**Версия:** 2.0.0 (см. `vpn_client.py:APP_VERSION`)  
**Размер .exe:** ~45 МБ  
**Поддерживаемые ОС:** Windows 10 (1809+), Windows 11  
**Лицензия:** [MIT](LICENSE)
