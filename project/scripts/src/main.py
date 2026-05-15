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
import os
import subprocess
import time
from pathlib import Path


DEFAULT_PORT = 8050


def _load_env_value(path: Path, key: str) -> str:
    if not path.exists():
        return ""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for raw in lines:
        line = str(raw or "").strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        current_key, value = line.split("=", 1)
        if current_key.strip() == key:
            return value.strip().strip('"').strip("'")
    return ""


def _startup_port() -> int:
    raw = os.getenv("ND_PORT", "").strip()
    if not raw:
        repo_root = Path(__file__).resolve().parents[4]
        project_dir = Path(__file__).resolve().parents[3]
        for candidate in (
            repo_root / ".env",
            repo_root / ".env.local",
            project_dir / ".env",
            project_dir / ".env.local",
        ):
            raw = _load_env_value(candidate, "ND_PORT")
            if raw:
                break
    try:
        port = int(raw)
    except Exception:
        port = DEFAULT_PORT
    return port if 0 < port <= 65535 else DEFAULT_PORT


def _pids_listening_on_port(port: int) -> set[int]:
    try:
        result = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        return set()
    if result.returncode != 0:
        return set()

    suffix = f":{int(port)}"
    pids: set[int] = set()
    for raw in result.stdout.splitlines():
        parts = raw.split()
        if len(parts) < 5:
            continue
        local_addr = parts[1]
        state = parts[3].upper()
        pid_raw = parts[-1]
        if state != "LISTENING" or not local_addr.endswith(suffix):
            continue
        try:
            pid = int(pid_raw)
        except Exception:
            continue
        if pid > 0 and pid != os.getpid():
            pids.add(pid)
    return pids


def _stop_previous_server(port: int) -> None:
    pids = _pids_listening_on_port(port)
    if not pids:
        return
    for pid in sorted(pids):
        try:
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid), "/T"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception:
            pass
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        if not _pids_listening_on_port(port):
            return
        time.sleep(0.3)


def create_app() -> Dash:
    """Factory principal do aplicativo Dash/Flask."""
    from dash import Dash
    from flask_caching import Cache

    if __package__:
        from .api.router import register_all
        from .core.config import SETTINGS, configure_runtime, validate_data_files
        from .domain.cache_utils import CacheOptions, as_dict
        from .ui.layout import LAYOUT
        from .ui.theme import GLOBAL_CSS, LANGUAGE_JS
    else:
        # Suporta execucao direta: `py .\scripts\src\main.py`
        import sys

        scripts_dir = Path(__file__).resolve().parent.parent
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))

        from src.api.router import register_all
        from src.core.config import SETTINGS, configure_runtime, validate_data_files
        from src.domain.cache_utils import CacheOptions, as_dict
        from src.ui.layout import LAYOUT
        from src.ui.theme import GLOBAL_CSS, LANGUAGE_JS

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
            <script>{LANGUAGE_JS}</script>
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
    app._ronda_settings = SETTINGS
    return app


if __name__ != "__main__":
    app = create_app()
    server = app.server
else:
    app = None
    server = None


if __name__ == "__main__":
    _stop_previous_server(_startup_port())
    app = create_app()
    server = app.server
    settings = app._ronda_settings
    app.run(debug=settings.debug, port=settings.port)
