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

from .core.config import CacheSettings, configure_runtime
from .api import register_all
from .ui.layout import LAYOUT


configure_runtime()

cache_settings = CacheSettings()

app = Dash(
    __name__,
    suppress_callback_exceptions=True,
    prevent_initial_callbacks="initial_duplicate",
)

cache = Cache(app.server, config={
    "CACHE_TYPE": cache_settings.cache_type,
    "CACHE_DEFAULT_TIMEOUT": cache_settings.default_timeout,
})
cache.init_app(app.server)

app.layout = LAYOUT

register_all(app)

server = app.server


if __name__ == "__main__":
    app.run(debug=False, port=8050)
