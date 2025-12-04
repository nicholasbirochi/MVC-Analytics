"""config.py

Configurações globais, caminhos de dados e parâmetros de runtime.

Projeto: Dashboard presencialidade — Volkswagen do Brasil
Padronização:
- Tipagem adiantada: `from __future__ import annotations`
- Logger de módulo: `logging.getLogger(__name__)`
- Docstrings estilo Google (Args/Returns/Raises)
- Linhas <= 100 colunas quando possível
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

import datetime as dt
import locale
import warnings
import os

import pandas as pd


# -----------------------------------------------------------------------------
# Diretores e caminhos base
# -----------------------------------------------------------------------------
BASE_DIR: Final[Path] = Path(__file__).resolve().parents[3] # .../Projeto
# Mantém compatibilidade com a estrutura do zip original
DATA_DIR: Final[Path] = (BASE_DIR / "database").resolve() # .../../database

# Arquivos de dados (Parquet)
DEPARTAMENTOS_PARQUET: Final[Path] = DATA_DIR / "Departamentos.parquet"
DATAS_PARQUET: Final[Path] = DATA_DIR / "ArquivoFinalDatas.parquet"
SEMANA_PARQUET: Final[Path] = DATA_DIR / "ArquivoFinalSemana.parquet"
AFASTADOS_PARQUET: Final[Path] = DATA_DIR / "Afastados.parquet"
GPTW_PARQUET: Final[Path] = DATA_DIR / "GPTW.parquet"
ALMOCO_PARQUET: Final[Path] = DATA_DIR / "Almoco.parquet"

# -----------------------------------------------------------------------------
# Locale / pandas
# -----------------------------------------------------------------------------
DEFAULT_LOCALE: Final[str] = "pt_BR.utf8"
PANDAS_CHAINED_ASSIGNMENT: Final[str] = "mode.chained_assignment"

# -----------------------------------------------------------------------------
# Cache
# -----------------------------------------------------------------------------
DEFAULT_CACHE_TIMEOUT: Final[int] = 900  # 15 minutos

# -----------------------------------------------------------------------------
# Constantes de domínio (ajuste se necessário)
# -----------------------------------------------------------------------------
# Períodos de férias coletivas (exemplo do unificado)
FERIAS_COLETIVAS: Final[tuple[tuple[dt.datetime, dt.datetime], ...]] = (
    (dt.datetime(2023, 12, 18), dt.datetime(2024, 1, 7)),
    (dt.datetime(2024, 12, 23), dt.datetime(2025, 1, 12)),
)

# Áreas tratadas como "fora" / viajantes por padrão
AREAS_FORA: Final[list[str]] = ["B-SNP", "B-V"]

# -----------------------------------------------------------------------------
# Config de cache para Flask-Caching (utilizado no Dash)
# -----------------------------------------------------------------------------
@dataclass
class CacheSettings:
    """Configura opções do Flask-Caching.

    Attributes:
        cache_type: Tipo de backend de cache (ex.: "SimpleCache").
        default_timeout: Tempo padrão (segundos) para expiração.
    """
    cache_type: str = "SimpleCache"
    default_timeout: int = DEFAULT_CACHE_TIMEOUT

# -----------------------------------------------------------------------------
# Função de inicialização de ambiente
# -----------------------------------------------------------------------------
def configure_runtime() -> None:
    """Aplica configurações globais utilizadas pelo app Dash."""
    warnings.filterwarnings("ignore", category=FutureWarning)
    try:
        locale.setlocale(locale.LC_TIME, DEFAULT_LOCALE)
    except locale.Error:
        # Em alguns ambientes Windows o locale pode não existir.
        # Mantemos o fluxo sem interromper a execução.
        pass
    pd.set_option(PANDAS_CHAINED_ASSIGNMENT, None)

def validate_data_files(required: tuple[Path, ...] | None = None) -> None:
    """Valida a existência dos arquivos .parquet essenciais.

    Args:
        required: Paths a validar. Por padrão, valida todos os conhecidos.
    Raises:
        FileNotFoundError: Se algum arquivo obrigatório não existir.
    """
    if required is None:
        required = (
            DEPARTAMENTOS_PARQUET,
            DATAS_PARQUET,
            SEMANA_PARQUET,
            AFASTADOS_PARQUET,
            GPTW_PARQUET,
            ALMOCO_PARQUET,
        )
    missing = [p for p in required if not p.exists()]
    if missing:
        raise FileNotFoundError(
            "Arquivos ausentes: " + " | ".join(str(m) for m in missing)
        )
