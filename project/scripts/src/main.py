"""main.py

Módulo do dashboard de dados (Volkswagen do Brasil).

Projeto: Dashboard presencialidade — Volkswagen do Brasil
Padronização:
- Tipagem adiantada: `from __future__ import annotations`
- Logger de módulo: `logging.getLogger(__name__)`
- Docstrings estilo Google (Args/Returns/Raises)
- Linhas <= 100 colunas quando possível
"""
from __future__ import annotations
from dash import Dash
from flask_caching import Cache

from .core.config import configure_runtime
from .api.router import register_all
from .ui.layout import LAYOUT
from .domain.cache_utils import CacheOptions, as_dict


configure_runtime()

app = Dash(
    __name__,
    suppress_callback_exceptions=True,
    prevent_initial_callbacks="initial_duplicate",
)

cache_options = CacheOptions()
cache = Cache(app.server, config=as_dict(cache_options))
cache.init_app(app.server)

app.layout = LAYOUT

register_all(app)

server = app.server


if __name__ == "__main__":
    app.run(debug=False, port=8050)
