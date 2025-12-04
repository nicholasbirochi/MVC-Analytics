"""datasets.py

Carregamento de DataFrames a partir de arquivos Parquet com cache interno.

Projeto: Dashboard presencialidade — Volkswagen do Brasil
Padronização:
- Tipagem adiantada: `from __future__ import annotations`
- Logger de módulo: `logging.getLogger(__name__)`
- Docstrings estilo Google (Args/Returns/Raises)
- Linhas <= 100 colunas quando possível
"""
from __future__ import annotations


from functools import lru_cache
from typing import Callable

import pandas as pd

from ..config import (
    AFASTADOS_PARQUET,
    ALMOCO_PARQUET,
    DATAS_PARQUET,
    DEPARTAMENTOS_PARQUET,
    GPTW_PARQUET,
    SEMANA_PARQUET,
)

ParquetLoader = Callable[[str | bytes], pd.DataFrame]


def _read_parquet(path: str | bytes) -> pd.DataFrame:
    return pd.read_parquet(path)


def _load(path: str | bytes, reader: ParquetLoader = _read_parquet) -> pd.DataFrame:
    df = reader(path)
    return df.copy() if isinstance(df, pd.DataFrame) else df


@lru_cache(maxsize=None)
def load_departamentos(reader: ParquetLoader = _read_parquet) -> pd.DataFrame:
    return _load(str(DEPARTAMENTOS_PARQUET), reader)


@lru_cache(maxsize=None)
def load_datas(reader: ParquetLoader = _read_parquet) -> pd.DataFrame:
    return _load(str(DATAS_PARQUET), reader)


@lru_cache(maxsize=None)
def load_semana(reader: ParquetLoader = _read_parquet) -> pd.DataFrame:
    return _load(str(SEMANA_PARQUET), reader)


@lru_cache(maxsize=None)
def load_afastados(reader: ParquetLoader = _read_parquet) -> pd.DataFrame:
    return _load(str(AFASTADOS_PARQUET), reader)


@lru_cache(maxsize=None)
def load_gptw(reader: ParquetLoader = _read_parquet) -> pd.DataFrame:
    return _load(str(GPTW_PARQUET), reader)


@lru_cache(maxsize=None)
def load_almoco(reader: ParquetLoader = _read_parquet) -> pd.DataFrame:
    return _load(str(ALMOCO_PARQUET), reader)


def load_all() -> dict[str, pd.DataFrame]:
    """Carrega todos os DataFrames necessarios para o app."""
    return {
        "df_departamentos": load_departamentos(),
        "df_datas": load_datas(),
        "df_semana_merged": load_semana(),
        "df_afastados": load_afastados(),
        "df_gptw": load_gptw(),
        "df_almoco": load_almoco(),
    }