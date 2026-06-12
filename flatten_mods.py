"""
Achata mods da Steam Workshop dentro da pasta `mods`.

Estrutura de origem:  mods/<numero>/mods/<NomeRealDoMod>
Resultado:            mods/<NomeRealDoMod>
Depois apaga a pasta numerada (que fica vazia).

Por padrao roda em modo simulacao (dry-run). Para aplicar de verdade:
    python flatten_mods.py --apply
"""

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODS_ROOT = ROOT / "mods"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="Aplica de verdade (sem isso, so simula).")
    args = parser.parse_args()
    dry = not args.apply

    if dry:
        print(">>> MODO SIMULACAO (use --apply para mover de verdade)\n")

    if not MODS_ROOT.is_dir():
        print("Pasta 'mods' nao encontrada.")
        sys.exit(1)

    moved = 0
    skipped = 0

    # Pastas numericas: nome composto so por digitos
    for numbered in sorted(MODS_ROOT.iterdir()):
        if not numbered.is_dir() or not numbered.name.isdigit():
            continue

        mods_dir = numbered / "mods"
        if not mods_dir.is_dir():
            print(f"[ignorado] {numbered.name}: nao tem subpasta 'mods'")
            skipped += 1
            continue

        # Move cada mod de dentro de mods/<numero>/mods/ para mods/
        for mod in list(mods_dir.iterdir()):
            dest = MODS_ROOT / mod.name

            if dest.exists():
                print(f"[SUBSTITUIR] '{mod.name}' ja existe em mods/ -> apagando "
                      f"a antiga e usando a de {numbered.name}")
                if not dry:
                    if dest.is_dir():
                        shutil.rmtree(dest)
                    else:
                        dest.unlink()
                    shutil.move(str(mod), str(dest))
                moved += 1
                continue

            print(f"[mover] mods/{numbered.name}/mods/{mod.name}  ->  mods/{mod.name}")
            if not dry:
                shutil.move(str(mod), str(dest))
            moved += 1

        # Remove a pasta numerada se estiver vazia
        if not dry:
            remaining = list(numbered.rglob("*"))
            # so apaga se nao sobrou nenhum arquivo/pasta de mod
            leftover_files = [p for p in remaining if p.is_file()]
            leftover_mod_dirs = [p for p in mods_dir.iterdir()] if mods_dir.exists() else []
            if not leftover_files and not leftover_mod_dirs:
                shutil.rmtree(numbered)
                print(f"[apagar] pasta numerada vazia: {numbered.name}")
            else:
                print(f"[mantido] {numbered.name} ainda tem conteudo, nao apagado")
        else:
            print(f"[apagar] (simulado) pasta numerada: {numbered.name}")

    print(f"\nResumo: {moved} mod(s) movido(s), {skipped} pulado(s).")
    if dry:
        print("Nada foi alterado. Rode com --apply para efetivar.")


if __name__ == "__main__":
    main()
