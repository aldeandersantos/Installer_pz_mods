# -*- coding: utf-8 -*-
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
import webbrowser
import urllib.error
import urllib.request
import zipfile
import re
from pathlib import Path

import customtkinter as ctk

# ==========================================
#       Instalador feito por Aldeander
# ==========================================

DEFAULT_CONFIG = {
    "app_version": "1.0.0",
    "update_metadata_url": "https://seuusuario.github.io/seurepo/version.json",
    "mods_release_tag": "mods-latest",
}


def is_frozen():
    return getattr(sys, "frozen", False)


def get_base_dir():
    # Quando compilado (.exe), usa a pasta do executavel; senao, a do script.
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def get_config_candidates():
    candidates = [get_base_dir() / "config.json"]
    if getattr(sys, "_MEIPASS", None):
        candidates.append(Path(sys._MEIPASS) / "config.json")
    return candidates


def load_config():
    # config.json e opcional e serve apenas para sobrescrever os valores padrao.
    config = DEFAULT_CONFIG.copy()

    for config_path in get_config_candidates():
        if not config_path.exists():
            continue

        try:
            with open(config_path, "r", encoding="utf-8") as config_file:
                loaded = json.load(config_file)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[Config] Nao foi possivel ler {config_path.name}: {exc}")
            return config

        if isinstance(loaded, dict):
            config.update(loaded)
        return config

    return config


_config = load_config()

# Versao atual do instalador.
APP_VERSION = str(_config.get("app_version", "1.0.0"))

# Publique um JSON nesse endereco com este formato:
# {"version": "1.0.1", "url": "https://seu-servidor/instalador.exe"}
UPDATE_METADATA_URL = str(_config.get("update_metadata_url", ""))
GITHUB_REPOSITORY = "aldeandersantos/Installer_pz_mods"
GITHUB_LATEST_RELEASE_API_URL = (
    f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/latest"
)

# --- CONFIGURACOES ---
# Tag da release do GitHub que hospeda um ZIP por mod (assets da release).
MODS_RELEASE_TAG = str(_config.get("mods_release_tag", "mods-latest")).strip() or "mods-latest"
GITHUB_MODS_RELEASE_API_URL = (
    f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/tags/{MODS_RELEASE_TAG}"
)

# Pega o caminho do usuario logado automaticamente e monta a pasta do Zomboid
pasta_usuario = os.path.expanduser("~")
caminho_zomboid = os.path.join(pasta_usuario, "Zomboid")
caminho_mods = os.path.join(pasta_usuario, "Zomboid", "mods")
lua_dir = os.path.join(caminho_zomboid, "Lua")
# ---------------------


SPECIAL_PACKAGES = {
    "mod_config.zip": {
        "name": "__mod_config__",
        "target_dir": lua_dir,
        "target_files": (
            "saved_modlists.txt",
            "modmanager-mods.txt",
            "pz_modlist_settings.cfg",
        ),
        "always_install": True,
    }
}


# =====================================================================
#  NUCLEO / LOGICA  (sem dependencia de interface)
# =====================================================================

def parse_version(version):
    normalized = re.sub(r"^[^\d]+", "", str(version).strip())
    if not normalized:
        return (0,)

    parts = []
    for chunk in normalized.split("."):
        match = re.search(r"\d+", chunk)
        if match:
            parts.append(int(match.group()))
        else:
            parts.append(0)

    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def fetch_json(url, headers=None, timeout=5):
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_update_metadata_from_url():
    if not UPDATE_METADATA_URL.strip():
        return None, "URL de metadados nao configurada."

    try:
        data = fetch_json(UPDATE_METADATA_URL, timeout=5)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return None, f"Falha ao ler os metadados remotos: {exc}"

    remote_version = str(data.get("version", "")).strip()
    download_url = str(data.get("url", "")).strip()
    if not remote_version or not download_url:
        return None, "Metadados invalidos. Esperado: version + url."

    return {"version": remote_version, "url": download_url}, None


def fetch_update_metadata_from_github():
    try:
        data = fetch_json(
            GITHUB_LATEST_RELEASE_API_URL,
            headers={"User-Agent": "PZ-Mod-Installer"},
            timeout=10,
        )
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return None, f"Falha ao consultar a release mais recente no GitHub: {exc}"

    remote_version = str(data.get("tag_name", "")).strip()
    assets = data.get("assets", [])
    download_url = ""

    for asset in assets:
        candidate_name = str(asset.get("name", "")).lower()
        candidate_url = str(asset.get("browser_download_url", "")).strip()
        if candidate_name.endswith(".exe") and candidate_url:
            download_url = candidate_url
            break

    if not remote_version or not download_url:
        return None, "Release do GitHub sem tag ou sem asset .exe para download."

    return {"version": remote_version, "url": download_url}, None


def fetch_update_metadata():
    errors = []

    for fetcher in (fetch_update_metadata_from_url, fetch_update_metadata_from_github):
        info, error = fetcher()
        if error:
            errors.append(error)
            continue

        if parse_version(info["version"]) <= parse_version(APP_VERSION):
            return {"status": "up_to_date"}

        return {"status": "update_available", **info}

    return {"status": "error", "message": " | ".join(errors)}


def download_file(download_url, destination):
    request = urllib.request.Request(
        download_url, headers={"User-Agent": "PZ-Mod-Installer"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        with open(destination, "wb") as target:
            shutil.copyfileobj(response, target)


def schedule_self_update(download_url):
    current_exe = Path(sys.executable).resolve()
    temp_dir = Path(tempfile.gettempdir())
    new_exe = temp_dir / f"{current_exe.stem}.new.exe"
    updater_script = temp_dir / "update_installer.ps1"
    update_log = temp_dir / "update_installer.log"

    download_file(download_url, new_exe)

    ps_lines = [
        "$ErrorActionPreference = 'Stop'",
        f"$CurrentExe = {json.dumps(str(current_exe))}",
        f"$NewExe = {json.dumps(str(new_exe))}",
        f"$LogFile = {json.dumps(str(update_log))}",
        f"$CurrentPid = {os.getpid()}",
        "",
        "function Write-Log([string]$Message) {",
        "    $timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'",
        "    Add-Content -Path $LogFile -Value \"$timestamp $Message\"",
        "}",
        "",
        "function Test-FileUnlocked([string]$Path) {",
        "    try {",
        "        $stream = [System.IO.File]::Open($Path, 'Open', 'ReadWrite', 'None')",
        "        $stream.Close()",
        "        return $true",
        "    } catch {",
        "        return $false",
        "    }",
        "}",
        "",
        "Write-Log 'Iniciando rotina de auto-atualizacao.'",
        "",
        "for ($attempt = 0; $attempt -lt 120; $attempt++) {",
        "    if (-not (Get-Process -Id $CurrentPid -ErrorAction SilentlyContinue)) {",
        "        break",
        "    }",
        "    Start-Sleep -Milliseconds 500",
        "}",
        "",
        "if (Get-Process -Id $CurrentPid -ErrorAction SilentlyContinue) {",
        "    Write-Log 'Timeout aguardando o processo antigo encerrar.'",
        "    exit 1",
        "}",
        "",
        "if (-not (Test-Path -LiteralPath $NewExe)) {",
        "    Write-Log 'Arquivo baixado nao foi encontrado.'",
        "    exit 1",
        "}",
        "",
        "for ($attempt = 0; $attempt -lt 120; $attempt++) {",
        "    if (Test-FileUnlocked -Path $CurrentExe) {",
        "        Write-Log 'Executavel antigo desbloqueado para substituicao.'",
        "        break",
        "    }",
        "    Start-Sleep -Milliseconds 500",
        "}",
        "",
        "if (-not (Test-FileUnlocked -Path $CurrentExe)) {",
        "    Write-Log 'Timeout aguardando o executavel antigo liberar o arquivo.'",
        "    exit 1",
        "}",
        "",
        "$sourceInfo = Get-Item -LiteralPath $NewExe",
        "Write-Log \"Novo executavel baixado: $($sourceInfo.Length) bytes.\"",
        "",
        "for ($attempt = 1; $attempt -le 10; $attempt++) {",
        "    try {",
        "        Copy-Item -LiteralPath $NewExe -Destination $CurrentExe -Force",
        "        $targetInfo = Get-Item -LiteralPath $CurrentExe",
        "        if ($targetInfo.Length -eq $sourceInfo.Length) {",
        "            Write-Log \"Substituicao concluida na tentativa $attempt.\"",
        "            Start-Process -FilePath $CurrentExe -WorkingDirectory ([System.IO.Path]::GetDirectoryName($CurrentExe))",
        "            Write-Log 'Aplicativo reiniciado com sucesso.'",
        "            Remove-Item -LiteralPath $NewExe -Force -ErrorAction SilentlyContinue",
        "            exit 0",
        "        }",
        "        Write-Log \"Tamanho divergente apos a copia na tentativa $attempt.\"",
        "    } catch {",
        "        Write-Log \"Falha na tentativa ${attempt}: $($_.Exception.Message)\"",
        "    }",
        "    Start-Sleep -Seconds 1",
        "}",
        "",
        "Write-Log 'Nao foi possivel substituir o executavel apos varias tentativas.'",
        "exit 1",
    ]
    updater_script.write_text("\n".join(ps_lines), encoding="utf-8")

    subprocess.Popen(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(updater_script),
        ],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def download_mod_archive(download_url, destination):
    if not str(download_url).strip():
        raise ValueError("URL de download do mod nao configurada.")

    if os.path.exists(destination):
        os.remove(destination)

    download_file(download_url, destination)

    if not os.path.exists(destination):
        raise FileNotFoundError("O arquivo baixado nao foi encontrado.")


def ensure_valid_mods_path():
    normalized = os.path.normpath(caminho_mods)
    expected_suffix = os.path.normpath(os.path.join("Zomboid", "mods"))
    if not normalized.endswith(expected_suffix):
        raise ValueError(f"Caminho de mods inesperado: {caminho_mods}")
    return normalized


def reset_mods_directory():
    safe_mods_path = ensure_valid_mods_path()
    if os.path.isdir(safe_mods_path):
        shutil.rmtree(safe_mods_path)
    os.makedirs(safe_mods_path, exist_ok=True)


def extract_zip_with_mode(zip_path, destination_dir, overwrite_existing, log, set_progress):
    extraidos = 0
    ignorados = 0

    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        membros = zip_ref.namelist()
        total = len(membros) or 1
        for indice, membro in enumerate(membros, start=1):
            destino = os.path.join(destination_dir, membro)
            should_extract = overwrite_existing or not os.path.exists(destino)
            if should_extract:
                zip_ref.extract(membro, destination_dir)
                extraidos += 1
            else:
                ignorados += 1
            set_progress(indice / total)

    log(f"{extraidos} item(ns) instalado(s) | {ignorados} ja existente(s) ignorado(s).")
    return extraidos, ignorados


def fetch_mods_release_assets():
    data = fetch_json(
        GITHUB_MODS_RELEASE_API_URL,
        headers={"User-Agent": "PZ-Mod-Installer"},
        timeout=10,
    )

    assets = data.get("assets", [])
    catalog = []
    for asset in assets:
        archive_name = str(asset.get("name", "")).strip()
        download_url = str(asset.get("browser_download_url", "")).strip()
        if not archive_name.lower().endswith(".zip") or not download_url:
            continue
        special_package = get_special_package(archive_name)
        catalog.append(
            {
                "name": special_package["name"] if special_package else normalize_mod_name(archive_name),
                "download_url": download_url,
                "archive_name": archive_name,
                "special_package": special_package,
            }
        )

    return catalog


def normalize_mod_name(name):
    normalized = str(name).strip()
    if normalized.lower().endswith(".zip"):
        normalized = normalized[:-4]
    return normalized.strip()


def get_special_package(archive_name):
    return SPECIAL_PACKAGES.get(str(archive_name).strip())


def install_special_package(zip_path, special_package, log):
    os.makedirs(special_package["target_dir"], exist_ok=True)
    target_files = tuple(special_package.get("target_files", ()))

    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        members = [name for name in zip_ref.namelist() if not name.endswith("/")]
        if not members:
            raise ValueError(
                f"O pacote especial '{special_package['name']}' esta vazio."
            )
        members_by_name = {os.path.basename(member): member for member in members}

        installed_files = []
        for target_file in target_files:
            matching_member = members_by_name.get(target_file)
            if not matching_member:
                continue

            target_path = os.path.join(special_package["target_dir"], target_file)
            with zip_ref.open(matching_member) as source, open(target_path, "wb") as destination:
                destination.write(source.read())
            installed_files.append(target_file)

    if not installed_files:
        expected_files = ", ".join(target_files)
        raise ValueError(
            f"O pacote especial nao contem nenhum dos arquivos esperados: {expected_files}."
        )

    log(
        "Configuracoes de menu atualizadas em "
        f"{special_package['target_dir']}: {', '.join(installed_files)}."
    )


def load_remote_mod_catalog(log):
    log(f"Lendo catalogo da release '{MODS_RELEASE_TAG}' no GitHub...")
    try:
        mods = fetch_mods_release_assets()
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Falha ao consultar a release de mods no GitHub: {exc}"
        ) from exc

    if not mods:
        raise ValueError(
            f"A release '{MODS_RELEASE_TAG}' nao possui arquivos .zip de mods."
        )

    mods.sort(key=lambda item: item["name"].lower())
    return mods


def install_mods(install_mode, log, set_stage, set_progress):
    os.makedirs(caminho_mods, exist_ok=True)
    log(f"Destino detectado:\n  {caminho_mods}")
    log(f"Catalogo de mods hospedado em GitHub Releases (tag '{MODS_RELEASE_TAG}').")
    set_stage("Lendo catalogo de mods...")
    set_progress(None)
    mods = load_remote_mod_catalog(log)
    total_mods = len(mods)

    if install_mode == "replace_all":
        log("Opcao selecionada: substituir todos os mods existentes.")
        set_stage("Limpando pasta de mods...")
        set_progress(None)
        reset_mods_directory()
        pendentes = mods
    else:
        log("Opcao selecionada: instalar apenas mods faltantes.")
        existentes = {
            item.name.lower()
            for item in Path(caminho_mods).iterdir()
            if item.is_dir()
        }
        pendentes = []
        for mod in mods:
            special_package = mod.get("special_package")
            if special_package and special_package.get("always_install"):
                pendentes.append(mod)
                continue
            if mod["name"].lower() not in existentes:
                pendentes.append(mod)
        log(f"Catalogo carregado: {total_mods} mod(s) | {len(pendentes)} pendente(s).")

    if not pendentes:
        set_progress(1)
        log("Nenhum mod faltando. Nada para baixar.")
        return 0, total_mods

    temp_dir = tempfile.mkdtemp(prefix="pz_mods_")
    instalados = 0
    ignorados = total_mods - len(pendentes)
    try:
        for indice, mod in enumerate(pendentes, start=1):
            archive_name = mod["archive_name"]
            zip_path = os.path.join(temp_dir, archive_name)
            set_stage(f"Baixando mod {indice}/{len(pendentes)}: {mod['name']}")
            set_progress((indice - 1) / len(pendentes))
            log(f"Baixando {mod['name']}...")
            download_mod_archive(mod["download_url"], zip_path)

            if not zipfile.is_zipfile(zip_path):
                raise ValueError(f"O arquivo do mod '{mod['name']}' nao e um ZIP valido.")

            special_package = mod.get("special_package")
            if special_package:
                install_special_package(zip_path, special_package, log)
            else:
                with zipfile.ZipFile(zip_path, "r") as zip_ref:
                    zip_ref.extractall(caminho_mods)
            instalados += 1
            set_progress(indice / len(pendentes))
            log(f"{mod['name']} instalado.")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    return instalados, ignorados


def run_installation(install_mode, log, set_stage, set_progress):
    return install_mods(install_mode, log, set_stage, set_progress)


# =====================================================================
#  TEMA / PALETA  -  "Quarantine Terminal"
# =====================================================================

BG        = "#0d0b09"   # fundo principal (preto quente)
BG_PANEL  = "#16130f"   # paineis
BG_TERM   = "#0a0807"   # terminal
BORDER    = "#2b241b"   # bordas
ACCENT     = "#3a9fe0"   # acento azul (primario)
ACCENT_DK  = "#1f72ac"   # azul escuro (hover)
RED       = "#d24b32"   # erro / perigo
GREEN     = "#8fb840"   # sucesso (verde de sobrevivencia)
TEXT      = "#ece3d2"   # texto principal
MUTED     = "#897f6c"   # texto secundario

FONT_DISPLAY = "Bahnschrift"   # condensado industrial (Windows)
FONT_MONO    = "Consolas"      # terminal


AUTHOR = "Aldeander"
GITHUB_URL = "https://github.com/aldeandersantos"


def make_hyperlink(label, url=GITHUB_URL):
    """Transforma um CTkLabel em link clicavel (cursor + sublinhado no hover)."""
    base = label.cget("font")

    def _open(_event=None):
        webbrowser.open_new_tab(url)

    def _enter(_event=None):
        label.configure(text_color=ACCENT, cursor="hand2",
                        font=(base[0], base[1], "underline"))

    def _leave(_event=None):
        label.configure(text_color=ACCENT_DK, cursor="hand2",
                        font=(base[0], base[1]))

    label.configure(text_color=ACCENT_DK, cursor="hand2")
    label.bind("<Button-1>", _open)
    label.bind("<Enter>", _enter)
    label.bind("<Leave>", _leave)
    return label


def _stripes(canvas, w, h, step=22, color=ACCENT, bg=BG_TERM):
    """Desenha barras diagonais de perigo num canvas."""
    canvas.delete("all")
    canvas.configure(bg=bg)
    x = -h
    while x < w:
        canvas.create_polygon(
            x, h, x + step // 2, h, x + step // 2 + h, 0, x + h, 0,
            fill=color, outline="",
        )
        x += step


# =====================================================================
#  DIALOGO MODAL  -  confirmacao de atualizacao
# =====================================================================

class ConfirmDialog(ctk.CTkToplevel):
    def __init__(self, master, title, message):
        super().__init__(master)
        self.result = False
        self.title("")
        self.configure(fg_color=BG)
        self.resizable(False, False)
        self.transient(master)
        self.geometry("420x210")

        wrap = ctk.CTkFrame(self, fg_color=BG_PANEL, border_color=ACCENT,
                            border_width=1, corner_radius=4)
        wrap.pack(fill="both", expand=True, padx=12, pady=12)

        ctk.CTkLabel(wrap, text=f"// {title}", text_color=ACCENT,
                     font=(FONT_DISPLAY, 20, "bold"), anchor="w").pack(
            fill="x", padx=20, pady=(18, 6))
        ctk.CTkLabel(wrap, text=message, text_color=TEXT, justify="left",
                     wraplength=360, font=(FONT_MONO, 12), anchor="w").pack(
            fill="x", padx=20)

        row = ctk.CTkFrame(wrap, fg_color="transparent")
        row.pack(side="bottom", fill="x", padx=20, pady=18)
        ctk.CTkButton(row, text="AGORA NAO", width=120, height=34,
                      fg_color="transparent", border_color=BORDER, border_width=1,
                      hover_color=BG_TERM, text_color=MUTED,
                      font=(FONT_DISPLAY, 14, "bold"),
                      command=self._no).pack(side="right", padx=(10, 0))
        ctk.CTkButton(row, text="ATUALIZAR", width=140, height=34,
                      fg_color=ACCENT, hover_color=ACCENT_DK, text_color=BG,
                      font=(FONT_DISPLAY, 14, "bold"),
                      command=self._yes).pack(side="right")

        self.after(60, self._center)
        self.grab_set()

    def _center(self):
        self.update_idletasks()
        m = self.master
        x = m.winfo_x() + (m.winfo_width() - self.winfo_width()) // 2
        y = m.winfo_y() + (m.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")

    def _yes(self):
        self.result = True
        self.destroy()

    def _no(self):
        self.result = False
        self.destroy()


# =====================================================================
#  APLICACAO
# =====================================================================

class InstallerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")

        self.title("PZ Mod Installer")
        self.geometry("760x600")
        self.minsize(680, 560)
        self.configure(fg_color=BG)

        self._busy = False
        self.install_mode = tk.StringVar(value="missing_only")
        self._build_ui()
        self.after(400, self._auto_check_updates)

    # ---------- construcao da interface ----------
    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self._build_header()
        self._build_meta()
        self._build_terminal()
        self._build_footer()

    def _build_header(self):
        header = ctk.CTkFrame(self, fg_color=BG_PANEL, corner_radius=0,
                              height=104)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        header.grid_columnconfigure(1, weight=1)

        # marcador de perigo (canvas com circulo + traco)
        badge = tk.Canvas(header, width=64, height=104, bg=BG_PANEL,
                          highlightthickness=0)
        badge.grid(row=0, column=0, padx=(22, 8))
        badge.create_oval(14, 38, 50, 74, outline=ACCENT, width=3)
        badge.create_oval(27, 51, 37, 61, fill=ACCENT, outline="")

        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.grid(row=0, column=1, sticky="w")
        ctk.CTkLabel(title_box, text="PROJECT ZOMBOID", text_color=MUTED,
                     font=(FONT_MONO, 12), anchor="w").pack(anchor="w", pady=(26, 0))
        ctk.CTkLabel(title_box, text="MOD INSTALLER", text_color=TEXT,
                     font=(FONT_DISPLAY, 34, "bold"), anchor="w").pack(
            anchor="w", pady=(0, 2))
        author = ctk.CTkLabel(title_box, text=f"feito por {AUTHOR}",
                               font=(FONT_MONO, 11), anchor="w")
        author.pack(anchor="w")
        make_hyperlink(author)

        ctk.CTkLabel(header, text=f"v{APP_VERSION}", text_color=BG,
                     fg_color=ACCENT, corner_radius=3, width=58, height=22,
                     font=(FONT_MONO, 12, "bold")).grid(
            row=0, column=2, padx=22, sticky="e")

        # faixa de perigo diagonal
        self.stripe = tk.Canvas(self, height=8, bg=BG_TERM, highlightthickness=0)
        self.stripe.grid(row=1, column=0, sticky="ew")
        self.stripe.bind(
            "<Configure>",
            lambda e: _stripes(self.stripe, e.width, e.height, color=ACCENT))

    def _build_meta(self):
        # destino fica dentro do bloco terminal; nada aqui por enquanto
        pass

    def _build_terminal(self):
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=2, column=0, sticky="nsew", padx=22, pady=(18, 6))
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(1, weight=1)

        bar = ctk.CTkFrame(body, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ctk.CTkLabel(bar, text="// LOG DE INSTALACAO", text_color=MUTED,
                     font=(FONT_MONO, 11)).pack(side="left")
        self.dot = ctk.CTkLabel(bar, text="●  OCIOSO", text_color=MUTED,
                                font=(FONT_MONO, 11))
        self.dot.pack(side="right")

        self.terminal = ctk.CTkTextbox(
            body, fg_color=BG_TERM, border_color=BORDER, border_width=1,
            corner_radius=4, text_color=GREEN, font=(FONT_MONO, 12.5),
            wrap="word")
        self.terminal.grid(row=1, column=0, sticky="nsew")
        self.terminal.configure(state="disabled")
        self.terminal.tag_config("accent", foreground=ACCENT)
        self.terminal.tag_config("red", foreground=RED)
        self.terminal.tag_config("muted", foreground=MUTED)

        self._append("Sistema de instalacao pronto.", "accent")
        self._append("Aguardando comando do operador...", "muted")

    def _build_footer(self):
        footer = ctk.CTkFrame(self, fg_color=BG_PANEL, corner_radius=0)
        footer.grid(row=3, column=0, sticky="ew")
        footer.grid_columnconfigure(0, weight=1)

        self.stage = ctk.CTkLabel(footer, text="Pronto para instalar.",
                                  text_color=TEXT, font=(FONT_MONO, 12),
                                  anchor="w")
        self.stage.grid(row=0, column=0, sticky="w", padx=22, pady=(16, 4))

        self.progress = ctk.CTkProgressBar(
            footer, height=10, corner_radius=2, fg_color=BG_TERM,
            progress_color=ACCENT, border_color=BORDER, border_width=1)
        self.progress.grid(row=1, column=0, columnspan=2, sticky="ew",
                           padx=22)
        self.progress.set(0)

        mode_row = ctk.CTkFrame(footer, fg_color="transparent")
        mode_row.grid(row=2, column=0, columnspan=2, sticky="ew",
                      padx=22, pady=(14, 2))
        mode_row.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(mode_row, text="MODO DE INSTALACAO",
                     text_color=MUTED, font=(FONT_MONO, 11)).grid(
            row=0, column=0, sticky="w", pady=(0, 8))

        self.mode_switch = ctk.CTkSegmentedButton(
            mode_row,
            values=["SO FALTANTES", "SUBSTITUIR TUDO"],
            selected_color=ACCENT,
            selected_hover_color=ACCENT_DK,
            unselected_color=BG_TERM,
            unselected_hover_color=BG,
            text_color=TEXT,
            font=(FONT_DISPLAY, 13, "bold"),
            command=self._on_mode_changed,
        )
        self.mode_switch.grid(row=1, column=0, sticky="w")
        self.mode_switch.set("SO FALTANTES")

        actions = ctk.CTkFrame(footer, fg_color="transparent")
        actions.grid(row=3, column=0, columnspan=2, sticky="ew",
                     padx=22, pady=18)
        actions.grid_columnconfigure(0, weight=1)

        self.update_btn = ctk.CTkButton(
            actions, text="VERIFICAR ATUALIZACOES", width=200, height=46,
            fg_color="transparent", border_color=BORDER, border_width=1,
            hover_color=BG_TERM, text_color=MUTED,
            font=(FONT_DISPLAY, 15, "bold"),
            command=lambda: self._auto_check_updates(manual=True))
        self.update_btn.grid(row=0, column=0, sticky="w")

        self.install_btn = ctk.CTkButton(
            actions, text="▶  INSTALAR MODS", width=240, height=46,
            fg_color=ACCENT, hover_color=ACCENT_DK, text_color=BG,
            font=(FONT_DISPLAY, 17, "bold"),
            command=self._on_install)
        self.install_btn.grid(row=0, column=1, sticky="e")

        # credito / autoria
        credit = ctk.CTkFrame(footer, fg_color="transparent")
        credit.grid(row=4, column=0, columnspan=2, sticky="ew",
                    padx=22, pady=(0, 14))
        ctk.CTkLabel(credit, text=f"feito por {AUTHOR}  ·  ",
                     text_color=MUTED, font=(FONT_MONO, 11)).pack(side="left")
        link = ctk.CTkLabel(credit, text="github.com/aldeandersantos",
                            font=(FONT_MONO, 11))
        link.pack(side="left")
        make_hyperlink(link)

    # ---------- utilitarios thread-safe ----------
    def _ui(self, fn, *args):
        self.after(0, lambda: fn(*args))

    def _append(self, text, tag=None):
        self.terminal.configure(state="normal")
        prefix = ">  "
        for i, line in enumerate(text.split("\n")):
            mark = prefix if i == 0 else "   "
            self.terminal.insert("end", mark + line + "\n", tag or "")
        self.terminal.see("end")
        self.terminal.configure(state="disabled")

    def _set_stage(self, text):
        self.stage.configure(text=text)

    def _set_progress(self, value):
        if value is None:
            self.progress.configure(mode="indeterminate")
            self.progress.start()
        else:
            self.progress.stop()
            self.progress.configure(mode="determinate")
            self.progress.set(value)

    def _set_busy(self, busy, status="TRABALHANDO"):
        self._busy = busy
        if busy:
            self.install_btn.configure(state="disabled", text="INSTALANDO...")
            self.update_btn.configure(state="disabled")
            self.mode_switch.configure(state="disabled")
            self.dot.configure(text="●  " + status, text_color=ACCENT)
        else:
            self.install_btn.configure(state="normal", text="▶  INSTALAR MODS")
            self.update_btn.configure(state="normal")
            self.mode_switch.configure(state="normal")
            self.dot.configure(text="●  OCIOSO", text_color=MUTED)

    def _on_mode_changed(self, choice):
        selected_mode = "replace_all" if choice == "SUBSTITUIR TUDO" else "missing_only"
        self.install_mode.set(selected_mode)
        if selected_mode == "replace_all":
            self._append("Modo definido para substituir toda a pasta de mods.", "muted")
        else:
            self._append("Modo definido para instalar apenas mods faltantes.", "muted")

    # ---------- acoes ----------
    def _on_install(self):
        if self._busy:
            return
        self._set_busy(True, "INSTALANDO")
        install_mode = self.install_mode.get()
        mode_text = "substituir tudo" if install_mode == "replace_all" else "instalar so faltantes"
        self._append(f"Iniciando instalacao ({mode_text})...", "accent")
        threading.Thread(target=self._install_worker, args=(install_mode,), daemon=True).start()

    def _install_worker(self, install_mode):
        try:
            extraidos, ignorados = run_installation(
                install_mode=install_mode,
                log=lambda m: self._ui(self._append, m),
                set_stage=lambda s: self._ui(self._set_stage, s),
                set_progress=lambda v: self._ui(self._set_progress, v),
            )
        except Exception as exc:
            self._ui(self._set_progress, 0)
            self._ui(self._set_stage, "Falha na instalacao.")
            self._ui(self._append, f"ERRO: {exc}", "red")
            self._ui(self._set_busy, False)
            return

        self._ui(self._set_progress, 1)
        self._ui(self._set_stage,
                 f"Concluido: {extraidos} instalado(s), {ignorados} ignorado(s).")
        self._ui(self._append, "INSTALACAO CONCLUIDA COM SUCESSO.", "accent")
        self._ui(self._set_busy, False)

    # ---------- atualizacoes ----------
    def _auto_check_updates(self, manual=False):
        if self._busy:
            return
        if manual:
            self._append("Verificando atualizacoes...", "muted")
        threading.Thread(
            target=self._update_worker, args=(manual,), daemon=True).start()

    def _update_worker(self, manual):
        info = fetch_update_metadata()
        if info["status"] == "error":
            print(f"[Atualizacao] {info['message']}")
            if manual:
                self._ui(
                    self._append,
                    "Nao foi possivel verificar atualizacoes agora.",
                    "red",
                )
            return

        if info["status"] == "up_to_date":
            if manual:
                self._ui(
                    self._append,
                    "Voce ja esta na versao mais recente.",
                    "muted",
                )
            return
        self._ui(self._prompt_update, info)

    def _prompt_update(self, info):
        self._append(
            f"Nova versao disponivel: {info['version']} (atual: {APP_VERSION})",
            "accent")
        dialog = ConfirmDialog(
            self, "ATUALIZACAO DISPONIVEL",
            f"Versao {info['version']} esta pronta para download.\n"
            f"Deseja atualizar o instalador agora?")
        self.wait_window(dialog)
        if not dialog.result:
            return

        if not is_frozen():
            self._append(
                "A auto-atualizacao so funciona no .exe compilado.", "muted")
            return

        try:
            self._append("Baixando nova versao...", "accent")
            schedule_self_update(info["url"])
            self._append("Atualizacao baixada. Reiniciando...", "accent")
            self.after(800, self.destroy)
        except Exception as exc:
            self._append(f"Falha ao atualizar: {exc}", "red")


def main():
    app = InstallerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
