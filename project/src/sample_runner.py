"""CLI utilitario para validar o bootstrap do app MVC."""
from __future__ import annotations

from .main import create_app


if __name__ == "__main__":
    app = create_app()
    print("App carregado com sucesso.")
    print("Routes:", sorted({str(page.get("path", "")) for page in app._pages.values()}) if hasattr(app, "_pages") else "n/a")
