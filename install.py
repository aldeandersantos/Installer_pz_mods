# -*- coding: utf-8 -*-
import json
import os
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
import webbrowser
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import customtkinter as ctk
import gdown

# ==========================================
#       Instalador feito por Aldeander
# ==========================================

DEFAULT_CONFIG = {
    "app_version": "1.0.0",
    "update_metadata_url": "https://seuusuario.github.io/seurepo/version.json",
    "file_id": "COLOQUE_AQUI_O_FILE_ID_DO_GOOGLE_DRIVE",
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

# --- CONFIGURACOES ---
file_id = str(_config.get("file_id", ""))
url = f"https://drive.google.com/uc?id={file_id}"

# Pega o caminho do usuario logado automaticamente e monta a pasta do Zomboid
pasta_usuario = os.path.expanduser("~")
caminho_mods = os.path.join(pasta_usuario, "Zomboid", "mods")
arquivo_zip = os.path.join(caminho_mods, "mods_download.zip")
# ---------------------


# =====================================================================
#  NUCLEO / LOGICA  (sem dependencia de interface)
# =====================================================================

def parse_version(version):
    parts = []
    for chunk in version.strip().split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            parts.append(0)
    return tuple(parts)


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

    return {"version": remote_version, "url": download_url}


def download_file(download_url, destination):
    with urllib.request.urlopen(download_url, timeout=30) as response:
        with open(destination, "wb") as target:
            target.write(response.read())


def schedule_self_update(download_url):
    current_exe = Path(sys.executable).resolve()
    temp_dir = Path(tempfile.gettempdir())
    new_exe = temp_dir / f"{current_exe.stem}.new.exe"
    updater_bat = temp_dir / "update_installer.bat"

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


def run_installation(log, set_stage, set_progress):
    """Executa o download e a extracao dos mods.

    log(msg)            -> registra uma linha no terminal da interface
    set_stage(texto)    -> atualiza o rotulo de status
    set_progress(valor) -> None = indeterminado; float 0..1 = progresso real

    Retorna (extraidos, ignorados). Lanca excecao em caso de falha.
    """
    os.makedirs(caminho_mods, exist_ok=True)

    if not file_id.strip():
        raise ValueError("file_id nao configurado em config.json.")

    log(f"Destino detectado:\n  {caminho_mods}")
    set_stage("Baixando pacote do Google Drive...")
    set_progress(None)
    gdown.download(url, arquivo_zip, quiet=True)

    if not os.path.exists(arquivo_zip):
        raise FileNotFoundError("O arquivo baixado nao foi encontrado.")

    if not zipfile.is_zipfile(arquivo_zip):
        raise ValueError(
            "O download nao e um ZIP valido. "
            "Verifique se o link/arquivo do Google Drive esta correto."
        )

    log("Download concluido. Verificando integridade... OK")
    set_stage("Extraindo arquivos...")

    extraidos = 0
    ignorados = 0
    with zipfile.ZipFile(arquivo_zip, "r") as zip_ref:
        membros = zip_ref.namelist()
        total = len(membros) or 1
        for indice, membro in enumerate(membros, start=1):
            destino = os.path.join(caminho_mods, membro)
            if os.path.exists(destino):
                ignorados += 1
            else:
                zip_ref.extract(membro, caminho_mods)
                extraidos += 1
            set_progress(indice / total)

    os.remove(arquivo_zip)
    log(f"{extraidos} item(ns) instalado(s) | {ignorados} ja existente(s) ignorado(s).")
    log("Pacote temporario removido.")
    return extraidos, ignorados


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

        actions = ctk.CTkFrame(footer, fg_color="transparent")
        actions.grid(row=2, column=0, columnspan=2, sticky="ew",
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
        credit.grid(row=3, column=0, columnspan=2, sticky="ew",
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
            self.dot.configure(text="●  " + status, text_color=ACCENT)
        else:
            self.install_btn.configure(state="normal", text="▶  INSTALAR MODS")
            self.update_btn.configure(state="normal")
            self.dot.configure(text="●  OCIOSO", text_color=MUTED)

    # ---------- acoes ----------
    def _on_install(self):
        if self._busy:
            return
        self._set_busy(True, "INSTALANDO")
        self._append("Iniciando instalacao...", "accent")
        threading.Thread(target=self._install_worker, daemon=True).start()

    def _install_worker(self):
        try:
            extraidos, ignorados = run_installation(
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
        if not info:
            if manual:
                self._ui(self._append, "Voce ja esta na versao mais recente.", "muted")
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
