import argparse
import json
import shutil
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_SOURCE = ROOT / "mods"
DEFAULT_OUTPUT = ROOT / "dist" / "mod_catalog"
MOD_CONFIG_ARCHIVE = "mod_config.zip"
MOD_CONFIG_FILES = (
    "saved_modlists.txt",
    "modmanager-mods.txt",
    "pz_modlist_settings.cfg",
)


def zip_directory(source_dir, destination_zip):
    archive_base = destination_zip.with_suffix("")
    created = shutil.make_archive(
        str(archive_base),
        "zip",
        root_dir=source_dir.parent,
        base_dir=source_dir.name,
    )
    return Path(created)


def zip_files(source_files, destination_zip):
    with zipfile.ZipFile(destination_zip, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        for source_file in source_files:
            zip_file.write(source_file, arcname=source_file.name)
    return destination_zip


def build_catalog(source_dir, output_dir):
    if not source_dir.is_dir():
        raise FileNotFoundError(f"Pasta de origem nao encontrada: {source_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"mods": []}
    mod_dirs = sorted(item for item in source_dir.iterdir() if item.is_dir())
    mod_config_paths = [source_dir / file_name for file_name in MOD_CONFIG_FILES]
    available_config_files = [path for path in mod_config_paths if path.is_file()]

    if not mod_dirs and not available_config_files:
        raise ValueError(f"Nenhuma subpasta de mod encontrada em: {source_dir}")

    for mod_dir in mod_dirs:
        archive_name = f"{mod_dir.name}.zip"
        zip_path = output_dir / archive_name
        if zip_path.exists():
            zip_path.unlink()

        zip_directory(mod_dir, zip_path)
        manifest["mods"].append(
            {
                "name": mod_dir.name,
                "archive_name": archive_name,
                "file_id": "PREENCHER_NO_DRIVE",
            }
        )
        print(f"[ok] {mod_dir.name} -> {archive_name}")

    if available_config_files:
        mod_config_zip = output_dir / MOD_CONFIG_ARCHIVE
        if mod_config_zip.exists():
            mod_config_zip.unlink()

        zip_files(available_config_files, mod_config_zip)
        manifest["mods"].append(
            {
                "name": "__mod_config__",
                "archive_name": MOD_CONFIG_ARCHIVE,
                "file_id": "PREENCHER_NO_DRIVE",
            }
        )
        print(f"[ok] configuracoes de menu -> {MOD_CONFIG_ARCHIVE}")

    manifest_path = output_dir / "mods_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    print(f"\nCatalogo gerado em: {output_dir}")
    print(f"Mods processados: {len(mod_dirs)}")
    if available_config_files:
        print("Arquivos de menu incluidos: " + ", ".join(path.name for path in available_config_files))
    print("Proximo passo:")
    print("1. Suba os ZIPs para uma pasta compartilhada do Google Drive.")
    print("2. Configure o folder_id dessa pasta no config.json.")
    print("3. O mods_manifest.json fica como fallback opcional, nao e mais obrigatorio.")


def main():
    parser = argparse.ArgumentParser(
        description="Gera um ZIP por mod e um manifesto para o instalador."
    )
    parser.add_argument(
        "--source",
        default=str(DEFAULT_SOURCE),
        help="Pasta com um diretorio por mod. Padrao: ./mods",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help="Pasta de saida para ZIPs e manifesto.",
    )
    args = parser.parse_args()

    build_catalog(Path(args.source), Path(args.output))


if __name__ == "__main__":
    main()
