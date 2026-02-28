"""config.py

Configura ambiente, caminhos de dados e parametros globais do app.

Projeto: Dashboard presencialidade - Volkswagen do Brasil
Padronizacao:
- Tipagem adiantada: `from __future__ import annotations`
- Logger de modulo: `logging.getLogger(__name__)`
- Docstrings estilo Google (Args/Returns/Raises)
- Linhas <= 100 colunas quando possivel
"""
from __future__ import annotations

import datetime as dt
import locale
import logging
import os
import warnings
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Final, Iterable

import pandas as pd

# -----------------------------------------------------------------------------
# Valores padrao
# -----------------------------------------------------------------------------
DEFAULT_LOCALE: Final[str] = "pt_BR.utf8"
DEFAULT_CACHE_TIMEOUT: Final[int] = 900  # 15 minutos
DEFAULT_PORT: Final[int] = 8050
DEFAULT_FERIAS: Final[tuple[tuple[dt.datetime, dt.datetime], ...]] = (
    (dt.datetime(2023, 12, 18), dt.datetime(2024, 1, 7)),
    (dt.datetime(2024, 12, 23), dt.datetime(2025, 1, 12)),
)
DEFAULT_AREAS_FORA: Final[tuple[str, ...]] = ("B-SNP", "B-V")
PANDAS_CHAINED_ASSIGNMENT: Final[str] = "mode.chained_assignment"


@dataclass(frozen=True)
class Settings:
    """Config agregada do runtime."""

    base_dir: Path
    data_dir: Path
    dw_path: Path | None
    login_db_path: Path | None
    raw_data_dir: Path | None
    pasta_df_desligados: Path
    pasta_df_ativos: Path
    caminho_df_gptw: Path
    caminho_semana: Path
    caminho_datas: Path
    caminho_almoco: Path
    caminho_headcount: Path | None
    pandas_locale: str
    cache_ttl: int
    debug: bool
    port: int
    areas_fora: tuple[str, ...]
    ferias_coletivas: tuple[tuple[dt.datetime, dt.datetime], ...]


def _load_env_file(path: Path) -> None:
    """Carrega variaveis de um arquivo .env simples (sem dependencia externa)."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _resolve_path(raw: str | None, default: Path, bases: Iterable[Path]) -> Path:
    """Resolve um caminho relativo usando bases conhecidas."""
    if raw:
        candidate = Path(raw)
        if candidate.is_absolute():
            return candidate
        last = None
        for base in bases:
            resolved = (base / candidate).resolve()
            if resolved.exists():
                return resolved
            last = resolved
        if last is not None:
            return last
    return default


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Carrega configuracoes a partir de .env + defaults."""
    repo_root = Path(__file__).resolve().parents[4]
    project_dir = Path(__file__).resolve().parents[3]

    for candidate in (
        repo_root / ".env",
        repo_root / ".env.local",
        project_dir / ".env",
        project_dir / ".env.local",
    ):
        _load_env_file(candidate)

    base_dir = project_dir
    external_data_dir = (repo_root.parent / "_dados_ronda_local" / "project" / "database").resolve()
    internal_data_dir = (base_dir / "database").resolve()
    default_data_dir = external_data_dir if external_data_dir.exists() else internal_data_dir
    data_dir = _resolve_path(
        os.getenv("ND_DATA_DIR"),
        default_data_dir,
        bases=(repo_root, base_dir, external_data_dir, internal_data_dir),
    )
    dw_default = (data_dir / "dw_ronda.sqlite").resolve()
    dw_path = _resolve_path(
        os.getenv("RONDA_DW_PATH"),
        dw_default,
        bases=(repo_root, base_dir, data_dir, external_data_dir, internal_data_dir),
    )
    if not dw_path.exists():
        dw_path = None

    login_default = (data_dir / "db_login.sqlite").resolve()
    login_db_path = _resolve_path(
        os.getenv("RONDA_LOGIN_DB_PATH"),
        login_default,
        bases=(repo_root, base_dir, data_dir, external_data_dir, internal_data_dir),
    )
    if not login_db_path.exists():
        login_db_path = None

    raw_default = (repo_root.parent / "_dados_ronda_local" / "Base de Dados Original").resolve()
    raw_data_dir = _resolve_path(
        os.getenv("RONDA_RAW_DATA_DIR"),
        raw_default,
        bases=(repo_root, base_dir, repo_root.parent),
    )
    if not raw_data_dir.exists():
        raw_data_dir = None

    bases = (repo_root, base_dir, data_dir)
    pasta_df_desligados = _resolve_path(
        os.getenv("pasta_df_desligados"),
        data_dir / "Desligados.parquet",
        bases,
    )
    pasta_df_ativos = _resolve_path(
        os.getenv("pasta_df_ativos"),
        data_dir / "Ativos.parquet",
        bases,
    )
    caminho_df_gptw = _resolve_path(
        os.getenv("caminho_df_gptw"),
        data_dir / "GPTW.parquet",
        bases,
    )
    caminho_semana = _resolve_path(
        os.getenv("caminho_semana"),
        data_dir / "ArquivoFinalSemana.parquet",
        bases,
    )
    caminho_datas = _resolve_path(
        os.getenv("caminho_datas"),
        data_dir / "ArquivoFinalDatas.parquet",
        bases,
    )
    caminho_almoco = _resolve_path(
        os.getenv("caminho_almoco") or os.getenv("almoco"),
        data_dir / "Almoco.parquet",
        bases,
    )

    headcount_raw = os.getenv("caminho_headcount")
    caminho_headcount = (
        _resolve_path(headcount_raw, data_dir / "Headcount.parquet", bases)
        if headcount_raw
        else None
    )

    pandas_locale = os.getenv("ND_PANDAS_LOCALE", DEFAULT_LOCALE)
    cache_ttl = int(os.getenv("ND_CACHE_TTL", DEFAULT_CACHE_TIMEOUT))
    debug = str(os.getenv("ND_DEBUG", "false")).lower() in {"1", "true", "yes"}
    port = int(os.getenv("ND_PORT", DEFAULT_PORT))

    areas_env = os.getenv("AREAS_FORA", "")
    areas_fora = tuple(
        a.strip()
        for a in areas_env.split(",")
        if a.strip()
    ) or DEFAULT_AREAS_FORA

    ferias_coletivas = DEFAULT_FERIAS

    return Settings(
        base_dir=base_dir,
        data_dir=data_dir,
        dw_path=dw_path,
        login_db_path=login_db_path,
        raw_data_dir=raw_data_dir,
        pasta_df_desligados=pasta_df_desligados,
        pasta_df_ativos=pasta_df_ativos,
        caminho_df_gptw=caminho_df_gptw,
        caminho_semana=caminho_semana,
        caminho_datas=caminho_datas,
        caminho_almoco=caminho_almoco,
        caminho_headcount=caminho_headcount,
        pandas_locale=pandas_locale,
        cache_ttl=cache_ttl,
        debug=debug,
        port=port,
        areas_fora=areas_fora,
        ferias_coletivas=ferias_coletivas,
    )


# -----------------------------------------------------------------------------
# Atalhos/export para compatibilidade com os demais modulos
# -----------------------------------------------------------------------------
SETTINGS = get_settings()
BASE_DIR: Final[Path] = SETTINGS.base_dir
DATA_DIR: Final[Path] = SETTINGS.data_dir
DW_SQLITE_PATH: Final[Path] | None = SETTINGS.dw_path
LOGIN_DB_PATH: Final[Path] | None = SETTINGS.login_db_path
RAW_DATA_DIR: Final[Path] | None = SETTINGS.raw_data_dir
DEPARTAMENTOS_PARQUET: Final[Path] = SETTINGS.pasta_df_ativos
DATAS_PARQUET: Final[Path] = SETTINGS.caminho_datas
SEMANA_PARQUET: Final[Path] = SETTINGS.caminho_semana
AFASTADOS_PARQUET: Final[Path] = SETTINGS.pasta_df_desligados
GPTW_PARQUET: Final[Path] = SETTINGS.caminho_df_gptw
ALMOCO_PARQUET: Final[Path] = SETTINGS.caminho_almoco
HEADCOUNT_PARQUET: Final[Path] | None = SETTINGS.caminho_headcount
DEFAULT_LOCALE = SETTINGS.pandas_locale
AREAS_FORA: Final[tuple[str, ...]] = SETTINGS.areas_fora
FERIAS_COLETIVAS: Final[tuple[tuple[dt.datetime, dt.datetime], ...]] = SETTINGS.ferias_coletivas


# -----------------------------------------------------------------------------
# Configuracao e validacao
# -----------------------------------------------------------------------------
def configure_logging(debug: bool) -> None:
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )


def configure_runtime(settings: Settings | None = None) -> None:
    """Aplica configuracoes globais utilizadas pelo app Dash."""
    settings = settings or SETTINGS
    warnings.filterwarnings("ignore", category=FutureWarning)
    try:
        locale.setlocale(locale.LC_TIME, settings.pandas_locale)
    except locale.Error:
        pass
    pd.set_option(PANDAS_CHAINED_ASSIGNMENT, None)
    configure_logging(settings.debug)


def validate_data_files(
    required: tuple[Path, ...] | None = None,
    settings: Settings | None = None,
) -> None:
    """Valida a existencia das fontes de dados essenciais."""
    settings = settings or SETTINGS
    if settings.dw_path and settings.dw_path.exists():
        return

    if required is None:
        required = (
            DEPARTAMENTOS_PARQUET,
            DATAS_PARQUET,
            SEMANA_PARQUET,
            AFASTADOS_PARQUET,
            GPTW_PARQUET,
            ALMOCO_PARQUET,
        )
    missing = [p for p in required if p and not p.exists()]
    if missing:
        raise FileNotFoundError(
            "Arquivos ausentes: "
            + " | ".join(str(m) for m in missing)
            + " (ou configure RONDA_DW_PATH para usar o DW SQLite canonico)"
        )
