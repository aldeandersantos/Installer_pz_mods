import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import gdown

# ==========================================
#       Instalador feito por Aldeander
# ==========================================


def get_base_dir():
    # Quando compilado (.exe), usa a pasta do executavel; senao, a do script.
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def load_config():
    config_path = get_base_dir() / "config.json"
    try:
        with open(config_path, "r", encoding="utf-8") as config_file:
            return json.load(config_file)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[Config] Nao foi possivel ler config.json: {exc}")
        return {}


_config = load_config()

# Versao atual do instalador.
APP_VERSION = str(_config.get("app_version", "1.0.0"))

# Publique um JSON nesse endereco com este formato:
# {
#   "version": "1.0.1",
#   "url": "https://seu-servidor/instalador.exe"
# }
UPDATE_METADATA_URL = str(_config.get("update_metadata_url", ""))

# --- CONFIGURACOES ---
file_id = str(_config.get("file_id", ""))
url = f"https://drive.google.com/uc?id={file_id}"

# Pega o caminho do usuario logado automaticamente e monta a pasta do Zomboid
pasta_usuario = os.path.expanduser("~")
caminho_mods = os.path.join(pasta_usuario, "Zomboid", "mods")
arquivo_zip = os.path.join(caminho_mods, "mods_download.zip")
# ---------------------


def parse_version(version):
    parts = []
    for chunk in version.strip().split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def is_frozen():
    return getattr(sys, "frozen", False)


def fetch_update_metadata():
    if not UPDATE_METADATA_URL.strip():
        return None

    try:
        with urllib.request.urlopen(UPDATE_METADATA_URL, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"[Atualizacao] Nao foi possivel verificar atualizacoes: {exc}")
        return None

    remote_version = str(data.get("version", "")).strip()
    download_url = str(data.get("url", "")).strip()
    if not remote_version or not download_url:
        print("[Atualizacao] Metadados invalidos. Esperado: version + url.")
        return None

    if parse_version(remote_version) <= parse_version(APP_VERSION):
        return None

    return {
        "version": remote_version,
        "url": download_url,
    }


def ask_yes_no(prompt):
    while True:
        answer = input(prompt).strip().lower()
        if answer in {"s", "sim", "y", "yes"}:
            return True
        if answer in {"n", "nao", "não", "no"}:
            return False
        print("Resposta invalida. Digite S ou N.")


def download_file(download_url, destination):
    with urllib.request.urlopen(download_url, timeout=30) as response:
        with open(destination, "wb") as target:
            target.write(response.read())


def schedule_self_update(download_url):
    current_exe = Path(sys.executable).resolve()
    temp_dir = Path(tempfile.gettempdir())
    new_exe = temp_dir / f"{current_exe.stem}.new.exe"
    updater_bat = temp_dir / "update_installer.bat"

    print("[Atualizacao] Baixando nova versao...")
    download_file(download_url, new_exe)

    bat_lines = [
        "@echo off",
        "setlocal",
        "timeout /t 2 /nobreak >nul",
        f'copy /Y "{new_exe}" "{current_exe}" >nul',
        f'start "" "{current_exe}"',
        f'del "{new_exe}" >nul 2>nul',
        'del "%~f0" >nul 2>nul',
    ]
    updater_bat.write_text("\n".join(bat_lines), encoding="utf-8")

    subprocess.Popen(
        ["cmd", "/c", str(updater_bat)],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def check_for_updates():
    update_info = fetch_update_metadata()
    if not update_info:
        return False

    print(
        f"[Atualizacao] Nova versao encontrada: {update_info['version']} "
        f"(atual: {APP_VERSION})"
    )

    if not ask_yes_no("Deseja atualizar agora? [S/N]: "):
        return False

    if not is_frozen():
        print(
            "[Atualizacao] A troca automatica do executavel so funciona no .exe "
            "compilado. Atualize o codigo-fonte/manual build neste modo."
        )
        return False

    try:
        schedule_self_update(update_info["url"])
    except Exception as exc:
        print(f"[Atualizacao] Falha ao atualizar: {exc}")
        return False

    print("[Atualizacao] Atualizacao baixada. O instalador sera reiniciado.")
    return True


def run_installer():
    os.makedirs(caminho_mods, exist_ok=True)

    print("=" * 42)
    print("       Instalador feito por Aldeander")
    print("=" * 42)

    try:
        print(f"Destino detectado: {caminho_mods}")
        print("Baixando os mods do Google Drive...")
        gdown.download(url, arquivo_zip, quiet=False)

        print("Extraindo arquivos...")
        extraidos = 0
        ignorados = 0
        with zipfile.ZipFile(arquivo_zip, "r") as zip_ref:
            for membro in zip_ref.namelist():
                destino = os.path.join(caminho_mods, membro)
                # Se o arquivo/pasta ja existir, ignora
                if os.path.exists(destino):
                    ignorados += 1
                    continue
                zip_ref.extract(membro, caminho_mods)
                extraidos += 1

        os.remove(arquivo_zip)
        print(
            f"Sucesso! {extraidos} item(ns) instalado(s), "
            f"{ignorados} ja existente(s) ignorado(s)."
        )
        print("Arquivo ZIP removido.")

    except Exception as exc:
        print(f"Ocorreu um erro: {exc}")


def main():
    if check_for_updates():
        return

    run_installer()
    input("\nPressione Enter para fechar...")


if __name__ == "__main__":
    main()
