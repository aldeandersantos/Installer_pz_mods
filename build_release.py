import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCE_FILE = ROOT / "install.py"
CONFIG_FILE = ROOT / "config.json"
TEMP_SOURCE_FILE = ROOT / "_build_install.py"
VERSION_INFO_FILE = ROOT / "_build_version_info.txt"
BUILD_DIR = ROOT / "build"
DIST_DIR = ROOT / "dist"
TEMP_DIST_DIR = ROOT / "_dist_build"
OUTPUT_NAME = "Install_pz_mods"
GENERATED_SPEC_FILE = ROOT / f"{OUTPUT_NAME}.spec"


def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as config_file:
        config = json.load(config_file)

    required_keys = ("app_version", "update_metadata_url", "mods_release_tag")
    missing = [key for key in required_keys if not str(config.get(key, "")).strip()]
    if missing:
        missing_text = ", ".join(missing)
        raise ValueError(f"config.json esta sem os campos obrigatorios: {missing_text}")

    return config


def build_temp_source(config):
    source = SOURCE_FILE.read_text(encoding="utf-8")
    replacement = "DEFAULT_CONFIG = " + json.dumps(
        config, ensure_ascii=True, indent=4, sort_keys=True
    )
    updated, count = re.subn(
        r"DEFAULT_CONFIG\s*=\s*\{.*?\n\}",
        replacement,
        source,
        count=1,
        flags=re.DOTALL,
    )

    if count != 1:
        raise RuntimeError("Nao foi possivel localizar DEFAULT_CONFIG em install.py")

    TEMP_SOURCE_FILE.write_text(updated, encoding="utf-8")


def build_version_file(config):
    version = str(config["app_version"]).strip() or "1.0.0"
    version_parts = [part for part in version.split(".") if part.strip()]
    numeric_parts = []
    for part in version_parts[:4]:
        numeric_parts.append(str(int(part)) if part.isdigit() else "0")
    while len(numeric_parts) < 4:
        numeric_parts.append("0")

    version_tuple = ", ".join(numeric_parts)
    version_text = ".".join(numeric_parts)
    version_file = f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({version_tuple}),
    prodvers=({version_tuple}),
    mask=0x3F,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [
          StringStruct('CompanyName', 'Open Source Project'),
          StringStruct('FileDescription', 'Instalador de mods do Project Zomboid'),
          StringStruct('FileVersion', '{version_text}'),
          StringStruct('InternalName', '{OUTPUT_NAME}'),
          StringStruct('OriginalFilename', '{OUTPUT_NAME}.exe'),
          StringStruct('ProductName', 'PZ Mod Installer'),
          StringStruct('ProductVersion', '{version_text}')
        ]
      )
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)"""
    VERSION_INFO_FILE.write_text(version_file, encoding="utf-8")


def run_pyinstaller():
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--distpath",
        str(TEMP_DIST_DIR),
        "--workpath",
        str(BUILD_DIR),
        "--version-file",
        str(VERSION_INFO_FILE),
        "--name",
        OUTPUT_NAME,
        str(TEMP_SOURCE_FILE),
    ]
    subprocess.run(command, cwd=ROOT, check=True)


def publish_output():
    built_output = TEMP_DIST_DIR / f"{OUTPUT_NAME}.exe"
    final_output = DIST_DIR / f"{OUTPUT_NAME}.exe"
    fallback_output = DIST_DIR / f"{OUTPUT_NAME}.new.exe"

    if not built_output.exists():
        raise FileNotFoundError(f"Build concluido, mas o arquivo nao foi encontrado: {built_output}")

    DIST_DIR.mkdir(exist_ok=True)

    try:
        if final_output.exists():
            final_output.unlink()
        if fallback_output.exists():
            fallback_output.unlink()
        shutil.move(str(built_output), str(final_output))
        return final_output
    except PermissionError as exc:
        shutil.move(str(built_output), str(fallback_output))
        raise RuntimeError(
            "O executavel atual esta em uso e nao pode ser substituido agora. "
            f"A nova versao foi salva em: {fallback_output}"
        ) from exc


def cleanup():
    paths_to_remove = [
        TEMP_SOURCE_FILE,
        VERSION_INFO_FILE,
        GENERATED_SPEC_FILE,
        BUILD_DIR,
        TEMP_DIST_DIR,
    ]

    for path in paths_to_remove:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.exists():
            path.unlink()


def main():
    try:
        try:
            config = load_config()
            build_temp_source(config)
            build_version_file(config)
            run_pyinstaller()
            output_file = publish_output()
        except Exception as exc:
            print(f"Build falhou: {exc}")
            raise SystemExit(1) from exc
    finally:
        cleanup()

    print(f"Build concluido: {output_file}")


if __name__ == "__main__":
    main()
