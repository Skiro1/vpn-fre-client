# -*- coding: utf-8 -*-
"""
Конвертер пресетов youtubediscord/zapret (.txt) в формат .bat для VPN-Client.

Использование:
    python tools/fetch_zapret_presets.py

Скачивает все *.txt из src/presets/builtin/winws1/ и winws2/ репозитория
youtubediscord/zapret и конвертирует в .bat с маркером ZAPRET_VERSION.
"""
import os
import re
import sys
import json
import urllib.request
import urllib.error
from pathlib import Path

REPO = "youtubediscord/zapret"
BRANCH = "main"
API = f"https://api.github.com/repos/{REPO}/git/trees/{BRANCH}?recursive=1"

ROOT = Path(__file__).resolve().parent.parent
OUT_V1 = ROOT / "zapret"
OUT_V2 = ROOT / "zapret" / "zapret2"

BIN_FILES_NEEDED = {
    "tls_clienthello_www_google_com.bin",
    "tls_clienthello_max_ru.bin",
    "tls_clienthello_4pda_to.bin",
    "tls_clienthello_7.bin",
    "tls_clienthello_3.bin",
    "quic_initial_www_google_com.bin",
    "quic_initial_dbankcloud_ru.bin",
    "stun.bin",
    "http_iana_org.bin",
    "tls_clienthello_disney_plus.bin",
    "tls_clienthello_samsungcloudsolution_com.bin",
    "quic_initial_static.bin",
}

LISTS_TO_PLACEHOLDER = True  # Если True, несуществующие списки заменяются на list-general-user.txt


def fetch_tree():
    print(f"[i] Получаю список файлов из {REPO}@{BRANCH}...")
    req = urllib.request.Request(API, headers={"User-Agent": "vpn-client-converter"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    return data.get("tree", [])


def fetch_text(url):
    # urllib.request требует ASCII-символов в URL; кодируем путь целиком
    from urllib.parse import quote
    scheme, rest = url.split("://", 1)
    host, path = rest.split("/", 1)
    url = scheme + "://" + host + "/" + quote(path, safe="/")
    req = urllib.request.Request(url, headers={"User-Agent": "vpn-client-converter"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def sanitize_filename(name: str) -> str:
    """Преобразует имя файла в безопасное."""
    name = re.sub(r"[<>:\"/\\|?*]", "_", name)
    name = re.sub(r"_+", "_", name).strip("._")
    if not name.lower().endswith(".bat"):
        name += ".bat"
    return name


def collect_existing_lists(base_dir: Path):
    """Собирает имена файлов из lists/ чтобы отличать реальные от отсутствующих."""
    names = set()
    if base_dir.is_dir():
        for f in base_dir.iterdir():
            if f.is_file() and f.suffix == ".txt":
                names.add(f.name)
    return names


def convert_preset(content: str, name: str, version: int, existing_lists: set) -> str:
    """Преобразует содержимое .txt пресета в .bat с правильным путями и маркером."""
    lines = content.splitlines()

    # Извлекаем метаданные
    preset_title = name
    description = ""
    for line in lines:
        s = line.strip()
        if s.startswith("# Preset:"):
            preset_title = s[len("# Preset:"):].strip() or name
        elif s.startswith("# Description:"):
            description = s[len("# Description:"):].strip()

    # Собираем только "полезные" строки (аргументы winws)
    arg_lines = []
    for line in lines:
        s = line.rstrip()
        stripped = s.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        # Заменяем относительные пути на шаблоны
        s = s.replace("bin/", "%BIN%")
        s = s.replace("lists/", "%LISTS%")
        # Фикс бага исходных .txt youtubediscord: в нескольких стратегиях
        # (YTDisBystro_34_1..4) написано
        #     --hostlist=%LISTS%list-general-user.txt,domain1.com,domain2.com,...
        # winws воспринимает это как ОДНО имя файла и падает с
        # "cannot access hostlist file 'list-general-user.txt,domain1.com,...'".
        # Правильный формат: --hostlist=<файл> + --hostlist-domains=<csv>.
        m = re.match(
            r'^(--hostlist=(?:%LISTS%[\w\-./]+\.txt|\S+\.txt)),([\w.\-]+(?:,[\w.\-]+)+)\s*\^?\s*$',
            s.strip(),
        )
        if m:
            file_part = m.group(1)
            domains_part = m.group(2)
            # Сплитим в 2 строки: --hostlist=<файл> ^\n--hostlist-domains=<csv> ^
            s = f"{file_part} ^\n--hostlist-domains={domains_part} ^"
        # Если список не существует — заменяем на user-list
        if LISTS_TO_PLACEHOLDER:
            def _check_list(m):
                path = m.group(1)
                fname = os.path.basename(path)
                if fname in existing_lists:
                    return m.group(0)
                return f"--hostlist=%LISTS%list-general-user.txt"
            s = re.sub(r"(--hostlist(?:=-exclude)?=)(%LISTS%[\w\-./]+\.txt)", _check_list, s)
            s = re.sub(r"(--ipset(?:=-exclude)?=)(%LISTS%[\w\-./]+\.txt)", _check_list, s)
        arg_lines.append(s)

    if not arg_lines:
        return None

    # Собираем bat-файл
    bat_lines = [
        "@echo off",
        "chcp 65001 > nul",
        ":: 65001 - UTF-8",
        f":: ZAPRET_VERSION={version}",
    ]
    if description:
        bat_lines.append(f":: {description}")
    bat_lines.append(":: " + preset_title)
    bat_lines.append("")
    bat_lines.append("cd /d \"%~dp0\"")
    bat_lines.append("")

    # Если версия 2, бинарь называется winws2.exe
    winws_name = "winws.exe" if version == 1 else "winws2.exe"
    bat_lines.append(f'start "zapret: %~n0" /min "%BIN%{winws_name}" \\')

    for i, al in enumerate(arg_lines):
        is_last = (i == len(arg_lines) - 1)
        bat_lines.append(al + ("" if is_last else " ^"))

    bat_lines.append("")
    return "\r\n".join(bat_lines)


def main():
    OUT_V1.mkdir(parents=True, exist_ok=True)
    OUT_V2.mkdir(parents=True, exist_ok=True)

    existing_v1_lists = collect_existing_lists(OUT_V1 / "lists")
    existing_v2_lists = collect_existing_lists(OUT_V2 / "lists")

    try:
        tree = fetch_tree()
    except urllib.error.URLError as e:
        print(f"[!] Не удалось получить список файлов: {e}")
        print("    Возможно, нет доступа к GitHub API. Попробуйте позже.")
        sys.exit(1)

    presets_v1 = []
    presets_v2 = []
    for node in tree:
        if node.get("type") != "blob":
            continue
        path = node.get("path", "")
        if path.startswith("src/presets/builtin/winws1/") and path.endswith(".txt"):
            presets_v1.append(path)
        elif path.startswith("src/presets/builtin/winws2/") and path.endswith(".txt"):
            presets_v2.append(path)

    print(f"[i] Найдено пресетов: winws1={len(presets_v1)}, winws2={len(presets_v2)}")

    # Конвертируем winws1 -> zapret/*.bat
    print(f"\n[winws1 -> {OUT_V1.relative_to(ROOT)}/]")
    converted_v1 = 0
    for path in presets_v1:
        raw_name = os.path.basename(path)
        base = os.path.splitext(raw_name)[0]
        bat_name = sanitize_filename(f"z1 - {base}")
        out_path = OUT_V1 / bat_name
        try:
            text = fetch_text(f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/{path}")
        except Exception as e:
            print(f"  [ERR] {raw_name}: {e}")
            continue
        bat = convert_preset(text, base, 1, existing_v1_lists)
        if bat is None:
            continue
        with open(out_path, "w", encoding="utf-8", newline="") as f:
            f.write(bat)
        converted_v1 += 1
    print(f"  Сконвертировано: {converted_v1}")

    # Конвертируем winws2 -> zapret/zapret2/*.bat
    print(f"\n[winws2 -> {OUT_V2.relative_to(ROOT)}/*.bat]")
    converted_v2 = 0
    for path in presets_v2:
        raw_name = os.path.basename(path)
        base = os.path.splitext(raw_name)[0]
        bat_name = sanitize_filename(f"z2 - {base}")
        out_path = OUT_V2 / bat_name
        try:
            text = fetch_text(f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/{path}")
        except Exception as e:
            print(f"  [ERR] {raw_name}: {e}")
            continue
        bat = convert_preset(text, base, 2, existing_v2_lists)
        if bat is None:
            continue
        with open(out_path, "w", encoding="utf-8", newline="") as f:
            f.write(bat)
        converted_v2 += 1
    print(f"  Сконвертировано: {converted_v2}")

    print(f"\n[OK] Готово. Всего создано: v1={converted_v1}, v2={converted_v2}")


if __name__ == "__main__":
    main()
