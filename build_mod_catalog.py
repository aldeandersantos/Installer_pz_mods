import argparse
import shutil
import subprocess
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_SOURCE = ROOT / "mods"
DEFAULT_OUTPUT = ROOT / "dist" / "mod_catalog"
DEFAULT_RELEASE_TAG = "mods-latest"
DEFAULT_REPO = "aldeandersantos/Installer_pz_mods"
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
    mod_dirs = sorted(item for item in source_dir.iterdir() if item.is_dir())
    mod_config_paths = [source_dir / file_name for file_name in MOD_CONFIG_FILES]
    available_config_files = [path for path in mod_config_paths if path.is_file()]

    if not mod_dirs and not available_config_files:
        raise ValueError(f"Nenhuma subpasta de mod encontrada em: {source_dir}")

    created_mods = 0
    skipped_mods = 0

    for mod_dir in mod_dirs:
        archive_name = f"{mod_dir.name}.zip"
        zip_path = output_dir / archive_name

        if zip_path.exists():
            skipped_mods += 1
            print(f"[skip] {mod_dir.name} -> {archive_name} ja existe")
        else:
            zip_directory(mod_dir, zip_path)
            created_mods += 1
            print(f"[ok] {mod_dir.name} -> {archive_name}")

    if available_config_files:
        mod_config_zip = output_dir / MOD_CONFIG_ARCHIVE

        if mod_config_zip.exists():
            print(f"[skip] configuracoes de menu -> {MOD_CONFIG_ARCHIVE} ja existe")
        else:
            zip_files(available_config_files, mod_config_zip)
            print(f"[ok] configuracoes de menu -> {MOD_CONFIG_ARCHIVE}")

    print(f"\nCatalogo gerado em: {output_dir}")
    print(f"Mods encontrados: {len(mod_dirs)}")
    print(f"ZIPs criados: {created_mods}")
    print(f"ZIPs ignorados por ja existirem: {skipped_mods}")
    if available_config_files:
        print("Arquivos de menu incluidos: " + ", ".join(path.name for path in available_config_files))


def ensure_gh_available():
    if shutil.which("gh") is None:
        raise RuntimeError(
            "gh CLI nao encontrado. Instale em https://cli.github.com/ e rode 'gh auth login'."
        )


def release_exists(tag, repo):
    result = subprocess.run(
        ["gh", "release", "view", tag, "--repo", repo],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def upload_catalog(output_dir, tag, repo):
    ensure_gh_available()

    zips = sorted(output_dir.glob("*.zip"))
    if not zips:
        raise ValueError(f"Nenhum .zip encontrado em {output_dir} para enviar.")

    if not release_exists(tag, repo):
        print(f"\nCriando release '{tag}' em {repo}...")
        subprocess.run(
            [
                "gh", "release", "create", tag,
                "--repo", repo,
                "--title", "Catalogo de mods",
                "--notes", "Catalogo de mods do instalador (gerado por build_mod_catalog.py).",
                "--latest=false",
            ],
            check=True,
        )

    print(f"\nEnviando {len(zips)} arquivo(s) para a release '{tag}'...")
    subprocess.run(
        [
            "gh", "release", "upload", tag,
            *[str(zip_path) for zip_path in zips],
            "--repo", repo,
            "--clobber",
        ],
        check=True,
    )
    print(f"Release '{tag}' atualizada com {len(zips)} asset(s).")


def main():
    parser = argparse.ArgumentParser(
        description="Gera um ZIP por mod e, opcionalmente, publica como release no GitHub."
    )
    parser.add_argument(
        "--source",
        default=str(DEFAULT_SOURCE),
        help="Pasta com um diretorio por mod. Padrao: ./mods",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help="Pasta de saida para os ZIPs.",
    )
    parser.add_argument(
        "--upload",
        action="store_true",
        help="Apos gerar, envia os ZIPs para a release do GitHub via gh CLI.",
    )
    parser.add_argument(
        "--tag",
        default=DEFAULT_RELEASE_TAG,
        help=f"Tag da release de mods. Padrao: {DEFAULT_RELEASE_TAG}",
    )
    parser.add_argument(
        "--repo",
        default=DEFAULT_REPO,
        help=f"Repositorio no formato owner/name. Padrao: {DEFAULT_REPO}",
    )
    args = parser.parse_args()

    output_dir = Path(args.output)
    build_catalog(Path(args.source), output_dir)

    if args.upload:
        upload_catalog(output_dir, args.tag, args.repo)
    else:
        print("\nProximo passo:")
        print("Rode novamente com --upload para publicar na release, ou suba os")
        print(f"ZIPs de {output_dir} manualmente para a release '{args.tag}' no GitHub.")


if __name__ == "__main__":
    main()
