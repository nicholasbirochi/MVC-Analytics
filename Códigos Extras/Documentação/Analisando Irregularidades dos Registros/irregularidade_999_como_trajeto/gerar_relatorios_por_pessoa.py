from __future__ import annotations

import runpy
import sys
from pathlib import Path


def main() -> None:
    this_dir = Path(__file__).resolve().parent
    destino = (this_dir.parents[1] / "Irregularidade de 999 como Trajeto" / "gerar_relatorios_por_pessoa.py").resolve()

    if not destino.exists():
        raise FileNotFoundError(
            "Script principal nao encontrado no novo caminho: "
            f"{destino}"
        )

    print(f"[INFO] Script movido. Executando: {destino}", flush=True)
    sys.path.insert(0, str(destino.parent))
    runpy.run_path(str(destino), run_name="__main__")


if __name__ == "__main__":
    main()
