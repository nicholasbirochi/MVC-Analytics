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

if __package__:
    from .api.router import register_all
    from .core.config import SETTINGS, configure_runtime, validate_data_files
    from .domain.cache_utils import CacheOptions, as_dict
    from .ui.layout import LAYOUT
    from .ui.theme import GLOBAL_CSS
else:
    # Suporta execucao direta: `py .\scripts\src\main.py`
    import sys
    from pathlib import Path

    scripts_dir = Path(__file__).resolve().parent.parent
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))

    from src.api.router import register_all
    from src.core.config import SETTINGS, configure_runtime, validate_data_files
    from src.domain.cache_utils import CacheOptions, as_dict
    from src.ui.layout import LAYOUT
    from src.ui.theme import GLOBAL_CSS


def create_app() -> Dash:
    """Factory principal do aplicativo Dash/Flask."""
    configure_runtime(SETTINGS)
    validate_data_files(settings=SETTINGS)

    app = Dash(
        __name__,
        suppress_callback_exceptions=True,
        prevent_initial_callbacks="initial_duplicate",
    )
    try:
        app.index_string = f"""<!DOCTYPE html>
<html>
    <head>
        {{%metas%}}
        <title>{{%title%}}</title>
        {{%favicon%}}
        {{%css%}}
        <style>{GLOBAL_CSS}</style>
    </head>
    <body>
        {{%app_entry%}}
        <footer>
            {{%config%}}
            {{%scripts%}}
            {{%renderer%}}
        </footer>
    </body>
</html>"""
    except Exception:
        pass

    cache_options = CacheOptions()
    cache = Cache(app.server, config=as_dict(cache_options))
    cache.init_app(app.server)

    app.layout = LAYOUT
    register_all(app)
    return app


app = create_app()
server = app.server


if __name__ == "__main__":
    app.run(debug=SETTINGS.debug, port=SETTINGS.port)
